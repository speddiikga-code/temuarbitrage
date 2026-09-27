# Working agreement

Two AI agents build this repo at the same time: **Claude** (Claude Code) and **GPT** (the owner's
other coding agent). The owner is the human who assigns work and merges. Read this file and
[TASKS.md](TASKS.md) before changing anything.

## The project

This is a dropship price-gap tool for the Korean market. It finds the same product cheaper at a supplier
(AliExpress, Temu, 1688, ...) than it sells for on Naver/Coupang, prices the resale after fees, ads,
returns and customs, and later lists the product and handles orders. Phase 1 is done and lives in `src/arbitrage`
(see README).

## Rules

1. **Extend, don't duplicate.** Build on `src/arbitrage`. If you disagree with a design, say so in
   a PR or issue. Don't write a parallel version.
2. **Claim before you start.** Put your name and branch on a task in `TASKS.md` in your first commit.
   Change files outside your task only through a PR that says why.
3. **Branches:** use `claude/<task>` or `gpt/<task>`, and open a PR into `main`. Never push to the other agent's
   branch. Never force-push a shared branch. The owner merges.
4. **Contracts** (below) change only in a PR titled `contract: ...` that updates the tests and this file.
   Adding a field is fine. Renaming or removing one needs a `schema_version` bump.
5. **Green before push:** `pip install -e ".[dev]" && pytest`. Use Python 3.11+. The only hard dependency is
   `requests`, so anything else goes in an optional extra in `pyproject.toml`.
6. **No secrets in git** (`.env` is ignored). **No scraping** of sites whose terms forbid it (Temu):
   use CSV import instead.
7. Match the surrounding code: small modules, dataclasses, no framework in the core package.

## Code map

| Path | What | Owner |
|---|---|---|
| `src/arbitrage/models.py` | `Offer`, `MatchResult`, `Quote`, `Opportunity` | shared contract |
| `src/arbitrage/sources/` | Supplier and market connectors (AliExpress, Naver Shopping, CSV) | Claude |
| `src/arbitrage/matching.py`, `images.py` | Same-product decision (model code, image hash, title, brand) | Claude |
| `src/arbitrage/pricing.py`, `default.toml` | Landed cost, fee math, price for margin | Claude |
| `src/arbitrage/scanner.py`, `report.py`, `cli.py` | Pipeline, CSV/JSON output, CLI | Claude |
| `workbench/` (new) | Review UI: approve/reject matches, adjust costs, re-price | GPT (proposed) |

## Contracts

**Source**: any object with `name: str` and `search(query: str, limit: int) -> list[Offer]`.
It raises `arbitrage.errors.SourceError` on API failure.

**Pricing:** call `arbitrage.pricing` (`landed_cost`, `quote`, `price_for_margin`). Don't
re-implement the fee math. Price for margin = `landed ÷ (1 − fee − ads − returns − margin)`.

**Scan JSON** (`arbitrage scan QUERY --json scan.json`), `schema_version: 1`:

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-09-24T10:00:00+00:00",
  "query": "주방 집게",
  "source_count": 50,
  "warnings": [],
  "fx": {"origin": "live", "USD": 1364.26},
  "policy": {"ad_rate": 0.1, "returns_rate": 0.03, "target_margin": 0.15, "...": "..."},
  "fee_rates": {"naver": 0.0663, "coupang": 0.1188},
  "opportunities": [                      // best profit first
    {
      "id": "aliexpress:1005001",         // stable across scans
      "source": { /* Offer */ },
      "landed_cost": 9415,                // KRW
      "market_low": 12900,                // KRW, cheapest matched listing
      "best_marketplace": "naver",
      "quotes": {"naver": {"marketplace": "naver", "list_price": 12900, "break_even": 11800,
                           "min_viable": 14500, "profit": 1234, "margin": 0.096, "viable": false}},
      "matches": [{"offer": { /* Offer */ }, "score": 0.83, "reasons": ["model WH1000XM5", "title 0.62"]}],
      "notes": []
    }
  ]
}
```

`Offer` fields are `platform, title, price, currency, url, shipping, image_url, seller, brand, model,
product_id, cross_border`.

**Review decisions** (proposed; the workbench owner may amend it with a `contract:` PR). The workbench writes
`data/decisions.json` and the future listing step reads it:

```jsonc
{
  "schema_version": 1,
  "decisions": [
    {"opportunity_id": "aliexpress:1005001", "decision": "approved",   // or "rejected"
     "market_url": "https://...", "list_on": ["naver"], "list_price": 14900,
     "overrides": {"shipping_krw": 2500}, "note": "", "decided_at": "2026-09-24T10:00:00+00:00"}
  ]
}
```
