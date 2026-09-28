"""The router's scheduled work as workflow handlers: route a request durably, reconcile calls with unknown results,
close dispute windows (which realizes profit), expire the cache and report stale catalog prices."""

from __future__ import annotations

from ..errors import ReconciliationRequired
from ..workflows import Outcome, Workflow, WorkflowEngine, done, fail
from .service import ComputeRouter

MODE = "mode"


def register_router(engine: WorkflowEngine, router: ComputeRouter) -> None:
    def route_request(wf: Workflow) -> Outcome:
        """One durable request: every step is idempotent, so a retried workflow resumes at the request's step."""
        request_id = wf.payload["request_id"]
        try:
            row = router.route(request_id)
        except ReconciliationRequired as e:
            return fail(str(e))          # retried with backoff after the reconciliation job runs
        return done({"step": row["step"], "status": row["status"], "charge_krw": row["charge_krw"], "cache_hit": row["cache_hit"]})

    def reconcile_unknown_calls(wf: Workflow) -> Outcome:
        mode = wf.payload.get(MODE, "live")
        with router.db.transaction() as tx:
            parked = router.gateway.list(tx, mode=mode, kind="inference_call", state="result_unknown")
        outcomes, still = {}, []
        for action in parked:
            try:
                outcomes[action.id] = router.reconcile(action.id).state
            except ReconciliationRequired as e:
                outcomes[action.id] = "result_unknown"
                still.append(str(e))
        if still:
            return fail("still unknown: " + "; ".join(still))
        return done({"reconciled": outcomes})

    def close_request_windows(wf: Workflow) -> Outcome:
        return done({"closed": router.close_dispute_windows(wf.payload.get(MODE, "live"))})

    def expire_cache(wf: Workflow) -> Outcome:
        with router.db.transaction() as tx:
            n = router.cache.expire(tx)
        return done({"expired": n})

    def catalog_staleness(wf: Workflow) -> Outcome:
        mode = wf.payload.get(MODE, "live")
        with router.db.transaction() as tx:
            stale = router.catalog.stale(tx, mode, int(wf.payload.get("max_age_days", 30)))
        return done({"stale": stale})

    engine.register("route_request", route_request)
    engine.register("reconcile_unknown_calls", reconcile_unknown_calls)
    engine.register("close_request_windows", close_request_windows)
    engine.register("expire_route_cache", expire_cache)
    engine.register("catalog_staleness", catalog_staleness)


def install_router_schedules(engine: WorkflowEngine, mode: str = "live") -> None:
    engine.add_schedule(f"reconcile_calls:{mode}", "reconcile_unknown_calls", 30 * 60, {MODE: mode})
    engine.add_schedule(f"request_windows:{mode}", "close_request_windows", 6 * 60 * 60, {MODE: mode})
    engine.add_schedule("expire_route_cache", "expire_route_cache", 60 * 60, {})
    engine.add_schedule(f"catalog_staleness:{mode}", "catalog_staleness", 24 * 60 * 60, {MODE: mode, "max_age_days": 30})
