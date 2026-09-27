# Readiness report

As of 2026-09-27, branch `claude/operating-core-ujwp1e`. Updated by the operating-core task; the live-account facts
below are what the code and the registry can show, not a claim about any account the owner may hold.

## Built and tested (this branch, simulated only)

| Component | Where | Tested |
|---|---|---|
| Mandate loader, fail-closed pending sentinel, simulated/live separation | `ops/mandate.py`, `mandate.toml`, `mandate.simulated.toml` | yes |
| Double-entry ledger, chart, idempotent postings, trial balance | `ops/ledger.py`, `ops/books.py`, `ops/metrics.py` | yes |
| Budget governor: headroom, reinvestment formula, atomic reservations, retained-profit lock | `ops/budget.py` | yes (8 racing reservations, 2 succeed under one limit) |
| Policy controller, owner pause scopes, automatic guardrails | `ops/policy.py` | yes |
| Action gateway: idempotency keys, confirmations, five state machines, `payment_unknown` | `ops/gateway.py` | yes |
| Purchases, payments, fulfillment, listings, orders | `ops/purchases.py`, `ops/payments.py`, `ops/fulfillment.py`, `ops/listings.py`, `ops/orders.py` | yes, end to end with simulated adapters |
| Eligibility gates: import mode on every order and purchase, resale never personal-use, unknown duty never zero, price evidence, freight quote, certification, customs code once | `ops/purchases.py`, `ops/fulfillment.py`, `ops/listings.py` | yes |
| Integration registry loader (schema from the platform-eligibility task, PR #4) | `ops/registry.py` | yes; the real file's tests skip until PR #4 lands |
| 13 charters, orchestrator limits | `ops/charters.toml`, `ops/orchestrator.py` | yes |
| Durable workflows, leases, schedules, standard jobs | `ops/workflows.py`, `ops/jobs.py` | yes, including lease recovery |
| Audit hash chain, evidence store | `ops/audit.py`, `ops/evidence.py` | yes |
| Dashboard document, `arbitrage-ops` command, simulated demo | `ops/dashboard.py`, `ops/cli.py` | yes |
| Customs modes in pricing (commercial resale default, personal use, genuine sample) | `arbitrage/pricing.py` | yes, same-basket regression |

Test commands and results are in the pull request description and the thread; the current run is
`pytest` (SQLite) and `OPSCORE_TEST_DATABASE_URL=postgresql://... pytest` (each ops test again on PostgreSQL 16).

## Deployed

Nothing. `docker-compose.yml` and `Dockerfile` describe the target stack (PostgreSQL 16 + worker). They were written
here but not run: the development environment has no Docker daemon. First run belongs to whoever deploys.

## Live

Nothing. No live adapter exists; the registry has no production-ready integration; the live mandate has 26 pending
fields; live books are empty. Realized profit toward the KRW 1,000,000 target: ₩0.

## Pending: what the owner must supply before any live action

1. **The mandate.** All 26 `pending` fields in `mandate.toml`: business identity and operating country; storefronts,
   marketplaces, suppliers and payment processors actually held; funding sources and payout destinations; initial
   capital and authorized operating expenses; the six limits (transaction, daily, total exposure, cumulative loss,
   inventory value, per-SKU exposure); reserves (minimum cash, refund reserve rate and days, dispute reserve rate);
   reinvestment rate; AI credit and infrastructure budgets; permitted categories and external actions.
2. **Accounts.** A Naver Smart Store seller account (first channel), an AliExpress buyer account with DS API access
   (supplier), a payment processor and settlement account, a carrier account, a business registration and
   통신판매업 신고 for the seller identity. Coupang WING follows as the second channel. Temu is not an approved supplier.
3. **A fixed Seoul IP** for the Naver Commerce and Coupang WING APIs, and the PostgreSQL host.
4. **Registry entries** for each account in `integrations/registry.toml` with `status = "live"` and `connected = true`
   (platform-eligibility task owns the file).

## Blocked: what the core cannot do until code exists

- Live adapters (AliExpress DS API, Naver Commerce API, Coupang WING, processor, carrier). Each is a class with the
  same methods as its `Simulated*` counterpart; the gateway does not change.
- Market prices: the Naver 쇼핑 검색 API ended 2026-07-31; price evidence after that date must come from another
  licensed source or a manual capture with URL and date, or purchase verification refuses it.
- Fee tables (Naver 3% + Npay 3.63%; Coupang category fee + VAT + ₩55,000 monthly above ₩1,000,000 sales) belong to the
  pricing/scanner work; the core accrues whatever expected fee the order carries and books the settled actual.
- A freight quote per purchase: the core refuses a zero-shipping cross-border purchase without one.

## What a simulated result is not

A passing test, the demo, or a green checklist is not a connected account, a live purchase or realized profit. The
`SIMULATED: not real money` label on every simulated figure exists so that nobody reads it otherwise.
