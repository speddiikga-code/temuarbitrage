# Readiness report

As of 2026-09-27, branch `claude/operating-core-ujwp1e`; router rows added 2026-09-28 on
`claude/compute-router-core-xqjk4d`. Updated by the operating-core and router tasks; the live-account facts below are
what the code and the registry can show, not a claim about any account the owner may hold.

On 2026-09-28 the owner switched the business the core runs to the GlobalCompute Router (`business.domain =
"compute_router"` in `mandate.toml`). The ecommerce rows below still describe code that exists and passes its tests;
the live mandate now requires the router's fields, not the storefront and supplier ones. See [router.md](router.md).

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
| Router: intent, compression, language plan | `ops/router/intent.py` | yes |
| Router: catalog with evidence, compliance gate, cost-aware planner, escalation ladder, decomposition | `ops/router/catalog.py`, `ops/router/planner.py` | yes |
| Router: semantic cache, quality judge (structural checks + scorer), `inference_call` and `provider_prepayment` actions | `ops/router/cache.py`, `ops/router/judge.py`, `ops/gateway.py` | yes |
| Router: platform-credits and own-keys billing, dispute windows, refunds, realized profit on requests | `ops/router/billing.py`, `ops/router/service.py`, `ops/metrics.py` | yes, end to end with simulated providers, judge and processor |
| Router: reconciliation of unknown results, workflows and schedules, report, CLI (`router demo/requests/catalog`), dashboard section | `ops/router/service.py`, `ops/router/jobs.py`, `ops/router/reporting.py`, `ops/cli.py` | yes |
| Router: the twelve provider rules from `docs/provider_terms.md` §3 (registry-cleared providers, end-user country screening, pre-disclosed providers, PRC opt-in and personal-information classifier, no free tiers, per-tenant cache, residency as an explicit choice, terms and AI disclosure at registration, no pass-through, list price per call) | `ops/router/providers.py`, `ops/router/planner.py`, `ops/router/billing.py`, `ops/router/intent.py` | yes |

Test commands and results are in the pull request description and the thread; the current run is
`pytest` (SQLite) and `OPSCORE_TEST_DATABASE_URL=postgresql://... pytest` (each ops test again on PostgreSQL 16).

## Deployed

Nothing. `docker-compose.yml` and `Dockerfile` describe the target stack (PostgreSQL 16 + worker). They were written
here but not run: the development environment has no Docker daemon. First run belongs to whoever deploys.

## Live

Nothing. No live adapter exists; the registry has no production-ready integration; the live mandate has 34 pending
fields for the router domain; live books are empty; no customer exists. Realized profit toward the KRW 1,000,000
target: ₩0.

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

### For the router domain (the live mandate since 2026-09-28)

1. **The mandate.** Every `[router]` field (providers, permitted regions and task types, billing modes, per-request,
   daily, prepaid and exposure caps, platform fee rate, savings share rate, minimum quality, the published terms and
   privacy policy URLs and the providers that policy discloses) plus the generic fields: business identity, payment
   processors, funding source and payout destination, capital, limits, reserves.
2. **Accounts.** A payment processor (Stripe or Toss) that settles to the owner's bank; an account and funding at
   each provider the mandate names, with keys held outside git; business registration and VAT treatment for
   exported services.
3. **Hosting** for PostgreSQL and the worker, and later an HTTP surface for customers.
4. **A customer.** None exists. The first paid routed request needs one who has agreed to terms and a price.

## Blocked: what the core cannot do until code exists

- Live adapters (AliExpress DS API, Naver Commerce API, Coupang WING, processor, carrier). Each is a class with the
  same methods as its `Simulated*` counterpart; the gateway does not change.
- Market prices: the Naver 쇼핑 검색 API ended 2026-07-31; price evidence after that date must come from another
  licensed source or a manual capture with URL and date, or purchase verification refuses it.
- Fee tables (Naver 3% + Npay 3.63%; Coupang category fee + VAT + ₩55,000 monthly above ₩1,000,000 sales) belong to the
  pricing/scanner work; the core accrues whatever expected fee the order carries and books the settled actual.
- A freight quote per purchase: the core refuses a zero-shipping cross-border purchase without one.
- Router: live provider adapters, a live payment processor adapter, a live quality scorer, the live model catalog
  with sourced prices (`integrations/model_catalog.toml`, with the provider-terms task), and a customer-facing HTTP
  surface. Until then `arbitrage-ops router` runs only in simulated mode.

## What a simulated result is not

A passing test, the demo, or a green checklist is not a connected account, a live purchase or realized profit. The
`SIMULATED: not real money` label on every simulated figure exists so that nobody reads it otherwise.
