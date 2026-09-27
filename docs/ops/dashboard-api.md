# Dashboard API contract

The future Next.js dashboard reads one document per mode. Today the document comes from
`arbitrage.ops.dashboard.dashboard(core, mode, orchestrator, engine)` and from `arbitrage-ops status --json`; an HTTP
server is deliberately not part of this change (the owner asked for no large dashboard before the core works). When
one is added it serves these paths over the same functions:

| Method | Path | Returns |
|---|---|---|
| GET | `/dashboard?mode=live` | the document below |
| GET | `/dashboard?mode=simulated` | the same shape for simulated books |
| GET | `/readiness` | `readiness(core)` |
| GET | `/mandate` | `Mandate.summary()` (never the file itself) |
| POST | `/pause` `{scope, reason}` | owner pause id (owner authentication required) |
| POST | `/resume` `{pause_id}` | ok |
| GET | `/actions?state=payment_unknown` | actions needing attention |
| GET | `/audit/verify` | `{ok, records}` |

No endpoint spends, approves or connects anything. Every figure is integer KRW unless named `rate` or `progress`.

## Document

```jsonc
{
  "generated_at": "2026-09-27T12:00:00+00:00",
  "mode": "live",                         // or "simulated"
  "label": "live: reconciled figures only", // or "SIMULATED: not real money"
  "counts_toward_goal": true,             // false for simulated, always
  "goal": {"target_realized_profit_krw": 1000000, "reconciled_net_profit_krw": 0, "progress": 0.0, "note": "..."},
  "mandate": {"environment": "live", "complete": false, "pending_fields": ["business.operating_country", "..."], "fingerprint": "..."},
  "sales": {"orders_placed": 0, "gross_sales": 0, "net_revenue": 0, "settled_cash": 0, "payment_receivables": 0},
  "profit": {"realized": 0, "provisional": 0, "contribution": 0, "operating": 0, "estimates_note": "..."},
  "cash": {"settled": 0, "unpaid_commitments": 0, "required_reserves": 0,
           "reserves": {"min_cash": 0, "operating": 0, "returns_provision": 0, "dispute_provision": 0, "tax_payable": 0},
           "liabilities": 0, "available_headroom": 0, "available_reinvestment": 0},
  "inventory": {"value": 0, "outstanding_purchases_prepaid": 0, "open_purchases": [], "age_by_sku": []},
  "reinvestment": {"realized_profit": 0, "allocated": 0, "eligible_unallocated": 0, "rate": 0.0, "budget_now": 0, "executed": 0, "reserved": 0},
  "costs": {"advertising": 0, "ai_credits": 0, "software": 0, "infrastructure": 0, "logistics": 0,
            "marketplace_and_payment_fees": 0, "samples": 0, "variable_by_account": {}, "fixed_by_account": {}},
  "agents": {"tasks": {}, "roles": {}, "credits_used": 0, "credits_budget": 0, "runs_active": 0, "escalated": 0},
  "workflows": {"pending": 0, "done": 0},
  "exceptions": {"failed_or_unknown_actions": [], "escalated_tasks": [], "recent_reconciliations": []},
  "limits": {"max_transaction_krw": 0, "max_daily_spend_krw": 0, "max_total_exposure_krw": 0, "max_cumulative_loss_krw": 0,
             "spent_today": 0, "exposure": 0},
  "pauses": [{"id": "...", "scope": "purchasing", "kind": "automatic", "condition": "cash_below_reserve", "reason": "...", "since": "..."}],
  "integrations": [{"id": "...", "status": "planned", "connected": false, "health": "unknown", "production_ready": false, "verdict": "..."}],
  "trial_balance_ok": true
}
```

Rules the UI must keep: show `label` on every page; show simulated and live on separate pages, never summed; the goal
bar reads `goal.reconciled_net_profit_krw` only; `profit.provisional` and provisions are estimates and say so;
`integrations[].production_ready` is the only "connected" indicator, a checklist item is not.
