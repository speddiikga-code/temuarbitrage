"""The scheduled work the business needs between sessions: guardrails, return windows, stale agent runs,
ambiguous supplier payments.  Each is a workflow handler; `register_standard` wires them and their schedules."""

from __future__ import annotations

from .core import Core
from .errors import ReconciliationRequired
from .orchestrator import Orchestrator
from .workflows import Workflow, WorkflowEngine, Outcome, done, fail, proceed

MODES_PAYLOAD_KEY = "mode"


def register_standard(engine: WorkflowEngine, core: Core, orchestrator: Orchestrator | None = None) -> None:
    def guardrails(wf: Workflow) -> Outcome:
        mode = wf.payload.get(MODES_PAYLOAD_KEY, "live")
        with core.db.transaction() as tx:
            result = core.guardrails.evaluate(tx, mode)
        return done({"triggered": result.triggered, "facts": result.facts})

    def close_return_windows(wf: Workflow) -> Outcome:
        mode = wf.payload.get(MODES_PAYLOAD_KEY, "live")
        closed = core.fulfillment.close_return_windows(mode)
        return done({"closed": closed})

    def reconcile_unknown_payments(wf: Workflow) -> Outcome:
        """Every purchase parked in payment_unknown asks the supplier what happened; none is retried blindly."""
        mode = wf.payload.get(MODES_PAYLOAD_KEY, "live")
        with core.db.transaction() as tx:
            parked = core.gateway.list(tx, mode=mode, state="payment_unknown")
        outcomes = {}
        still_unknown = []
        for action in parked:
            try:
                outcomes[action.id] = core.purchasing.reconcile(action.id, actor="reconciliation").state
            except ReconciliationRequired as e:
                outcomes[action.id] = "payment_unknown"
                still_unknown.append(str(e))
        if still_unknown:
            return fail("still unknown: " + "; ".join(still_unknown))  # retried with backoff
        return done({"reconciled": outcomes})

    def expire_agent_runs(wf: Workflow) -> Outcome:
        if orchestrator is None:
            return done({"expired": []})
        return done({"expired": orchestrator.expire()})

    def daily_cycle(wf: Workflow) -> Outcome:
        """The operating loop's housekeeping in order: reconcile, close windows, evaluate guardrails."""
        step = wf.step
        if step == "start":
            return proceed("reconcile")
        if step == "reconcile":
            engine.start("reconcile_unknown_payments", {MODES_PAYLOAD_KEY: wf.payload.get(MODES_PAYLOAD_KEY, "live")},
                         dedupe_key=f"{wf.id}:reconcile")
            return proceed("windows")
        if step == "windows":
            engine.start("close_return_windows", {MODES_PAYLOAD_KEY: wf.payload.get(MODES_PAYLOAD_KEY, "live")},
                         dedupe_key=f"{wf.id}:windows")
            return proceed("guardrails")
        if step == "guardrails":
            engine.start("guardrails", {MODES_PAYLOAD_KEY: wf.payload.get(MODES_PAYLOAD_KEY, "live")}, dedupe_key=f"{wf.id}:guardrails")
            return done()
        return fail(f"unknown step {step}", retry=False)

    engine.register("guardrails", guardrails)
    engine.register("close_return_windows", close_return_windows)
    engine.register("reconcile_unknown_payments", reconcile_unknown_payments)
    engine.register("expire_agent_runs", expire_agent_runs)
    engine.register("daily_cycle", daily_cycle)


def install_schedules(engine: WorkflowEngine, mode: str = "live") -> None:
    engine.add_schedule(f"guardrails:{mode}", "guardrails", 15 * 60, {MODES_PAYLOAD_KEY: mode})
    engine.add_schedule(f"reconcile:{mode}", "reconcile_unknown_payments", 60 * 60, {MODES_PAYLOAD_KEY: mode})
    engine.add_schedule(f"return_windows:{mode}", "close_return_windows", 6 * 60 * 60, {MODES_PAYLOAD_KEY: mode})
    engine.add_schedule("expire_agent_runs", "expire_agent_runs", 10 * 60, {})
    engine.add_schedule(f"daily_cycle:{mode}", "daily_cycle", 24 * 60 * 60, {MODES_PAYLOAD_KEY: mode})
