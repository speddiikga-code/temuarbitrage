# GlobalCompute Router

As of 2026-09-28, branch `claude/compute-router-core-xqjk4d` (task 14 in TASKS.md), built on the operating core at
commit 7954072 (task 11, PR #6). Nothing in this document is a connected account, a live request or revenue: every
figure the code produces today is labelled `SIMULATED`, and realized profit toward the KRW 1,000,000 target is ₩0.

## What it is

One request in, the cheapest compliant route out, with a result of equivalent quality:

```
argmin  cost(route)
s.t.    quality(route) ≥ Q        (the customer's minimum, never below the mandate's floor)
        latency(route) ≤ L        (when the customer sets one)
        compliance(route) = true  (provider terms, mandate, region, task type, evidence)
```

The owner's switch on 2026-09-28 changed the business the core runs, not the core. `mandate.toml` now says
`business.domain = "compute_router"`; the ledger, budget governor, action gateway, policy controller, workflows and
audit chain are the same code that ran the ecommerce domain, with a router package on top. The ecommerce modules stay
in the tree and still pass their tests; the mandate decides which domain's fields must be filled.

The router does **not** evade provider pricing, regional restrictions or terms of service. A route whose terms do not
permit the use, whose region is not in the mandate, or whose price has no evidence is rejected with the reason written
into the plan. What it optimizes is legitimate: model choice, semantic caching, context compression, language routing,
decomposition of long inputs, and quality verification before anything is billed.

## Layers and where they live

| Layer | What it does | Module |
|---|---|---|
| 1 Universal Gateway | `RouteRequest` in, `submit()` idempotent on the customer's key, `route()` walks the steps | `ops/router/service.py`, `ops/router/intent.py` |
| 2 Intent Compiler | task type (declared or inferred), languages, capabilities, decomposability, token estimates | `ops/router/intent.py` (`compile_intent`) |
| 3 Semantic Compressor | normalize, drop duplicate paragraphs, keep the passages that overlap the prompt | `ops/router/intent.py` (`compress`) |
| 4 Language Router | which language to process in and answer in; never invents a translation stage | `ops/router/intent.py` (`language_plan`) |
| 5 Global Model Marketplace | catalog of provider/model/region rows with prices, evidence, terms, learned quality | `ops/router/catalog.py`, `ops/router/catalog.simulated.toml` |
| 6 Cost-Aware Router | compliance gate, cost in KRW, objective (economy, balanced, maximum), escalation ladder | `ops/router/planner.py` |
| 7 Semantic Cache | exact and near-duplicate hits per customer scope, task type and language; TTL 7 days | `ops/router/cache.py` |
| 8 Execution Orchestrator | one `inference_call` action per attempt through the gateway; decomposition; escalation | `ops/router/service.py` (`_execute`, `_call`, `_preprocess`) |
| 9 Quality Judge | structural checks, then a scorer; unjudged output is never delivered | `ops/router/judge.py`, `ops/router/adapters.py` (`SimulatedJudge`) |
| 10 Billing and Optimization | charges, fees, savings, dispute windows, catalog quality learning, reports | `ops/router/billing.py`, `ops/router/reporting.py`, `ops/router/jobs.py` |

## How the core's concepts map

| Core concept (ecommerce) | Router meaning |
|---|---|
| supplier | model provider |
| supplier purchase | `inference_call` action, confirmed by the provider's `provider_usage` record |
| prepaid supplier balance (1300) | prepaid provider credits (1400), bought through a `provider_prepayment` action |
| customer order and sale | routed request; the charge is the sale, provider cost is cost of sales (5020) |
| customs and eligibility gate | provider terms, permitted regions, permitted task types, price evidence |
| return window | dispute window on a settled request (`reserves.refund_reserve_days`) |
| inventory value limit | `router.max_provider_prepaid_krw` and `router.max_provider_exposure_krw` |

## Request lifecycle

`received → compiled → planned → executing → judged → billed → delivered`, each step persisted on `routed_requests`
so a durable workflow can resume it. Failure ends in `status = failed` with `last_error`; a provider call with no
answer ends in `result_unknown` on the action and `ReconciliationRequired` for the request: it is never retried
blind, the reconciliation job asks the provider what it recorded and only then does the request continue.

Every provider call is an action through the gateway: `proposed → verified → reserved → completed`, where
`verified` re-checks the mandate, catalog and money limits, `reserved` holds the cap cost from the budget governor
(platform-funded requests only) and `completed` needs the provider's usage record. The cost booked is the provider's
count, never the estimate; a usage record above the reserved cap goes to `result_unknown` and, on reconciliation,
pauses purchasing automatically.

## Compliance gate (before any price is compared)

A catalog row may serve a request only if it is available, its terms permit the use, its provider and region are in
the mandate, the task type is permitted by the mandate and served by the model, the context fits the window, and
there is quality evidence for that task type. Unknown quality never meets a threshold. A route that passes but
misses the customer's quality, latency or cost cap, or the mandate's per-request cap, is rejected with that reason.

## Billing modes

**Platform credits.** The customer prepays through a payment processor. A top-up is spendable only after the
processor settles it (customer balance 2600 is credited from settled cash, never from an authorization). A request
is charged provider cost plus `platform_fee_rate × cost`, then VAT; the charge is taken from the balance and booked as
gross sales and tax payable; the provider cost is booked to 5020 against prepaid credits (1400) or supplier payables
(2000). The request is `settled` at once and `closed` when the dispute window ends. A refund goes back to the balance.

**Own keys.** The customer's provider credentials are referenced by an environment-variable style name, never stored
as a value. The platform reserves and spends nothing: no inference cost is booked. The fee is `savings_share_rate ×
verified savings` when the baseline and the delivered route both carry verified prices, else `platform_fee_rate ×
metered cost`, invoiced through the processor; the request is `invoiced` on capture and `settled` on settlement.

**Realized profit** for routed requests follows the core's definition: only requests whose money is settled and whose
dispute window has ended count, net of provider cost, processor fees, FX and the refund reserve. Failed attempts are
a realized loss the platform carries. Simulated figures never count toward the goal.

## Money limits and disclosures (mandate `[router]`)

`providers`, `permitted_regions`, `permitted_task_types`, `billing_modes`, `max_request_cost_krw`,
`max_daily_inference_spend_krw`, `max_provider_prepaid_krw`, `max_provider_exposure_krw`, `platform_fee_rate`,
`savings_share_rate`, `min_quality_score`, `terms_url`, `privacy_policy_url`, `disclosed_providers`. All are
`"pending"` in `mandate.toml`, so the live router refuses everything; `mandate.router.simulated.toml` carries test
values.

## Provider rules the router enforces

The provider-terms work (task 13, `docs/provider_terms.md` section 3 on branch `claude/provider-terms-0oikmd`, draft
PR #7) read the terms of 21 AI providers and 8 payment processors and wrote twelve rules. Each is enforced in code or
recorded per request, and each has a test in `tests/ops/router/test_provider_rules.py` or `test_route_flow.py`:

| Rule (provider_terms.md §3) | Where it is enforced |
|---|---|
| 1 Keys stay server-side | `customers.provider_credentials` holds environment-variable names only; a key value is refused at registration. End users never see a provider name unless the customer's product shows it: the delivered result carries labels, not the route. |
| 2 The platform's credit is its own instrument | Top-ups are the platform's liability (2600), never provider credits (1400); a balance is charged only for this platform's requests, never moved to another customer, and a refund returns to the same balance or reverses the original processor payment. |
| 3 Users bound to each provider's policy and supported regions | `register_customer` needs `terms_accepted_at`; the customer's `region` is their country and the planner rejects every catalog row whose `customer_countries` does not list it. |
| 4 AI disclosure and output labelling; high-risk domains | `register_customer` needs `ai_disclosure_confirmed`; every delivered request carries `labels.ai_generated = true`; the intent compiler flags legal, medical, finance, employment, housing, insurance and credit prompts and the result carries `human_review_required = true`. |
| 5 No bare pass-through | A request cannot name a model, provider or endpoint (`metadata` is ignored by the planner); every request is compiled, planned, judged and billed. |
| 6 One account per provider, no splitting | The mandate lists each provider once; prepaid credits and exposure are tracked per provider id, never per account. |
| 7 Semantic cache per tenant | `cache_scope` is always `customer`; a hit is a repeat inside the same tenant only. |
| 8 Residency is a customer choice, cheapest sanctioned by default | `RouteRequest.residency` restricts the plan to that region and the plan says so; without it the plan notes "cheapest sanctioned route; residency is a customer-selected option, never silent". |
| 9 Foreign providers pre-disclosed | `router.disclosed_providers` in the mandate: a provider not listed in the privacy policy is rejected at planning and again at call verification. |
| 10 PRC-hosted endpoints gated | Catalog rows carry `data_residency`; a `cn` row needs the tenant's `prc_opt_in` and is excluded whenever the personal-information classifier (emails, phone numbers, 주민등록번호, card numbers, 개인통관고유부호) finds anything. |
| 11 Free tiers never carry customer traffic | Catalog rows carry `free_tier`; a free row is rejected at planning and at call verification. |
| 12 Per-request record | `route_executions.list_price` stores the list price, currency, multiplier, region and hosting at call time with tokens, cost, FX and the verdict; the judge's own cost and source are in the request's `judge` record; `baseline_cost_krw` and `savings_verified` measure against what the customer could do alone. |

A live catalog row is accepted only when the integration registry clears its provider: `service` is an AI inference
service, `customer_app_allowed = "explicit"` (the first-pilot rule; `not_prohibited` only after counsel), and the
verdict is not `no_go` or `unknown`. That reads the registry's extra fields through `ops/router/providers.py` without
writing any entry; the registry stays with tasks 10 and 13. A live call is then refused until the registry calls the
provider production-ready (status live, connected, verified operation), which no provider is today.

## Prices and evidence

Every catalog row carries `evidence = {source, url, date, verified}`, the countries whose end users the provider
supports, where the endpoint is hosted and whether it is a free tier. Simulated rows are never verified and the
planner says so in the plan. The live catalog is read from `integrations/model_catalog.toml` (or `OPS_MODEL_CATALOG`)
and does not exist yet; its prices should come from the `pricing_url` of each registry entry (task 13 read list
prices on 2026-09-28 in `docs/provider_terms.md` section 5). Loading it needs `integrations/registry.toml` (or
`OPS_REGISTRY`) so every provider is checked against the registry. Until both exist `arbitrage-ops router catalog`
lists nothing in live mode.

Token counts are estimates from character counts; the provider's usage record is the true count and the only one
that is booked. FX in simulated mode is a static placeholder (`DEMO_FX_ORIGIN` in `ops/cli.py`); in live mode it
comes from `OPS_FX_KRW_PER_USD` with its origin recorded on every plan.

## Try it (nothing is spent)

```bash
arbitrage-ops --mode simulated migrate
arbitrage-ops --mode simulated router demo      # three requests: credits, cache hit, own keys with escalation
arbitrage-ops --mode simulated router requests
arbitrage-ops --mode simulated router catalog
arbitrage-ops --mode simulated status --json    # "router" section, counts_toward_goal: false
arbitrage-ops status                             # live: pending mandate, ₩0
```

Tests: `tests/ops/router/` (intent, catalog and planner, cache, route flow, CLI), on SQLite by default and on
PostgreSQL with `OPSCORE_TEST_DATABASE_URL`.

## Path to the first paid routed request

What exists: the core (task 11) and this router, simulated end to end. What is new on this branch: the router
package, the `inference_call` and `provider_prepayment` actions, accounts 1400/2600/5020, domain-aware mandate,
router tables, CLI and dashboard section. No customer exists. No provider account, key or funding exists in the
repository, and none is claimed to exist anywhere else.

Only the owner can do these, in this order (details and sources in `docs/provider_terms.md` section 1b on the
provider-terms branch):

1. **Business registration** (사업자등록 as 일반과세자), 통신판매업 신고 (needs the payment processor's 구매안전서비스
   이용확인증), VAT treatment for exported services.
2. **Payment processor account** in the business's name: Toss Payments (KRW), PayPal Business Korea, Paddle or Polar;
   Stripe has no Korean entity. Prepaid top-ups of about ₩50,000 / $50 and up, because processor fixed fees make
   smaller charges uneconomic.
3. **Provider accounts with prepaid credits** for each provider the mandate will name, one account per provider, keys
   held outside git. First pilot: providers whose terms explicitly allow serving your own end users (`anthropic_api`,
   `openai_api`, `google_gemini_api`, `google_vertex_ai`, `aws_bedrock`, `groq_cloud`, `cerebras_inference`,
   `mistral_la_plateforme`, `moonshot_kimi`, `deepseek_api` for non-personal data; `azure_openai_foundry` conditional).
4. **Terms and privacy policy** published: platform terms that pass down each provider's usage policy and supported
   regions, and a privacy policy that names every foreign provider (개인정보 보호법 제28조의8); then the mandate's
   `terms_url`, `privacy_policy_url` and `disclosed_providers`.
5. **Mandate values**: every `[router]` field, the limits, reserves and `payment_processors` in `mandate.toml`.
6. **Hosting**: a PostgreSQL host and a worker (the `docker-compose.yml` stack from task 11, never run here).
7. **A customer** who accepts the terms and a price, confirms AI disclosure in their product, and makes a first top-up
   or brings their own provider key.

What code still needs before the first live request: live provider adapters (`complete`, `lookup`, `usage_report`
against real APIs), a live payment processor adapter, a live quality scorer, the live catalog with sourced prices,
and an HTTP surface for customers. Each is a class with the same methods as its `Simulated*` counterpart; the gateway,
ledger and policy do not change.

## What a simulated result is not

The demo, a green test run or a dashboard section is not a connected account, a live request or realized profit. The
`SIMULATED: not real money` label on every simulated figure exists so that nobody reads it otherwise.
