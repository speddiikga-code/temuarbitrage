"""Layer 10, the reporting half: cost per request and per customer, cache and judge rates, savings, and what the
router has learned, straight from the tables and the ledger for one mode.  Simulated figures are labelled so."""

from __future__ import annotations

from typing import Any

from .. import ledger as L
from ..common import LIVE, SIMULATED, now_iso
from .service import ComputeRouter


def router_report(router: ComputeRouter, mode: str = LIVE) -> dict[str, Any]:
    core = router.core
    with core.db.transaction() as tx:
        by_status = {r["status"]: int(r["n"]) for r in tx.fetchall("SELECT status, COUNT(*) AS n FROM routed_requests WHERE mode = ? GROUP BY status", (mode,))}
        totals = tx.fetchone(
            "SELECT COUNT(*) AS n, COALESCE(SUM(cache_hit), 0) AS hits, COALESCE(SUM(provider_cost_krw), 0) AS provider_cost, "
            "COALESCE(SUM(attempts_cost_krw), 0) AS attempts_cost, COALESCE(SUM(charge_krw), 0) AS charged, COALESCE(SUM(fee_krw), 0) AS fees, "
            "COALESCE(SUM(CASE WHEN savings_verified = 1 THEN savings_krw ELSE 0 END), 0) AS verified_savings, "
            "COALESCE(SUM(CASE WHEN savings_verified = 0 THEN savings_krw ELSE 0 END), 0) AS estimated_savings, "
            "COALESCE(SUM(input_tokens_raw), 0) AS tokens_raw, COALESCE(SUM(input_tokens_sent), 0) AS tokens_sent "
            "FROM routed_requests WHERE mode = ?", (mode,))
        judged = tx.fetchone("SELECT COUNT(*) AS n, COALESCE(SUM(passed), 0) AS passed FROM route_executions WHERE mode = ? AND passed IS NOT NULL "
                             "AND stage <> 'preprocess'", (mode,))
        escalations = int(tx.scalar("SELECT COUNT(*) FROM route_executions WHERE mode = ? AND stage = 'escalation'", (mode,)))
        by_customer = tx.fetchall(
            "SELECT customer_id, COUNT(*) AS requests, COALESCE(SUM(provider_cost_krw), 0) AS provider_cost_krw, COALESCE(SUM(charge_krw), 0) AS charged_krw, "
            "COALESCE(SUM(fee_krw), 0) AS fee_krw FROM routed_requests WHERE mode = ? GROUP BY customer_id ORDER BY charged_krw DESC LIMIT 50", (mode,))
        by_route = tx.fetchall(
            "SELECT catalog_id, COUNT(*) AS calls, COALESCE(SUM(cost_krw), 0) AS cost_krw, COALESCE(AVG(quality_score_bp), 0) AS avg_quality_bp, "
            "COALESCE(SUM(passed), 0) AS passed FROM route_executions WHERE mode = ? GROUP BY catalog_id ORDER BY calls DESC", (mode,))
        catalog = router.catalog.list(tx, mode)
        stale = router.catalog.stale(tx, mode, 30)
        verified_ids = {row["id"] for row in catalog if row["price_verified"]}
        unverified_routes = sum(int(r["calls"]) for r in by_route if r["catalog_id"] not in verified_ids)
        unknown = core.gateway.list(tx, mode=mode, kind="inference_call", state="result_unknown", limit=50)
        bal = core.ledger.balances(tx, mode)
        customers = int(tx.scalar("SELECT COUNT(*) FROM customers WHERE mode = ?", (mode,)))
        cache = router.cache.stats(tx, mode)
        spent_today = router.daily_inference_spend(tx, mode)
    n = int(totals["n"])
    return {
        "generated_at": now_iso(),
        "mode": mode,
        "label": "SIMULATED: no real provider, customer or money" if mode == SIMULATED else "live: reconciled figures only",
        "customers": customers,
        "requests": {"total": n, "by_status": by_status, "cache_hits": int(totals["hits"]),
                     "cache_hit_rate": (int(totals["hits"]) / n) if n else 0.0, "escalations": escalations},
        "tokens": {"input_raw": int(totals["tokens_raw"]), "input_sent": int(totals["tokens_sent"]),
                   "compression": (1 - int(totals["tokens_sent"]) / int(totals["tokens_raw"])) if int(totals["tokens_raw"]) else 0.0,
                   "note": "token counts are estimates until a provider usage record replaces them"},
        "quality": {"judged": int(judged["n"]), "passed": int(judged["passed"]),
                    "pass_rate": (int(judged["passed"]) / int(judged["n"])) if int(judged["n"]) else 0.0},
        "money_krw": {"provider_cost_delivered": int(totals["provider_cost"]), "provider_cost_all_attempts": int(totals["attempts_cost"]),
                      "charged": int(totals["charged"]), "platform_fees": int(totals["fees"]),
                      "verified_savings": int(totals["verified_savings"]), "estimated_savings": int(totals["estimated_savings"]),
                      "inference_cost_booked": bal[L.INFERENCE_COST], "prepaid_provider_credits": bal[L.PROVIDER_PREPAID],
                      "customer_balances_owed": bal[L.CUSTOMER_BALANCES], "inference_spent_today": spent_today,
                      "note": "savings count only when every price in the comparison is verified and a usage record exists"},
        "by_customer": [dict(r) for r in by_customer],
        "by_route": [{**dict(r), "avg_quality": int(r["avg_quality_bp"]) / 10_000} for r in by_route],
        "catalog": {"entries": len(catalog), "verified_prices": sum(1 for c in catalog if c["price_verified"]),
                    "stale": stale, "calls_on_unverified_prices": unverified_routes},
        "cache": cache,
        "exceptions": {"result_unknown_calls": [{"id": a.id, "error": a.last_error} for a in unknown]},
        "limits": {"max_request_cost_krw": core.mandate.krw("router.max_request_cost_krw"),
                   "max_daily_inference_spend_krw": core.mandate.krw("router.max_daily_inference_spend_krw"),
                   "max_provider_prepaid_krw": core.mandate.krw("router.max_provider_prepaid_krw")},
    }
