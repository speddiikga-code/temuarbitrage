"""Policy controller and pause control: may this action happen at all, right now?

The controller is deterministic and fails closed.  A live action needs a live, complete mandate, a permitted
action kind and category, an amount under the transaction limit, no pause on its scope and a production-ready
integration.  A simulated action skips only the mandate-completeness and integration checks (the demo has to run
against a pending mandate) but still respects limits, categories and pauses of the simulated mandate.

Pauses: the owner pauses `purchasing` (no new commitments) or `all`.  Guardrails pause `purchasing` automatically
when reconciliation fails, a spending limit is reached, cash falls below the reserves, an integration is
unhealthy or cumulative losses pass the mandate.  Fulfilling, refunding and supporting existing orders continue
during a purchasing pause.  Automatic pauses do not lift themselves; the owner resumes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import ledger as L
from .audit import AuditTrail
from .common import LIVE, MODES, SIMULATED, new_id, now_iso
from .db import Database, Tx
from .errors import PolicyRefused
from .ledger import Ledger
from .mandate import Mandate

# Action kinds that commit new money or new exposure: blocked by a purchasing pause.
NEW_COMMITMENT_KINDS = frozenset({
    "supplier_purchase", "sample_purchase", "supplier_payment", "advertising", "software_expense",
    "infrastructure_expense", "reinvestment", "listing",
    "inference_call", "provider_prepayment",   # GlobalCompute Router: a provider call, and buying provider credits
})
# Actions that serve obligations we already have: allowed during a purchasing pause, blocked only by `all`.
OBLIGATION_KINDS = frozenset({"customer_payment", "fulfillment", "shipping_purchase", "refund", "customer_support"})
KNOWN_KINDS = NEW_COMMITMENT_KINDS | OBLIGATION_KINDS
# Money leaving us: the per-transaction limit applies. Customer payments and fulfillment steps are not our spend.
OUTGOING_KINDS = NEW_COMMITMENT_KINDS | frozenset({"refund", "shipping_purchase"})

SCOPES = ("purchasing", "all")


@dataclass(frozen=True)
class ActionRequest:
    kind: str
    idempotency_key: str
    mode: str
    amount_krw: int = 0
    amount: int = 0
    currency: str = "KRW"
    integration: str | None = None
    category: str | None = None
    sku: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)   # why it was refused (empty when allowed)
    checks: list[str] = field(default_factory=list)    # what was verified

    def raise_if_refused(self) -> None:
        if not self.allowed:
            raise PolicyRefused("; ".join(self.reasons))


class PauseControl:
    def __init__(self, db: Database, audit: AuditTrail):
        self.db = db
        self.audit = audit

    def pause(self, tx: Tx, scope: str, reason: str, by: str, kind: str = "owner", condition: str | None = None) -> str:
        """Start a pause; one active pause per (kind, condition, scope) so a guardrail that keeps firing adds nothing."""
        if scope not in SCOPES:
            raise PolicyRefused(f"pause scope must be one of {SCOPES}")
        existing = tx.fetchone(
            "SELECT id FROM pauses WHERE active = 1 AND kind = ? AND scope = ? AND COALESCE(condition, '') = ?",
            (kind, scope, condition or ""))
        if existing:
            return existing["id"]
        row = {"id": new_id("pause"), "scope": scope, "kind": kind, "condition": condition, "reason": reason,
               "active": 1, "started_at": now_iso(), "started_by": by}
        tx.insert("pauses", row)
        self.audit.record(tx, by, "pause", "pauses", row["id"], after=row)
        return row["id"]

    def resume(self, tx: Tx, pause_id: str, by: str) -> bool:
        before = tx.fetchone("SELECT * FROM pauses WHERE id = ? AND active = 1", (pause_id,))
        if not before:
            return False
        tx.update("pauses", "id", pause_id, {"active": 0, "ended_at": now_iso(), "ended_by": by})
        self.audit.record(tx, by, "resume", "pauses", pause_id, before=before)
        return True

    def active(self, tx: Tx) -> list[dict]:
        return tx.fetchall("SELECT * FROM pauses WHERE active = 1 ORDER BY started_at")

    def blocking(self, tx: Tx, kind: str) -> list[dict]:
        """Active pauses that stop an action of `kind`."""
        out = []
        for p in self.active(tx):
            if p["scope"] == "all" or (p["scope"] == "purchasing" and kind in NEW_COMMITMENT_KINDS):
                out.append(p)
        return out


class PolicyController:
    def __init__(self, db: Database, mandate: Mandate, pauses: PauseControl, audit: AuditTrail, registry=None):
        self.db = db
        self.mandate = mandate
        self.pauses = pauses
        self.audit = audit
        self.registry = registry

    def evaluate(self, tx: Tx, request: ActionRequest, actor: str = "system") -> Decision:
        d = Decision(allowed=True)
        m = self.mandate

        if request.mode not in MODES:
            d.reasons.append(f"unknown mode {request.mode!r}")
        if request.kind not in KNOWN_KINDS:
            d.reasons.append(f"unknown action kind {request.kind!r}")

        if request.mode == LIVE:
            if m.environment != LIVE:
                d.reasons.append(f"mandate {m.path} is a {m.environment} mandate and cannot authorize live actions")
            pending = m.pending_fields()
            if pending:
                d.reasons.append(f"mandate has {len(pending)} pending field(s): {', '.join(pending[:4])}{'...' if len(pending) > 4 else ''}")
            d.checks.append("mandate complete and live")
            if request.kind in NEW_COMMITMENT_KINDS | OBLIGATION_KINDS and not m.permits_action_kind(request.kind):
                d.reasons.append(f"mandate does not permit external action for {request.kind}")
            d.checks.append("action kind permitted")
            if self.registry is not None and request.integration:
                integ = self.registry.get(tx, request.integration)
                if integ is None:
                    d.reasons.append(f"integration {request.integration} is not registered")
                elif integ["mode"] != LIVE or not integ["production_ready"]:
                    d.reasons.append(f"integration {request.integration} is not production-ready (verify a real operation first)")
                elif integ["health"] == "unhealthy":
                    d.reasons.append(f"integration {request.integration} is unhealthy")
                d.checks.append("integration production-ready and healthy")
        elif request.mode == SIMULATED and request.integration and not request.integration.startswith("simulated:"):
            d.reasons.append(f"a simulated action may only use a simulated adapter, not {request.integration}")

        if request.category is not None and not m.permits_category(request.category):
            d.reasons.append(f"category {request.category!r} is not in the mandate's permitted categories")
        d.checks.append("category permitted")

        if request.amount_krw < 0:
            d.reasons.append("amount must not be negative")
        limit = m.krw("limits.max_transaction_krw")
        if request.kind in OUTGOING_KINDS and request.amount_krw > limit:
            d.reasons.append(f"amount {request.amount_krw:,} KRW exceeds the transaction limit {limit:,} KRW")
        d.checks.append("under transaction limit")

        for p in self.pauses.blocking(tx, request.kind):
            d.reasons.append(f"paused ({p['scope']}, {p['kind']}): {p['reason']}")
        d.checks.append("no blocking pause")

        d.allowed = not d.reasons
        self.audit.record(tx, actor, "policy_decision", "action_request", request.idempotency_key,
                          after={"kind": request.kind, "mode": request.mode, "amount_krw": request.amount_krw,
                                 "allowed": d.allowed, "reasons": d.reasons})
        return d


@dataclass
class GuardrailResult:
    triggered: list[str]
    pauses: list[str]
    facts: dict[str, Any]


class Guardrails:
    """The automatic pause conditions from the owner's brief, evaluated for one mode."""

    def __init__(self, db: Database, mandate: Mandate, ledger: Ledger, pauses: PauseControl, registry=None):
        self.db = db
        self.mandate = mandate
        self.ledger = ledger
        self.pauses = pauses
        self.registry = registry

    def evaluate(self, tx: Tx, mode: str, actor: str = "guardrails") -> GuardrailResult:
        m = self.mandate
        bal = self.ledger.balances(tx, mode)
        today = date.today().isoformat()
        triggered: list[str] = []
        facts: dict[str, Any] = {}

        failed = tx.scalar(
            "SELECT COUNT(*) FROM reconciliations WHERE mode = ? AND status IN ('failed', 'mismatch') AND finished_at >= ?",
            (mode, today))
        facts["reconciliations_failed_today"] = int(failed)
        if failed:
            triggered.append("reconciliation_failed")

        spent = tx.scalar(
            "SELECT COALESCE(SUM(COALESCE(committed_amount, amount)), 0) FROM budget_reservations "
            "WHERE mode = ? AND state IN ('reserved', 'committed') AND created_at >= ?", (mode, today))
        facts["spent_today"] = int(spent)
        if int(spent) >= m.krw("limits.max_daily_spend_krw"):
            triggered.append("daily_spend_limit_reached")
        exposure = bal[L.INVENTORY] + bal[L.PREPAID] + bal[L.PROVIDER_PREPAID] + int(tx.scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM budget_reservations WHERE mode = ? AND state = 'reserved'", (mode,)))
        facts["exposure"] = exposure
        if exposure >= m.krw("limits.max_total_exposure_krw"):
            triggered.append("exposure_limit_reached")

        reserves = (m.krw("reserves.min_cash_reserve_krw") + bal[L.RETURNS_PROVISION] + bal[L.DISPUTE_PROVISION]
                    + bal[L.TAX_PAYABLE])
        facts["settled_cash"], facts["required_reserves"] = bal[L.CASH], reserves
        if bal[L.CASH] < reserves:
            triggered.append("cash_below_reserve")

        if self.registry is not None:
            unhealthy = [r["name"] for r in self.registry.list(tx, mode) if r["health"] == "unhealthy"]
            facts["unhealthy_integrations"] = unhealthy
            if unhealthy:
                triggered.append("integration_unreliable")

        revenue = self.ledger.total(tx, mode, type="revenue")
        expenses = self.ledger.total(tx, mode, type="expense")
        loss = max(0, expenses - revenue)
        facts["cumulative_loss"] = loss
        if loss > m.krw("limits.max_cumulative_loss_krw"):
            triggered.append("loss_limit_exceeded")

        ids = [self.pauses.pause(tx, "purchasing", f"guardrail {cond} ({mode}): {facts}", actor, "automatic", f"{mode}:{cond}")
               for cond in triggered]
        return GuardrailResult(triggered, ids, facts)
