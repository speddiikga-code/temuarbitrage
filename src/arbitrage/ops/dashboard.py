"""The owner's numbers, as one JSON document per mode, straight from the ledger and the tables.

This is the read contract for the future Next.js dashboard (docs/api.md): the same dict is what `GET /dashboard`
returns.  Simulated and live are separate documents; only live realized profit counts toward the goal, and every
figure that is an estimate says so.
"""

from __future__ import annotations

from typing import Any

from . import ledger as L
from .common import LIVE, SIMULATED, now_iso
from .core import Core
from .metrics import compute, inventory_age


def dashboard(core: Core, mode: str = LIVE, orchestrator=None, engine=None) -> dict[str, Any]:
    m = core.mandate
    with core.db.transaction() as tx:
        metrics = compute(tx, core.ledger, mode)
        headroom = core.governor.headroom(tx, mode)
        reinvest = core.governor.reinvestment_budget(tx, mode)
        bal = core.ledger.balances(tx, mode)
        reservations = core.governor.active_reservations(tx, mode)
        pauses = core.pauses.active(tx)
        integrations = core.registry.list(tx)
        failed = core.gateway.list(tx, mode=mode, state="failed", limit=50) + core.gateway.list(tx, mode=mode, state="payment_unknown", limit=50)
        open_purchases = [a for a in core.gateway.list(tx, mode=mode, kind="supplier_purchase", limit=200) if a.state in ("ordered", "paid", "shipped")]
        escalations = tx.fetchall("SELECT id, role, title, error FROM tasks WHERE state = 'escalated' ORDER BY updated_at DESC LIMIT 50")
        agents = orchestrator.summary(tx) if orchestrator else None
        workflows: dict[str, int] = {}
        if engine:
            for w in engine.list(tx, limit=500):
                workflows[w.state] = workflows.get(w.state, 0) + 1
        age = inventory_age(tx, mode)
        reconciliations = tx.fetchall("SELECT integration, kind, status, finished_at, difference FROM reconciliations WHERE mode = ? ORDER BY finished_at DESC LIMIT 10", (mode,))
        target = m.krw("goals.target_realized_profit_krw")
        spent_today = core.governor.daily_spend(tx, mode)
        exposure = core.governor.exposure(tx, mode)
    counts_toward_goal = mode == LIVE
    return {
        "generated_at": now_iso(),
        "mode": mode,
        "label": metrics.label,
        "counts_toward_goal": counts_toward_goal,
        "goal": {
            "target_realized_profit_krw": target,
            "reconciled_net_profit_krw": metrics.realized_profit if counts_toward_goal else 0,
            "progress": (metrics.realized_profit / target) if counts_toward_goal and target else 0.0,
            "note": "live realized profit only: settled cash, past the return window, net of fees, FX and reserves" if counts_toward_goal
                    else "simulated figures never count toward the goal",
        },
        "mandate": {"environment": m.environment, "complete": m.complete, "pending_fields": m.pending_fields(), "fingerprint": m.fingerprint},
        "sales": {"orders_placed": metrics.orders_placed, "gross_sales": metrics.gross_sales, "net_revenue": metrics.net_revenue,
                  "settled_cash": metrics.settled_cash, "payment_receivables": metrics.payment_receivables},
        "profit": {"realized": metrics.realized_profit, "provisional": metrics.provisional_profit,
                   "contribution": metrics.contribution_profit, "operating": metrics.operating_profit,
                   "estimates_note": "provisional = orders not yet settled or inside the return window; provisions are estimates"},
        "cash": {"settled": headroom.settled_cash, "unpaid_commitments": headroom.unpaid_commitments,
                 "required_reserves": headroom.required_reserves, "reserves": {
                     "min_cash": headroom.min_cash_reserve, "operating": headroom.operating_reserve,
                     "returns_provision": headroom.returns_provision, "dispute_provision": headroom.dispute_provision,
                     "tax_payable": headroom.tax_payable},
                 "liabilities": metrics.outstanding_liabilities, "available_headroom": headroom.available,
                 "available_reinvestment": reinvest.budget},
        "inventory": {"value": metrics.inventory_value, "outstanding_purchases_prepaid": metrics.outstanding_purchases,
                      "open_purchases": [{"id": a.id, "sku": a.sku, "state": a.state, "amount_krw": a.amount_krw} for a in open_purchases],
                      "age_by_sku": [{"sku": r["sku"], "units": int(r["units"]), "value": int(r["value"]), "oldest": r["oldest"]} for r in age]},
        "reinvestment": {"realized_profit": reinvest.realized_profit, "allocated": reinvest.already_allocated,
                         "eligible_unallocated": reinvest.eligible_unallocated, "rate": reinvest.reinvestment_rate,
                         "budget_now": reinvest.budget,
                         "executed": sum(r.committed_amount or 0 for r in reservations if r.source == "reinvestment" and r.state == "committed"),
                         "reserved": sum(r.amount for r in reservations if r.state == "reserved")},
        "costs": {"advertising": bal[L.ADVERTISING], "ai_credits": bal[L.AI_CREDITS], "software": bal[L.SOFTWARE],
                  "infrastructure": bal[L.INFRASTRUCTURE], "logistics": bal[L.FREIGHT] + bal[L.DUTIES],
                  "marketplace_and_payment_fees": bal[L.MARKETPLACE_FEES] + bal[L.PAYMENT_FEES], "samples": bal[L.SAMPLES],
                  "variable_by_account": metrics.variable_costs, "fixed_by_account": metrics.fixed_costs},
        "agents": agents,
        "workflows": workflows,
        "exceptions": {"failed_or_unknown_actions": [{"id": a.id, "kind": a.kind, "state": a.state, "error": a.last_error} for a in failed],
                       "escalated_tasks": escalations, "recent_reconciliations": reconciliations},
        "limits": {"max_transaction_krw": m.krw("limits.max_transaction_krw"), "max_daily_spend_krw": m.krw("limits.max_daily_spend_krw"),
                   "max_total_exposure_krw": m.krw("limits.max_total_exposure_krw"), "max_cumulative_loss_krw": m.krw("limits.max_cumulative_loss_krw"),
                   "spent_today": spent_today, "exposure": exposure},
        "pauses": pauses,
        "integrations": [{"id": i["id"], "status": i["status"], "connected": i["connected"], "health": i["health"],
                          "production_ready": i["production_ready"], "verdict": i["verdict"]} for i in integrations],
        "trial_balance_ok": metrics.trial_balance_ok,
    }


def readiness(core: Core, orchestrator=None) -> dict[str, Any]:
    """What is built, tested, live, pending and blocked, in one place (docs/readiness.md is the prose version)."""
    m = core.mandate
    with core.db.transaction() as tx:
        integrations = core.registry.list(tx, LIVE)
        pauses = core.pauses.active(tx)
    return {
        "generated_at": now_iso(),
        "mandate": {"environment": m.environment, "complete": m.complete, "pending_fields": m.pending_fields()},
        "live_actions_possible": False if not m.complete or m.environment != LIVE else not any(p["scope"] == "all" for p in pauses),
        "integrations_production_ready": [i["id"] for i in integrations if i["production_ready"]],
        "integrations_not_ready": [{"id": i["id"], "status": i["status"], "manual_dependency": i["manual_dependency"]} for i in integrations if not i["production_ready"]],
        "pauses": pauses,
        "live_adapters_built": [name for name, a in core.adapters.items() if getattr(a, "mode", None) == LIVE and not type(a).__name__ == "LiveAdapterUnavailable"],
        "simulated_adapters": [name for name in core.adapters if name.startswith("simulated:")],
    }
