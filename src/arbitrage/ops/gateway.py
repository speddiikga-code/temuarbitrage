"""Controlled action gateway: every external action is an `Action` row with a unique transaction id, an idempotency
key and a state machine, and every state that means "money moved" or "goods moved" needs an external confirmation.

Three machines: customer payment (authorize, capture, settle, refund, dispute), supplier purchase (verify, reserve,
order, pay, ship, receive, with `payment_unknown` for ambiguous results) and order fulfillment (allocate, pack, ship,
deliver, return).  Other spending (ads, software, shipping labels) uses the generic spend machine.

Confirmations are unique per (source, kind, external reference): a supplier charge or processor event delivered
twice attaches once and changes nothing the second time, and one confirmation can never advance two actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .adapters import CONFIRMED, AdapterResult
from .audit import AuditTrail
from .budget import BudgetGovernor
from .common import LIVE, SIMULATED, canonical_json, fingerprint, loads, new_id, now_iso
from .db import Database, Tx
from .errors import ConfirmationRequired, IdempotencyConflict, InvalidTransition, NotConfigured, OpsError
from .policy import ActionRequest, PolicyController

# -- state machines ------------------------------------------------------------------------------------

PAYMENT = {
    "created": {"authorized", "failed"},
    "authorized": {"captured", "voided"},
    "captured": {"settled", "partially_refunded", "refunded", "disputed"},
    "settled": {"partially_refunded", "refunded", "disputed"},
    "partially_refunded": {"partially_refunded", "refunded", "disputed"},
    "disputed": {"dispute_won", "dispute_lost"},
    "dispute_won": {"partially_refunded", "refunded"},
    "dispute_lost": set(), "refunded": set(), "voided": set(), "failed": set(),
}
PAYMENT_CONFIRMATIONS = {
    "authorized": "authorization", "captured": "capture", "settled": "settlement", "partially_refunded": "refund",
    "refunded": "refund", "disputed": "dispute_opened", "dispute_won": "dispute_closed", "dispute_lost": "dispute_closed",
    "voided": "void",
}

PURCHASE = {
    "proposed": {"verified", "rejected"},
    "verified": {"reserved", "rejected"},
    "reserved": {"ordered", "payment_unknown", "failed", "cancelled"},
    "ordered": {"paid", "payment_unknown", "cancelled"},
    "payment_unknown": {"ordered", "paid", "failed"},
    "paid": {"shipped", "refunded"},
    "shipped": {"received", "lost"},
    "received": set(), "rejected": set(), "failed": set(), "cancelled": set(), "refunded": set(), "lost": set(),
}
PURCHASE_CONFIRMATIONS = {"ordered": "supplier_order", "paid": "payment_receipt", "shipped": "shipment",
                          "received": "receiving", "refunded": "supplier_refund"}

SPEND = {
    "proposed": {"reserved", "rejected"},
    "reserved": {"paid", "payment_unknown", "failed", "cancelled"},
    "payment_unknown": {"paid", "failed"},
    "paid": set(), "rejected": set(), "failed": set(), "cancelled": set(),
}
SPEND_CONFIRMATIONS = {"paid": "payment_receipt"}

FULFILLMENT = {
    "pending": {"allocated", "cancelled"},
    "allocated": {"packed", "cancelled"},
    "packed": {"shipped", "cancelled"},
    "shipped": {"delivered", "return_requested", "lost"},
    "delivered": {"completed", "return_requested"},
    "return_requested": {"returned", "completed"},
    "completed": {"return_requested"},   # goodwill returns after the window
    "returned": set(), "cancelled": set(), "lost": set(),
}
FULFILLMENT_CONFIRMATIONS = {"shipped": "shipment", "delivered": "delivery", "returned": "return_receipt"}

LISTING = {
    "proposed": {"verified", "rejected"},
    "verified": {"listed", "rejected"},
    "listed": {"delisted"},
    "delisted": {"listed"},
    "rejected": set(),
}
LISTING_CONFIRMATIONS = {"listed": "listing", "delisted": "delisting"}

MACHINES: dict[str, tuple[dict, dict, str]] = {
    "listing": (LISTING, LISTING_CONFIRMATIONS, "proposed"),
    "customer_payment": (PAYMENT, PAYMENT_CONFIRMATIONS, "created"),
    "supplier_purchase": (PURCHASE, PURCHASE_CONFIRMATIONS, "proposed"),
    "sample_purchase": (PURCHASE, PURCHASE_CONFIRMATIONS, "proposed"),
    "fulfillment": (FULFILLMENT, FULFILLMENT_CONFIRMATIONS, "pending"),
    "advertising": (SPEND, SPEND_CONFIRMATIONS, "proposed"),
    "software_expense": (SPEND, SPEND_CONFIRMATIONS, "proposed"),
    "infrastructure_expense": (SPEND, SPEND_CONFIRMATIONS, "proposed"),
    "shipping_purchase": (SPEND, SPEND_CONFIRMATIONS, "proposed"),
    "supplier_payment": (SPEND, SPEND_CONFIRMATIONS, "proposed"),
}


def machine_for(kind: str) -> tuple[dict, dict, str]:
    try:
        return MACHINES[kind]
    except KeyError:
        raise OpsError(f"no state machine for action kind {kind!r}") from None


@dataclass
class Action:
    id: str
    idempotency_key: str
    kind: str
    mode: str
    state: str
    amount: int
    currency: str
    amount_krw: int
    integration: str | None
    reference_type: str | None
    reference_id: str | None
    reservation_id: str | None
    sku: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    last_error: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Action":
        return cls(row["id"], row["idempotency_key"], row["kind"], row["mode"], row["state"], int(row["amount"]),
                   row["currency"], int(row["amount_krw"]), row["integration"], row["reference_type"], row["reference_id"],
                   row["reservation_id"], row["sku"], loads(row["payload"]), row["created_at"], row["updated_at"], row["last_error"])

    def request(self) -> ActionRequest:
        """The request this action came from, for re-evaluating policy before an external call."""
        return ActionRequest(self.kind, self.idempotency_key, self.mode, self.amount_krw, self.amount, self.currency,
                             self.integration, self.payload.get("category"), self.sku, self.reference_type,
                             self.reference_id, self.payload)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class Confirmation:
    id: str
    action_id: str
    source: str
    kind: str
    external_reference: str
    mode: str
    amount: int | None = None
    currency: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: str = ""


def _request_fingerprint(r: ActionRequest) -> str:
    return fingerprint({"kind": r.kind, "mode": r.mode, "amount": r.amount, "currency": r.currency,
                        "amount_krw": r.amount_krw, "integration": r.integration, "category": r.category, "sku": r.sku,
                        "reference": [r.reference_type, r.reference_id], "payload": r.payload})


class ActionGateway:
    def __init__(self, db: Database, policy: PolicyController, governor: BudgetGovernor, audit: AuditTrail,
                 registry=None, adapters: dict[str, Any] | None = None):
        self.db = db
        self.policy = policy
        self.governor = governor
        self.audit = audit
        self.registry = registry
        self.adapters = adapters or {}

    # -- submission (idempotent) -----------------------------------------------------------------------

    def submit(self, request: ActionRequest, actor: str = "system", tx: Tx | None = None) -> Action:
        if tx is not None:
            return self._submit(tx, request, actor)
        with self.db.transaction() as tx2:
            return self._submit(tx2, request, actor)

    def _submit(self, tx: Tx, request: ActionRequest, actor: str) -> Action:
        fp = _request_fingerprint(request)
        existing = tx.fetchone("SELECT * FROM actions WHERE idempotency_key = ?", (request.idempotency_key,))
        if existing:
            if existing["request_fingerprint"] != fp:
                raise IdempotencyConflict(f"idempotency key {request.idempotency_key!r} was already used for a different request")
            return Action.from_row(existing)
        _, _, initial = machine_for(request.kind)
        self.policy.evaluate(tx, request, actor).raise_if_refused()
        now = now_iso()
        row = {
            "id": new_id("txn"), "idempotency_key": request.idempotency_key, "kind": request.kind, "mode": request.mode,
            "state": initial, "amount": request.amount, "currency": request.currency, "amount_krw": request.amount_krw,
            "integration": request.integration, "reference_type": request.reference_type, "reference_id": request.reference_id,
            "reservation_id": None, "sku": request.sku, "request_fingerprint": fp, "payload": canonical_json(request.payload),
            "created_at": now, "updated_at": now, "last_error": None,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        tx.execute(f"INSERT INTO actions ({cols}) VALUES ({marks}) ON CONFLICT (idempotency_key) DO NOTHING", tuple(row.values()))
        stored = tx.fetchone("SELECT * FROM actions WHERE idempotency_key = ?", (request.idempotency_key,))
        if stored["request_fingerprint"] != fp:
            raise IdempotencyConflict(f"idempotency key {request.idempotency_key!r} raced with a different request")
        if stored["id"] == row["id"]:
            self.audit.record(tx, actor, "action_created", "actions", row["id"], after=row)
        return Action.from_row(stored)

    # -- reading ---------------------------------------------------------------------------------------

    def get(self, tx: Tx, action_id: str) -> Action:
        row = tx.fetchone("SELECT * FROM actions WHERE id = ?", (action_id,))
        if not row:
            raise OpsError(f"unknown action {action_id}")
        return Action.from_row(row)

    def by_key(self, tx: Tx, idempotency_key: str) -> Action | None:
        row = tx.fetchone("SELECT * FROM actions WHERE idempotency_key = ?", (idempotency_key,))
        return Action.from_row(row) if row else None

    def list(self, tx: Tx, mode: str | None = None, kind: str | None = None, state: str | None = None, limit: int = 100) -> list[Action]:
        sql, params = "SELECT * FROM actions WHERE 1 = 1", []
        for col, val in (("mode", mode), ("kind", kind), ("state", state)):
            if val:
                sql += f" AND {col} = ?"
                params.append(val)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [Action.from_row(r) for r in tx.fetchall(sql, params)]

    def transitions(self, tx: Tx, action_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM action_transitions WHERE action_id = ? ORDER BY at, id", (action_id,))

    def confirmations(self, tx: Tx, action_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM external_confirmations WHERE action_id = ? ORDER BY received_at, id", (action_id,))

    # -- confirmations ---------------------------------------------------------------------------------

    @staticmethod
    def _normalize(confirmation) -> Confirmation:
        if isinstance(confirmation, Confirmation):
            return confirmation
        if isinstance(confirmation, AdapterResult):
            if confirmation.status != CONFIRMED:
                raise ConfirmationRequired(f"adapter result is {confirmation.status}, not confirmed: {confirmation.error}")
            if not confirmation.reference:
                raise ConfirmationRequired("confirmed adapter result has no external reference")
            return Confirmation("", "", confirmation.source, confirmation.kind, confirmation.reference, confirmation.mode,
                                confirmation.amount, confirmation.currency, dict(confirmation.payload))
        if isinstance(confirmation, dict):
            for k in ("source", "kind", "reference", "mode"):
                if not confirmation.get(k):
                    raise ConfirmationRequired(f"confirmation record needs {k!r}")
            return Confirmation("", "", confirmation["source"], confirmation["kind"], str(confirmation["reference"]),
                                confirmation["mode"], confirmation.get("amount"), confirmation.get("currency"),
                                dict(confirmation.get("payload", {})))
        raise ConfirmationRequired(f"unsupported confirmation {type(confirmation).__name__}")

    def record_confirmation(self, tx: Tx, action: Action, confirmation, actor: str = "system") -> tuple[Confirmation, bool]:
        """Attach a confirmation to `action`. Returns (confirmation, created). Reused references are refused."""
        c = self._normalize(confirmation)
        if c.mode != action.mode:
            raise OpsError(f"a {c.mode} confirmation cannot advance a {action.mode} action")
        if action.mode == SIMULATED and not c.source.startswith("simulated:"):
            raise OpsError(f"simulated action {action.id} accepts only simulated confirmations, not {c.source}")
        if action.mode == LIVE and c.source.startswith("simulated:"):
            raise OpsError(f"live action {action.id} cannot be advanced by simulated source {c.source}")
        existing = tx.fetchone("SELECT * FROM external_confirmations WHERE source = ? AND kind = ? AND external_reference = ?",
                               (c.source, c.kind, c.external_reference))
        if existing:
            if existing["action_id"] != action.id:
                raise OpsError(f"{c.kind} {c.external_reference} from {c.source} already belongs to action {existing['action_id']}")
            return Confirmation(existing["id"], action.id, c.source, c.kind, c.external_reference, c.mode,
                                existing["amount"], existing["currency"], loads(existing["payload"]), existing["received_at"]), False
        row = {"id": new_id("conf"), "action_id": action.id, "source": c.source, "kind": c.kind,
               "external_reference": c.external_reference, "amount": c.amount, "currency": c.currency,
               "payload": canonical_json(c.payload), "received_at": now_iso(), "mode": c.mode}
        tx.insert("external_confirmations", row)
        self.audit.record(tx, actor, "confirmation_recorded", "external_confirmations", row["id"], after=row)
        return Confirmation(row["id"], action.id, c.source, c.kind, c.external_reference, c.mode, c.amount, c.currency,
                            c.payload, row["received_at"]), True

    # -- transitions -----------------------------------------------------------------------------------

    def transition(self, tx: Tx, action_id: str, to_state: str, *, confirmation=None, reason: str | None = None,
                   actor: str = "system", payload: dict | None = None, reservation_id: str | None = None,
                   error: str | None = None) -> Action:
        action = self.get(tx, action_id)
        machine, required, _ = machine_for(action.kind)
        if to_state not in machine:
            raise InvalidTransition(f"{action.kind} has no state {to_state!r}")
        needed = required.get(to_state)
        conf: Confirmation | None = None
        if needed:
            if confirmation is None:
                raise ConfirmationRequired(f"{action.kind} {action.id}: {action.state} -> {to_state} needs a {needed} confirmation record")
            conf, created = self.record_confirmation(tx, action, confirmation, actor)
            if conf.kind != needed:
                raise ConfirmationRequired(f"{action.kind} {action.id}: {to_state} needs a {needed} confirmation, got {conf.kind}")
            if not created:
                already = tx.fetchone("SELECT id FROM action_transitions WHERE action_id = ? AND confirmation_id = ? AND to_state = ?",
                                      (action.id, conf.id, to_state))
                if already:
                    return action  # the same event delivered again: nothing changes
        if to_state not in machine.get(action.state, set()):
            if action.state == to_state and conf is None:
                return action
            raise InvalidTransition(f"{action.kind} {action.id} cannot go from {action.state} to {to_state}")
        now = now_iso()
        tx.insert("action_transitions", {"id": new_id("tr"), "action_id": action.id, "from_state": action.state,
                                         "to_state": to_state, "at": now, "confirmation_id": conf.id if conf else None, "reason": reason})
        changes: dict[str, Any] = {"state": to_state, "updated_at": now, "last_error": error}
        if payload:
            changes["payload"] = canonical_json({**action.payload, **payload})
        if reservation_id is not None:
            changes["reservation_id"] = reservation_id
        tx.update("actions", "id", action.id, changes)
        self.audit.record(tx, actor, "transition", "actions", action.id,
                          before={"state": action.state}, after={"state": to_state, "confirmation": conf.id if conf else None, "reason": reason})
        return self.get(tx, action.id)

    def note_error(self, tx: Tx, action_id: str, error: str) -> None:
        tx.update("actions", "id", action_id, {"last_error": error, "updated_at": now_iso()})

    # -- adapters --------------------------------------------------------------------------------------

    def adapter(self, tx: Tx, action: Action):
        """The adapter allowed to act for this action. Live needs a production-ready integration and a live adapter."""
        name = action.integration
        if not name:
            raise NotConfigured(f"action {action.id} names no integration")
        adapter = self.adapters.get(name)
        if action.mode == SIMULATED:
            if adapter is None or getattr(adapter, "mode", None) != SIMULATED or not name.startswith("simulated:"):
                raise NotConfigured(f"no simulated adapter registered as {name}")
            return adapter
        if self.registry is None:
            raise NotConfigured("live actions need an integration registry")
        integ = self.registry.get(tx, name)
        if integ is None or not integ["production_ready"] or integ["mode"] != LIVE:
            raise NotConfigured(f"integration {name} is not production-ready; verify a real operation before live use")
        if adapter is None or getattr(adapter, "mode", None) != LIVE:
            raise NotConfigured(f"no live adapter for {name}: {integ.get('manual_dependency') or 'not built yet'}")
        return adapter
