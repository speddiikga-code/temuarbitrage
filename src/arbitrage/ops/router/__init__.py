"""GlobalCompute Router: one request, the cheapest compliant route, an equivalent-quality result.

Built on the operating core (`arbitrage.ops`): the mandate decides what may be called and billed, the ledger books
every won, the budget governor reserves platform money before a provider call, the action gateway records each
call as an `inference_call` with the provider's usage record as its confirmation, and pauses, guardrails and the
audit chain apply unchanged.

Layers and where they live:

| Layer | Name                        | Module            |
|-------|-----------------------------|-------------------|
| 1     | Universal gateway           | `service.py`      |
| 2     | Intent compiler             | `intent.py`       |
| 3     | Semantic compressor         | `intent.py`       |
| 4     | Language router             | `intent.py`       |
| 5     | Global model marketplace    | `catalog.py`      |
| 6     | Cost-aware router           | `planner.py`      |
| 7     | Semantic cache              | `cache.py`        |
| 8     | Execution orchestrator      | `planner.py` (plan), `service.py` (run) |
| 9     | Quality judge               | `judge.py`        |
| 10    | Billing and optimization    | `billing.py`, `reporting.py`, `catalog.py` (learning) |

Everything here is simulated until a live provider adapter, a live billing processor and the owner's mandate exist:
the simulated provider returns scripted text and token counts, the simulated judge scripted scores.  No live model
is called anywhere in this package.
"""
