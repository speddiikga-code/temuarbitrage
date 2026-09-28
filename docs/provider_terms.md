# AI provider terms, regions, prices and Korean rules for the GlobalCompute Router

**Date of verification: 2026-09-28.** Owner: Claude, thread "Provider terms and routing economics",
branch `claude/provider-terms-0oikmd`, task 13 in [TASKS.md](../TASKS.md). The machine-readable companion is
[`integrations/registry.toml`](../integrations/registry.toml): 29 new entries (18 AI inference providers, 3
gateways, 8 payment processors), every one `connected = false` and `status = "not_connected"`. The savings
model is [`tools/routing_economics.py`](../tools/routing_economics.py).

**Nothing in this document is live, connected, contracted or authorised to spend.** No provider account,
payment contract or Korean registration exists for this business yet; realised profit is ₩0. The document
records what each provider's own terms and Korean law allow so that the build thread can gate routes on it
and the owner can see exactly which accounts, registrations and decisions are still missing. It is
documentary research, not legal advice; the decisive sentences are quoted so counsel can assess them.

Evidence tags:

| Tag | Meaning |
|---|---|
| **VERIFIED** | read on the provider's own page or a Korean government page on 2026-09-28; link and the page's own date given |
| **VERIFIED-ARCHIVE** | read from a web.archive.org snapshot of the provider's own page because the live page returned HTTP 403 from this environment; snapshot date given |
| **REPORTED** | press, law firm, consultancy, or a commercial statute mirror (lbox, bigcase, casenote, ulex reproduce 국가법령정보센터 text but are private services) |
| **INFERRED** | our reasoning from verified facts |
| **UNKNOWN** | could not be reached or found; treated as *not approved*, never as approval |

Unreachable from this environment on 2026-09-28: every `openai.com` and `help.openai.com` page (403; archive
snapshots used, `developers.openai.com` live), `law.go.kr`, `fsc.go.kr`, Microsoft's Product Terms site
(JavaScript shell), Google Partner Advantage, `groq.com/pricing` (redirects), the Azure and Bedrock public
price pages (placeholders; official price APIs used instead), Naver CLOVA Studio price cells (client-side).
Section 10 lists them all.

---

## 1. The shortest compliant path to one paid routed request

### 1a. The verdict that everything else hangs on

Every provider whose terms were read draws the same line:

- **Allowed:** building a product with its own function and serving *the platform's own end users* through
  provider keys the platform holds server-side. Anthropic A.1 ("power products and services Customer makes
  available to its own customers and end users"), OpenAI 2.2 ("make Customer Applications available to End
  Users"), Google Cloud 1.1 ("Customer Application that has material value independent of the Services"),
  AWS 2.5 (End Users under your account), Azure "Customer Solution", Groq 3.1, Cerebras, Mistral ("Customer
  Offering"), Kimi ("Customer Applications"), DeepSeek ("providing services to both internal and external end
  users"). All VERIFIED except Azure (REPORTED, see 2a).
- **Prohibited everywhere:** reselling the service, the account, API keys or the provider's own credits.
  Anthropic D.4 ("resell the Services except as expressly approved"), OpenAI 3.1 and 3.3(g), Google APIs ToS
  ("Sublicense an API for use by a third party ... an API Client that functions substantially the same as
  the APIs"), Google Cloud 3.3(c), AWS 6.4(c), Microsoft Online Subscription Agreement, Groq 3.2 and 6.3(c),
  Together 4(d) ("offer the Services on a standalone basis"), OpenRouter 7 ("reselling API access to
  Models"). Both Anthropic and OpenAI credit terms forbid selling or transferring their credits.

So the product the owner described ("online LLM trading credits") is compliant only in this shape
(INFERRED from the quotes): the platform sells **its own credit instrument**, redeemable only for **its own
service** (intent compiler, compression, cache, routing, judge, cost accounting), through **its own keys**,
to **its own registered users** who accept the platform's terms, which pass down every provider's usage
policy and supported-regions rule. Anything marketed as "Claude credits", "GPT credits" or "cheap API keys"
is the prohibited shape.

### 1b. Gates, in order

| # | Gate | Who | Status on 2026-09-28 | Evidence |
|---|---|---|---|---|
| 1 | **사업자등록 as 일반과세자** (a 간이과세자 cannot issue 세금계산서 or claim 영세율, see 6c) | owner | not verified to exist; the mandate questions of 2026-09-27 are unanswered | INFERRED from 6c |
| 2 | **Provider accounts in the business's name with prepaid credits**: Anthropic Console (prepaid usage credits, non-refundable, expire after one year), OpenAI (minimum $5, expire after one year), a Google Cloud project *with billing enabled* (free-tier traffic is used for training and human review), Groq or another open-weight host. Enter the 사업자등록번호 as tax ID. | owner pays; no spending mandate exists | none exist | VERIFIED [Anthropic credit terms](https://www.anthropic.com/legal/credit-terms) (2024-03-04); VERIFIED-ARCHIVE [OpenAI service credit terms](https://openai.com/policies/service-credit-terms/) (2026-01-01, snapshot 2026-09-03); VERIFIED [Gemini terms](https://ai.google.dev/gemini-api/terms) (2026-03-23) |
| 3 | **Platform terms and privacy policy**: pass-down of provider usage policies and supported regions; AI disclosure at session start (Anthropic AUP; AI Basic Act Art. 31(1)); output labelling (Art. 31(2)); human review for high-risk domains (Anthropic AUP; OpenAI usage policies); 18+ and no under-18 audiences (Google); a **pre-disclosed list of every foreign provider** with the five items of 개인정보 보호법 제28조의8 ②; footer with 상호, 대표자, 주소, 전화, 이메일, 사업자등록번호, 통신판매업신고번호, 호스팅제공자 (전자상거래법 제10조, 제13조); display that consumed credits cannot be withdrawn (제17조 ⑥). | Claude drafts, owner approves | not written | sections 3, 6 |
| 4 | **Payment collection**: Korean customers through Toss Payments (Toss review 1–2 days, card-company review up to 14 days, 3.4% + VAT, 가입비 220,000원); foreign customers through PayPal Business Korea (same day, 4.40% + $0.30 + up to 3% FX) or a merchant of record that accepts Korean sellers (Paddle, Polar, Lemon Squeezy; 1–2 weeks). Stripe does not onboard Korean entities. | owner signs | none exist | section 7 |
| 5 | **통신판매업 신고** on 정부24 (등록면허세 40,500원 in Seoul; the 구매안전서비스 이용확인증 that 정부24 asks for on 선지급식 sales comes from the PG after gate 4). Legally exempt in year one (no prior-year transactions), but the card-company review expects the number in the footer, so file at launch. | owner | not filed | 6a |
| 6 | **부가통신사업**: deemed filed while 자본금 ≤ 1억원 (개인사업자 or small 법인); file within one month once above. | owner | deemed filed if gate 1 is an 개인사업자 | 6b |
| 7 | **First paid routed request**: a registered customer buys platform credits (gate 4), sends a request, the router serves it on a platform key (gate 2), the platform records provider cost, fee and FX. Realised profit = settled cash net of provider cost, PG fee, FX and refund reserve. | build thread | ₩0 | standing rule |

Gates 1, 2, 4, 5 and 6 are owner-only. Gates 3 and 7 are build work that can proceed now against simulated
accounts, as long as nothing simulated is reported as connected or live.

### 1c. What blocks, what does not

- **Blocks:** no 사업자등록 confirmed; no provider account or credit; no payment contract; no 통신판매업 number
  for the footer. Each is days, not weeks, once the owner acts (Toss up to about two weeks for card review).
- **Does not block:** provider permission. No provider requires a partner or reseller programme to serve the
  platform's own end users; the reseller programmes (Google Partner Advantage, AWS Solution Provider
  Program, Microsoft CSP) are needed only for raw resale, which this product must not do.
- **Needs written confirmation before scale, not before the first request:** Together (benchmarking clause
  4(c)), Fireworks and DeepInfra (self-serve terms do not grant end-user distribution), Paddle ("store credit"
  in its prohibited list), Azure (the governing Product Terms could not be read on Microsoft's own site).
- **Not usable as an upstream:** OpenRouter (its terms forbid reselling API access), Stripe (no Korean
  entities), the Gemini free tier (trains on inputs), Naver CLOVA Studio until its KRW prices and data terms
  are read.

---

## 2. Provider matrix

### 2a. Frontier and hyperscaler providers

| Provider | Verdict | Own end users | Resale line | Korea | Residency and region price | Source (page date) |
|---|---|---|---|---|---|---|
| **Anthropic Claude API** | **GO** | A.1: "permission to use the Services, including to power products and services Customer makes available to its own customers and end users" | D.4: no "resell the Services except as expressly approved by Anthropic"; credits: "Customer may not transfer or sell Credits" | South Korea listed for commercial API access; AUP forbids facilitating access "in violation of our Supported Regions Policy" | `inference_geo` global (standard) or us (1.1x on all token categories, Claude 4.6+); workspace geo us only; no Asia option | VERIFIED [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) (2025-06-17); [Usage Policy](https://www.anthropic.com/legal/aup) (2025-09-15); [Supported regions](https://www.anthropic.com/supported-countries); [Data residency](https://platform.claude.com/docs/en/manage-claude/data-residency); [Credit terms](https://www.anthropic.com/legal/credit-terms) (2024-03-04) |
| **OpenAI API** | **GO** | 2.2: "the right to use OpenAI's API to integrate the Services into Customer Applications and to make Customer Applications available to End Users" | 3.1: "may not resell or lease access to its Account"; 3.3(g): no "buy, sell, or transfer API keys"; 3.3(i): no circumventing Usage Limits; credits: "We prohibit and do not recognize any purported transfers, sales, gifts, or trades of Service Credits" | South Korea listed; 16.12: "Customer and End Users may not access or offer access to the Services outside of the Supported Countries and Territories" | Korea project region `kr.api.openai.com` is storage-only (processing outside Korea), needs sales eligibility plus abuse-monitoring approval and a Modified Retention amendment; data-residency endpoints +10% for models released on or after 2026-03-05 | VERIFIED-ARCHIVE [Services Agreement](https://openai.com/policies/services-agreement/) (2026-01-01, snapshot 2026-09-26); [Usage policies](https://openai.com/policies/usage-policies/) (2025-10-29, snapshot 2026-09-27); VERIFIED [Supported countries](https://developers.openai.com/api/docs/supported-countries); [Data controls](https://developers.openai.com/api/docs/guides/your-data) |
| **Google Gemini API** (AI Studio) | **GO**, paid tier only | "make API Clients available to users"; "for developers building with Google AI models for professional or business purposes, not for consumer use"; 18+ and no under-18 audiences | Google APIs ToS: "Sublicense an API for use by a third party. Consequently, you will not create an API Client that functions substantially the same as the APIs and offer it for use by third parties." | South Korea on the available-regions list | No region choice; single global price list. Unpaid quota: "Used to improve our products: Yes" and "human reviewers may read"; the EEA/UK/CH exception does not cover Korea | VERIFIED [Gemini API terms](https://ai.google.dev/gemini-api/terms) (2026-03-23); [Google APIs ToS](https://developers.google.com/terms) (2021-11-09); [Available regions](https://ai.google.dev/gemini-api/docs/available-regions) (2026-04-28); [Pricing](https://ai.google.dev/gemini-api/docs/pricing) (2026-09-24) |
| **Google Vertex AI** (Gemini, Claude) | **GO** | 1.1: "integrate the GCP Services ... into any Customer Application that has material value independent of the Services"; End Users "may include ... other authorized third parties" | 3.3(c): no "sell, resell, sublicense, transfer, or distribute any or all of the Services"; 3.3(d)(iii): no use "intended to avoid incurring Fees (including creating multiple ... Accounts, or Projects ...)"; resale only under a Reseller Agreement (Partner Advantage) | Seoul `asia-northeast3` is a regional endpoint for Gemini; the partner-model (Claude) residency table has no Seoul column | Global endpoint "doesn't support data residency requirements"; non-global endpoints +10% for Gemini 3+ from 2026-07-01 and for Claude Sonnet 4.5 and later; Google: "we recommend routing your primary traffic to the global endpoint" | VERIFIED [Cloud ToS](https://cloud.google.com/terms) (2026-09-02); [Service Specific Terms](https://cloud.google.com/terms/service-terms) (2026-09-24); [Locations](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations) (2026-09-25); [Data residency](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency) (2026-09-25); [Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| **Amazon Bedrock** | **GO** | 2.5: End Users are anyone who "accesses or uses the Services under your account"; 50.4: platform must give End Users "legally adequate privacy notices" | 6.4(c): no "resell the Services or AWS Content"; 6.4(b): no use "intended to avoid incurring fees"; 2.4: keys "for your internal use only"; resale only through the Solution Provider Program via a Korean distributor | Contracting party Amazon Web Services Korea LLC; Seoul `ap-northeast-2` offers Claude 4.5, 4.6 and 5 family through the **Global** cross-region profile only, Amazon Nova through the APAC profile | Global profile "may be processed in other supported AWS commercial Regions"; "approximately 10% savings" versus geographic profiles; price set by the *source* region; Bedrock not in the 50.3 training list, 30-day abuse store only | VERIFIED [Customer Agreement](https://aws.amazon.com/agreement/) (2026-08-14); [Service Terms](https://aws.amazon.com/service-terms/) (2026-09-15); [Region availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html); [Cross-region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html); [Pricing feed](https://aws.amazon.com/bedrock/pricing/) |
| **Azure OpenAI / Foundry** | **CONDITIONAL** | Product Terms "Azure Customer Solution": "Customer may permit third parties to access and use the Microsoft Azure Services solely in connection with the use of that Customer Solution" (REPORTED from a 2025-03-12 mirror PDF; the official site is a JavaScript shell) | Online Subscription Agreement: "You may not rent, lease, lend, resell, transfer, or host the Product, or any portion thereof, to or for third parties except as expressly permitted"; "You may not resell or redistribute the Microsoft Azure Services"; resale only as a CSP indirect reseller | Korea Central: Global Standard for GPT-5.x, 4.1, 4o, o-series; APAC Data Zone for gpt-5.2, 5.3-codex, 5.4, 5.4-mini, 5.6-sol only; no regional Standard GPT | Global Standard is region-invariant and "has the lowest price"; Data Zone +10% in the US and EU but +20% in Korea Central; no training on prompts; abuse-monitoring sample stored in the resource's geography | VERIFIED [MOSA](https://azure.microsoft.com/en-us/support/legal/subscription-agreement); [Deployment types](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/deployment-types) (2026-08-06); [Region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability) (2026-09-03); [Data privacy](https://learn.microsoft.com/en-us/legal/cognitive-services/openai/data-privacy) (2026-05-18); [Retail Prices API](https://prices.azure.com/api/retail/prices); REPORTED [Product Terms mirror](https://www.aucotec.com/fileadmin/user_upload/aucotec/Microsoft_EULAs/EN/Visio/Microsoft_365_Licensing_Terms__12.03.2025__-_EN.pdf) |

### 2b. Open-weight hosts and gateways

| Provider | Verdict | Own end users | Resale line | Region | Source (page date) |
|---|---|---|---|---|---|
| **Groq** | **GO** | 3.1: right "to integrate the Cloud Services and AI Model Services into your Customer Application and to make the Cloud Services and AI Model Services available to End Users" | 3.2: "Customer may not resell or lease access to its Account"; 6.3(c): no "sell, resell, sublicense, transfer, or distribute any of the Cloud Services except as expressly approved by Groq" | US, Canada, Saudi Arabia, Finland; EU endpoint by sales enablement; no Korea | VERIFIED [Services Agreement](https://console.groq.com/docs/legal/services-agreement) (2026-06-22); [Models and prices](https://console.groq.com/docs/models) |
| **Cerebras** | **GO** | licence to "distribute or allow access to your integration of the APIs within your applications to end users of such applications" | no "sell ... sublicense, resell, distribute ... any part of the Service"; no "Buy, sell or transfer API keys without our prior written consent" | not stated | VERIFIED [Terms of Use](https://www.cerebras.ai/terms-of-service) (2024-08-27); [Pricing](https://www.cerebras.ai/pricing) |
| **Mistral La Plateforme** | **GO** | "Customer Offering" = "Customer's own products and services that it makes available to third parties which involve use of the Mistral AI Products"; licence "non-sublicensable (except to its End Users)" | Additional Product Terms 2: "End User Accounts may not be shared, sold, licensed, or otherwise made available outside of Customer's entity" | default endpoint no location commitment; EU and US regional inference at 1.1x | VERIFIED [Commercial Terms](https://legal.mistral.ai/terms/commercial-terms-of-service) (2026-09-25); [Pricing](https://mistral.ai/pricing/api) |
| **Together AI** | CONDITIONAL | no end-user clause either way (not verified) | 4(d): no "transfer, distribute, resell, lease, license, or assign the Services or otherwise offer the Services on a standalone basis"; 4(c): no "competitive analysis or benchmarking" (a router that continuously benchmarks Together must read this with counsel) | serverless region not selectable; EU dedicated only on Scale or Enterprise | VERIFIED [Terms of Service](https://www.together.ai/terms-of-service) (2026-05-19); [Pricing](https://www.together.ai/pricing) |
| **Fireworks AI** | CONDITIONAL | 2.1: use "solely for your personal use or internal business purposes"; no end-user grant found | 2.2(d): no "buy, sell or transfer API keys"; 2.2(e): no "sublicense, resell, distribute" | GLOBAL, US, EUROPE, APAC multi-regions and AP_TOKYO_1; US-only serverless 1.5x from 2026-09-01; no Korea | VERIFIED [Terms of Service](https://fireworks.ai/terms-of-service) (2026-07-10); [Pricing](https://docs.fireworks.ai/serverless/pricing) |
| **DeepInfra** | CONDITIONAL | no end-user grant found | 11(a)(viii): no "resell, sublicense, rent, distribute, or otherwise make the Services available to any third party except as expressly permitted under this Agreement or the applicable Service Order" | processed "in the United States"; no region selection | VERIFIED [Terms of Service](https://deepinfra.com/terms) (2026-08-17); [Pricing](https://deepinfra.com/pricing) |
| **OpenRouter** | **NO-GO as upstream**; keep as price feed | n/a | 7: no access "for purposes of reselling API access to Models or otherwise developing a competing service" | forwards requests with the originating country | VERIFIED [Terms](https://openrouter.ai/terms) (2026-08-31); [Models API](https://openrouter.ai/api/v1/models) (458 models) |
| **Vercel AI Gateway** | CONDITIONAL (infrastructure) | BYOK passes the platform's own keys with "no markup or fee"; credits mode bills Anthropic, OpenAI and Google at list price; AI Product Terms 2 licence "without the right to sublicense" | whether a paid third-party router may run on Vercel credits is not verified | not stated | VERIFIED [Pricing](https://vercel.com/docs/ai-gateway/pricing) (2026-09-08); [AI Product Terms](https://vercel.com/legal/ai-product-terms) (2026-03-31) |
| **Cloudflare AI Gateway** | CONDITIONAL (infrastructure) | core features free; Unified Billing passes provider prices "with no markup" plus "A 5% fee ... applied to all credits purchased" | whether a paid third-party router may run on Unified Billing is not verified | not stated | VERIFIED [Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/) (2026-09-23) |

### 2c. Korean and Chinese-origin providers

| Provider | Verdict | Own end users | Data location | Why the verdict | Source (page date) |
|---|---|---|---|---|---|
| **Upstage Solar** (Seoul) | **GO** | not addressed either way; 9(3) forbids transferring the right of use; 23(1) limits use to the service's purpose | privacy policy discloses AWS (US), Azure (US) and OpenAI (US) as sub-processors; results stored 30 days | Korean company, USD prices exclusive of 10% VAT, no training on paid inputs (22(5)); "Korean residency" cannot be promised because of the US sub-processors | VERIFIED [Terms](https://www.upstage.ai/terms-of-service) (2026-09-21); [Privacy](https://www.upstage.ai/privacy-policy/updated-sep-21-2026) (2026-09-15); [Pricing](https://www.upstage.ai/pricing) |
| **Naver CLOVA Studio** | **UNKNOWN** | not located | 리전 한국 only | KRW per-token prices render only client-side; no data-use or resale clause located; cannot be priced or gated yet | VERIFIED [Product page](https://www.ncloud.com/product/aiService/clovaStudio); [Spec](https://guide.ncloud-docs.com/docs/clovastudio-spec) (2026-09-17) |
| **DeepSeek API** | CONDITIONAL (no personal information) | "providing services to both internal and external end users" allowed; resale not addressed | "we directly collect, process and store your Personal Data in People's Republic of China"; PRC law, Hangzhou courts | The PIPC found in April 2025 that DeepSeek transferred user prompts to Volcano Engine without a legal basis and ordered it stopped; any prompt with a Korean data subject's personal information is a 국외 이전 under 제28조의8. Usable for non-personal workloads after privacy-policy disclosure and per-tenant opt-in; otherwise run DeepSeek weights on a US or Singapore host. Off-peak half price 16:30–00:30 KST on weekdays is a provider-published rate, so scheduling batch work there is sanctioned | VERIFIED [Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) (2026-04-29); [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) (2026-02-10); [Pricing](https://api-docs.deepseek.com/quick_start/pricing); [PIPC decision](https://www.pipc.go.kr/eng/user/ltn/new/noticeDetail.do?bbsId=BBSMSTR_000000000001&nttId=2819) (2025-04-24) |
| **Alibaba Model Studio** (international) | CONDITIONAL | not located | Singapore, US, Japan, Germany regions; "Request data is stored in that region"; never used for training | Qwen at list price outside China; the international terms were not read | VERIFIED [Pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing) (2026-09-28); [Regions](https://www.alibabacloud.com/help/en/model-studio/regions) |
| **Moonshot Kimi** | CONDITIONAL | "offer those Customer Applications to End Users" allowed; no "selling, or providing sub-licensing or re-licensing of the Services" | servers in Singapore; Singapore law | Self-serve terms: "We may use Content to provide, maintain, develop, support, and improve the Services"; enterprise ZDR on request. 제28조의8 ⑤ bars transfer contracts with terms that violate PIPA, so an enterprise or ZDR arrangement comes first | VERIFIED [Terms](https://platform.kimi.ai/docs/agreement/modeluse) (2026-07-30); [Privacy](https://platform.kimi.ai/docs/agreement/userprivacy.md) (2025-04-30); [Pricing](https://platform.kimi.ai/docs/pricing/chat) |
| **Z.ai GLM** | CONDITIONAL | developers must "establish agreements with ... End Users"; no explicit grant sentence | Singapore entity; API content "not saved" | no training on API content unless agreed; the same GLM-5.3 is $1.40 / $4.40 at Z.ai, Together, Fireworks and Mistral, so Z.ai is not a price advantage | VERIFIED [Terms](https://docs.z.ai/legal-agreement/terms-of-use) (2026-04-14); [Pricing](https://docs.z.ai/guides/overview/pricing) |

---

## 3. Rules the router must enforce (INFERRED from section 2)

1. **Keys stay server-side.** End users never receive a provider key, never bring a key the platform bills,
   and never see which provider answered unless the platform chooses to say (OpenAI 3.3(g), AWS 2.4,
   Cerebras, Fireworks 2.2(d); both Anthropic and OpenAI help centres: route through your own backend).
2. **The platform's credit is its own instrument.** It is never described as, backed by, or convertible into a
   provider's credits (Anthropic and OpenAI credit terms). It is non-transferable between users and redeems
   only the platform's service, which is also what keeps it outside 전자금융거래법 (section 6d).
3. **Every registered user accepts terms that pass down** each provider's usage policy, the supported-regions
   rules (OpenAI 16.12; Anthropic AUP), Google's B2B and 18+ rules, and the no-competing-model clauses.
   Users are screened by country; no request is accepted from a location a provider does not support.
4. **AI disclosure at session start and output labelling** are mandatory: Anthropic AUP for consumer-facing
   chatbots and agents; AI Basic Act Art. 31(1) and (2) (fine up to ₩30M for missing notice; a 1-year 계도기간
   from 2026-01-22 with no SME exemption). High-risk domains (legal, medical, finance, employment, housing,
   insurance, credit) need a qualified human in the loop and a disclosure (Anthropic AUP; OpenAI usage
   policies on "automation of high-stakes decisions in sensitive areas without human review").
5. **No bare pass-through endpoint.** A generic "/v1/chat/completions that just forwards" is "an API Client
   that functions substantially the same as the APIs" (Google APIs ToS) and "the Services on a standalone
   basis" (Together). The router's own function must be visible in the product: intent, compression,
   cache, judge, accounting.
6. **No fee avoidance.** One account per provider, no account or project splitting to stay under limits
   (Google Cloud 3.3(d)(iii), AWS 6.4(b), OpenAI 3.3(i)).
7. **Semantic cache is per tenant.** Answers are never served across customers; a hit is a repeat inside the
   same tenant only (vCache and MeanCache findings in section 8; PIPA).
8. **Region routing is a customer-selected constraint, cheapest sanctioned option by default.** Global or
   dynamic endpoints are the provider-recommended and cheapest choice everywhere (section 4); residency
   costs 10% to 20% more and is offered as an explicit option, never silently.
9. **Foreign providers are pre-disclosed.** The privacy policy lists every candidate foreign provider with the
   five items of 제28조의8 ② (items, country and method, recipient name and contact, purpose and retention,
   how to refuse). A new provider is added to the policy before it is added to the router.
10. **PRC-hosted endpoints are gated on a personal-information classifier and a tenant opt-in**; otherwise the
    same weights are served from a US or Singapore host.
11. **Free tiers never carry customer traffic** (Gemini unpaid quota, Upstage free tier, Mistral Experiment
    tier are used to improve models by default).
12. **The judge and cost ledger record, per request:** provider, model, endpoint or region, tokens by
    category, list price, batch or cache multipliers, judge cost, and the customer's baseline. A "verified
    saving" is measured against what the customer could do alone (section 8b).

---

## 4. Regions, residency, and whether price differences are legitimate to route on

### 4a. What each provider offers from Korea

| Provider | Korea-resident inference? | Cheapest sanctioned endpoint | Price of the residency option |
|---|---|---|---|
| Anthropic API | No (global or us only) | `inference_geo: "global"`, standard price | us: 1.1x on input, output, cache write and cache read (Claude 4.6+) |
| OpenAI API | No (kr project region is storage-only; processing outside Korea) | global project, standard price | data-residency endpoints +10% for models released on or after 2026-03-05; needs sales approval and MAM or ZDR |
| Gemini API | No region control | the single global price | none exists |
| Vertex AI | Gemini: Seoul `asia-northeast3` (ML processing in South Korea column); Claude: not verified (no Seoul column; newer Claude models on global, us or eu only) | global endpoint | non-global +10% (Gemini 3+ from 2026-07-01; Claude Sonnet 4.5 and later) |
| Bedrock | Claude: no (Seoul offers the Global profile only); Nova: APAC geography | Global cross-region profile called from Seoul, same price as from N. Virginia or Tokyo | geo or in-region profiles +10% (no Seoul row for Claude); Nova in Seoul about +17% versus N. Virginia |
| Azure | Data at rest stays in the geography; processing: Global anywhere, APAC Data Zone within APAC (5 GPT models), no regional Standard GPT in Korea Central | Global Standard, identical price in Korea Central and East US 2 | APAC Data Zone +20% in Korea Central (US and EU Data Zones +10%) |
| Mistral | No (EU or US regional at 1.1x) | default endpoint | +10% |
| Fireworks | No (GLOBAL, US, EUROPE, APAC, AP_TOKYO_1) | GLOBAL | US-only serverless 1.5x from 2026-09-01 |
| Naver CLOVA Studio | Yes, Korea only | unknown (prices unread) | n/a |
| Upstage | Korean company, but US sub-processors named in its privacy policy | single price | n/a |

### 4b. Legitimacy test

The owner's caveat was: do not design around evading provider pricing, regional restrictions or terms. The
test used here (INFERRED): a price difference is legitimate to route on when **the provider itself publishes
the two prices as alternative products for the same customer**, and illegitimate when reaching the cheaper
price requires misrepresenting who or where the customer is, splitting accounts, or breaking a usage rule.

- **Legitimate:** global versus regional endpoints (every hyperscaler and Anthropic price the global option
  lower and recommend it: "Choose Global for cost optimization" (AWS), "we recommend routing your primary
  traffic to the global endpoint" (Google), "start with Global Standard ... has the lowest price"
  (Microsoft)); batch and Flex tiers; prompt caching; provider-published off-peak rates (DeepSeek);
  model-tier choice; host choice for open-weight models (the same GLM-5.3 or DeepSeek weights are sold by
  several hosts at their own prices); promotional prices published on the price page (Gemini 3.x Flash
  through 2026-12-31, Upstage Mini 4 through 2026-10-22).
- **Not legitimate, and the router must refuse:** serving a user in an unsupported country through the
  platform's Korean account (OpenAI 16.12 makes both the customer and end users subject to the list;
  Anthropic AUP: no facilitating access "in violation of our Supported Regions Policy"); using free or
  promotional quota for paying customers; opening several accounts or projects to stay under limits or
  fees; claiming a data-residency or ZDR arrangement the platform does not hold; using the Gemini free tier
  for customer data; sending personal data to a PRC-hosted endpoint without the 제28조의8 basis.
- **Cross-provider price gaps are large and public**: Claude Fable 5.1 $10/$50 against gpt-6-luna $0.10/$0.50
  is a 100x list gap; DeepSeek V4-Flash is $0.09/$0.18 at DeepInfra against $0.30/$1.20 at Together and
  Fireworks. Routing on them is ordinary purchasing. The compliance risk is not the price but the terms
  attached to the cheaper host (section 2b).
- **"Data stays in Korea" is not a promise the router can make by default.** Only Vertex Seoul (Gemini,
  +10%), Azure APAC Data Zone (five models, +20%, APAC not Korea) and CLOVA Studio (unpriced) keep
  processing near Korea. Every frontier Claude and OpenAI route processes outside Korea.

---

## 5. Prices read on 2026-09-28 (USD per 1M tokens, list)

Frontier and mid tiers, first-party endpoints:

| Model | Input | Cached input | Cache write | Output | Batch in / out | Notes |
|---|---|---|---|---|---|---|
| Claude Fable 5.1 | $10.00 | $0.25 (0.025x) | $12.50 (5 min), $20.00 (1 h) | $50.00 | $5.00 / $25.00 | 1M context at standard price; tokenizer on 4.7+ yields about 30% more tokens |
| Claude Opus 5.5 | $4.00 | $0.20 (0.05x) | $5.00 / $8.00 | $20.00 | $2.00 / $10.00 | fast mode $8 / $40 |
| Claude Sonnet 5 | $2.00 | $0.20 | $2.50 / $4.00 | $10.00 | $1.00 / $5.00 | introductory price made standard on 2026-09-01 |
| Claude Haiku 4.5 | $1.00 | $0.10 | $1.25 / $2.00 | $5.00 | $0.50 / $2.50 | judge tier in the model |
| gpt-6-astra | $10.00 | $1.00 | $12.50 | $50.00 | $5.00 / $25.00 | above 272K input: 2x input, 1.5x output; Flex = batch rates; fast mode 2x |
| gpt-6-sol | $2.00 | $0.20 | $2.50 | $10.00 | $1.00 / $5.00 | |
| gpt-6-luna | $0.10 | $0.01 | $0.125 | $0.50 | $0.05 / $0.25 | |
| gpt-5 / gpt-5.1 | $1.25 | $0.125 | none before GPT-5.6 | $10.00 | $0.625 / $5.00 | same on Azure Global Standard in Korea Central |
| gpt-5-mini / nano | $0.25 / $0.05 | $0.025 / $0.005 | none | $2.00 / $0.40 | 50% | |
| Gemini 2.5 Pro | $1.25 (≤200k), $2.50 (>200k) | $0.125 / $0.25 | storage $4.50 per 1M token-hours | $10.00 / $15.00 | 50% | long-context cliff at 200k |
| Gemini 3.5 Flash | $1.50 (global), $1.65 (Vertex non-global) | $0.15 | storage $1.00 per 1M token-hours | $9.00 / $9.90 | 50% | |
| Gemini 2.5 Flash-Lite | $0.10 | $0.01 | | $0.40 | $0.05 / $0.20 | |
| Gemini 3.8/3.7/3.6 Flash | $0.75 through 2026-12-31, then $1.50 | | | $3.75, then $7.50 | 50% | promotional |

Sources: VERIFIED [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing);
[OpenAI pricing](https://developers.openai.com/api/docs/pricing); [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
(2026-09-24); [Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing); [Azure Retail Prices API](https://prices.azure.com/api/retail/prices).

Open-weight models by host (input / output; cached input where published):

| Model | Cheapest host read | Other hosts |
|---|---|---|
| DeepSeek V4-Flash (V4.1-Flash) | DeepInfra $0.09 / $0.18 | DeepSeek direct $0.15–0.30 / $0.60–1.20 (cache hit $0.003–0.006; off-peak half price); Together $0.30 / $1.20; Fireworks $0.30 ($0.006 cached) / $1.20; OpenRouter listing $0.035 / $0.29 |
| DeepSeek V4-Pro | DeepInfra $1.30 / $2.60 | DeepSeek direct $0.66–1.32 / $1.98–3.96; Together $1.32 ($0.13 cached) / $3.96 |
| DeepSeek V3.2 | DeepInfra $0.26 ($0.13 cached) / $0.38 | |
| Kimi K3 | Moonshot $3.00 ($0.30 cached, $6.00 write) / $15.00 | Together $3.00 / $15.00; Fireworks $3.00 ($0.30 cached) / $15.00 |
| GLM-5.3 | Z.ai $1.40 / $4.40 | Together $1.40 ($0.26 cached) / $4.40; Fireworks $1.40 / $4.40 |
| GLM-5.3-Flash | Z.ai $0.15 / $0.50 | |
| Qwen 3.8 Max | Alibaba $2.00 / $6.00 | Fireworks $2.00 ($0.25 cached) / $6.00 |
| Qwen-Flash / Qwen-Turbo | Alibaba $0.05–0.25 / $0.40–2.00; $0.05 / $0.20 | Together Qwen3.8 Flash $0.09 / $0.28 |
| gpt-oss-120b | Groq $0.15 / $0.60; Together $0.15 / $0.60; Fireworks $0.15 / $0.60 | Cerebras $0.35 / $0.75 |
| Llama 3.3 70B | DeepInfra $0.10 / $0.32 | Together $1.04 / $1.04; Groq "Contact Sales" |
| Mistral Small 4 / Medium 3.5 | Mistral $0.15 / $0.60; $1.50 / $7.50 | batch half price; cached input -90% |
| Solar Pro 4 / Mini 4 (Korean) | Upstage $0.30 ($0.06 cached) / $1.20; $0.10 ($0.01 cached) / $0.40 | prices exclude 10% VAT |

Batch discounts read: 50% at Anthropic, OpenAI (Batch and Flex), Gemini, Vertex, Bedrock, Azure, Fireworks,
Mistral; "up to 50%" at Together; reported but not read at Groq; not verified at Cerebras and DeepInfra.
Service tiers above standard: OpenAI fast mode 2x, Anthropic fast mode (Opus 5.5 $8 / $40), DeepInfra
Priority 1.5x and Flex 0.8x, Fireworks Priority about 1.25x.

---

## 6. Korean requirements for selling metered AI credits

### 6a. 통신판매업 신고 (전자상거래법 제12조)

- Selling prepaid credits for an online service is 통신판매 (제2조 2호 covers "용역" and "용역을 제공받을 수
  있는 권리"; REPORTED statute mirror; VERIFIED [easylaw definition](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=25&ccfNo=1&cciNo=1&cnpClsNo=1)
  기준일 2026-08-15). Every Korean AI-credit seller checked (Upstage, Naver Cloud, Wrtn, LBox, Law&Company)
  displays a 통신판매업신고번호 (VERIFIED on their pages).
- Exemption (공정거래위원회고시, 2022-04-05): "직전년도 동안 통신판매의 거래횟수가 50회 미만인 경우" or a
  간이과세자 (REPORTED mirror; VERIFIED [소비자24](https://www.consumer.go.kr/user/bbs/consumer/380/940/bbsDataView/3579.do)).
  A new business is literally exempt in year one; the PG's card-company review nevertheless expects the
  number in the footer (VERIFIED [Toss blog](https://www.tosspayments.com/blog/articles/semo-5)).
- Filing: 정부24, 등록면허세 40,500원 in Seoul and 광역시 (VERIFIED [Seocho-gu](https://www.seocho.go.kr/site/tax/02/10201020000002023050810.jsp)
  2026-01-30; [정부24 service page](https://www.gov.kr/mw/AA020InfoCappView.do?CappBizCD=11300000006)); the
  document list includes "구매안전서비스 이용 확인증 (선지급식인 경우)", and prepaid credits are 선지급식, so the
  PG contract comes first. Penalty for not filing: 3천만원 이하의 벌금 (VERIFIED [easylaw](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=25&ccfNo=2&cciNo=2&cnpClsNo=1)).

### 6b. 부가통신사업 (전기통신사업법 제22조)

- 제22조 ④ 1: a small 부가통신사업 is deemed filed; 시행령 제30조 ①: "인터넷을 이용하여 부가통신역무를 제공하는
  자본금 1억원 이하인 부가통신사업자"; ②: file within one month once 자본금 exceeds 1억원 (VERIFIED
  [중앙전파관리소](https://www.crms.go.kr/lay1/S1T54C59/contents.do)). An 개인사업자 has no 자본금 and is
  deemed filed (INFERRED). Penalty above the line without filing: up to 2년 징역 or 1억원 벌금 (VERIFIED easylaw).

### 6c. VAT (부가가치세법)

- **Korean customers:** 10% VAT; 전자세금계산서 mandatory for 법인 and for 개인사업자 above 8천만원 prior-year supply
  (VERIFIED [NTS](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=2461&cntntsId=7787)); 현금영수증 for
  consumer sales (VERIFIED [NTS](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=2470&cntntsId=7795)).
- **Foreign customers:** 영세율 under 제24조 ① 3 with 시행령 제33조 ② 1 바목, which lists "정보통신업 중 ...
  자료처리, 호스팅, 포털 및 기타 인터넷 정보매개서비스업, 기타 정보 서비스업" supplied to a 국내사업장이 없는
  비거주자 or 외국법인, paid through an 외국환은행 or the methods in the 시행규칙 (REPORTED mirrors; VERIFIED
  [KLRI translation](https://elaw.klri.re.kr/eng_mobile/viewer.do?hseq=63474&type=part&key=20)). Proof: an
  외화입금증명서 from the FX bank per 시행령 제101조 (REPORTED). Whether a PayPal or Paddle payout through a
  Korean bank satisfies the payment-method condition is a question for the tax adviser (UNKNOWN). A
  간이과세자 cannot use this route, hence gate 1 in section 1b.
- **Buying inference abroad:** no 대리납부 while the platform is a 과세사업자 using the inputs for its taxable
  service (제52조 ① parenthetical; REPORTED mirror and accounting-firm explanation). Enter the 사업자등록번호 in
  the Anthropic and OpenAI consoles; whether either then charges Korean VAT is NOT VERIFIED on their pages
  (REPORTED: business registration number exempts).

### 6d. 전자금융거래법: are the platform's credits 선불전자지급수단?

- Definition, 제2조 14호 (법률 제19734호, 시행 2024-09-15): "이전 가능한 금전적 가치가 전자적 방법으로 저장되어
  발행된 증표 ... 로서 발행인(대통령령으로 정하는 특수관계인을 포함한다) 외의 제3자로부터 재화 또는 용역을 구입하고 그
  대가를 지급하는데 사용되는 것" (REPORTED mirror; law.go.kr blocked).
- Every source found says a credit redeemable only for the issuer's own service is outside the definition:
  법무법인 세움 (2023-11-15, "자기발행형 상품권은 여전히 선불전자지급수단에 해당하지 않습니다"), 김·장 (2023-08, the
  "제3자성 요건은 여전히 유지"), 율촌 (2024), 최앤리 (2025-07-17); the FSC/FSS 법령해석 of 2024-03-27 applies the
  same third-party test (all REPORTED). The 특수관계인 carve-out was removed, so use by a parent or subsidiary
  now counts as third-party use (REPORTED 율촌).
- **Design constraint (INFERRED):** the exclusion holds only while credits buy the platform's own service and
  are not transferable between users or convertible into other issuers' goods or means. Forwarding a request
  to Anthropic is the platform's own service because the customer contracts with the platform. A marketplace,
  a gift or transfer feature, or reselling a provider subscription would turn the credit into a
  선불전자지급수단.
- If it ever applied: registration exemptions in 제28조 ③ 1 (가: used at 하나의 가맹점 with the same 사업주;
  나: 발행잔액 under 30억원 and 연간 총발행액 under 500억원, 시행령 제15조 ⑤), and if registered, 100% of the
  float in trust, deposit or insurance (제25조의2, 시행령 제13조의2) and the 제19조 refund rules (full refund
  when the balance falls below a threshold that may not be set under 20%) (all REPORTED mirrors and law firms;
  the FSC press release is blocked). Confirm the outside-the-definition reading with counsel before launch.

### 6e. 청약철회 and refunds (전자상거래법 제17조; soft law)

- 7-day withdrawal from the contract document (제17조 ① 1). No withdrawal once "용역 또는 ... 디지털콘텐츠의 제공이
  개시된 경우", except that for "가분적 용역" the part not yet started stays withdrawable (② 5), and the seller
  must display the no-withdrawal fact clearly or lose the exception (⑥) (VERIFIED [easylaw](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=25&ccfNo=3&cciNo=3&cnpClsNo=3);
  REPORTED mirror). Reading for credits (INFERRED): consumed credits are started service, the unused balance
  is withdrawable within 7 days of purchase, later refunds follow the platform's terms.
- Norms for the unused balance: 소비자분쟁해결기준 (공정거래위원회고시 제2024-32호) refunds unused paid content
  within 7 days and, for game cash, the balance less up to 10% for bank and PG fees (VERIFIED [easylaw
  online game](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=2858&ccfNo=2&cciNo=1&cnpClsNo=2));
  콘텐츠이용자 보호지침 refunds within 3 영업일 of a termination notice and requires 30 days' notice before
  ending a point service (REPORTED, older version).
- Pre-contract disclosure (제13조 ②): price and payment timing, withdrawal rules, refund conditions, the 약관,
  and, for 선지급식 sales, the escrow or insurance election unless paid by card (REPORTED mirror; VERIFIED
  easylaw on 제10조 footer items and the 1천만원 이하 과태료).

### 6f. 이용약관 and 개인정보처리방침

- 개인정보 보호법 제30조 requires a published 처리방침 listing purposes, retention, third-party provision and
  처리위탁 (REPORTED mirror; VERIFIED [PIPC portal](https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=283)).
- **제28조의8 (국외 이전)**: cross-border provision, entrusted processing or storage is prohibited unless one
  of five bases applies. The practical basis for an inference API is ① 3: 처리위탁·보관 necessary for the
  contract **and** the ② items (transferred items; country, timing and method; recipient name and contact;
  recipient's purpose and retention; how to refuse and its effect) disclosed in the 처리방침 (REPORTED
  [mirror](https://casenote.kr/법령/개인정보_보호법/제28조의8); VERIFIED [PIPC summary](https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=367)
  and [KLRI translation](https://elaw.klri.re.kr/eng_mobile/viewer.do?hseq=62389&type=part&key=4)). ⑤ bars
  transfer contracts whose terms violate the Act; 제28조의9 lets the PIPC order transfers stopped, which is
  what happened to DeepSeek. Consequence: the candidate provider list is fixed in the policy before routing
  (rule 9 in section 3).
- 약관의 규제에 관한 법률 제3조: terms in Korean, shown clearly at contract time, copy on request (REPORTED).

### 6g. AI Basic Act (인공지능 발전과 신뢰 기반 조성 등에 관한 기본법, 법률 제20676호, 시행 2026-01-22)

- Art. 31(1): an operator providing a product or service using generative AI "shall notify the user in
  advance that the product or service is operated based on the relevant artificial intelligence"; 31(2):
  "shall label that the output was generated by generative artificial intelligence"; Art. 43(1): fine up to
  30 million won for missing the notice (VERIFIED KLRI translation). An 이용사업자 that connects external models
  by API is covered (REPORTED datalaw.kr). The ministry runs a 계도기간 of at least one year from 2026-01-22
  with fines and fact-finding suspended, deepfake labelling excluded; no SME exemption (VERIFIED
  [korea.kr](https://www.korea.kr/news/policyNewsView.do?newsId=148954629) 2025-11-12; REPORTED Shin & Kim
  2026-02-11).

---

## 7. Payment processors a Korean 사업자 can actually use

| Processor | Korean seller? | Fee read | Settlement | Merchant of record | Stored-value line in its terms | Time to first payment | Source |
|---|---|---|---|---|---|---|---|
| **Toss Payments** | yes | card 3.4% (일반) + VAT; 가입비 220,000원, 연관리비 110,000원; 해외카드 by separate contract (fee not printed; REPORTED 4.5%); PayPal via Toss 4.0% + $0.30 + 2.5% | about 5 days; KRW | no | none | Toss review 1–2 days, card review up to 14 days | VERIFIED [fees](https://www.tosspayments.com/about/fee); [FAQ](https://docs.tosspayments.com/resources/faq); [foreign payment](https://docs.tosspayments.com/guides/v2/learn/foreign-payment) |
| **PayPal Business Korea** | yes | receiving from outside Korea 4.40% + $0.30; FX 3.00% on other conversions; withdrawal to a KRW account free above 150,000원, 3–5 business days, $20,000 a day | USD balance | no | pre-approval only for "the sale of stored value cards and escrow services" | same day | VERIFIED [fees](https://www.paypal.com/kr/webapps/mpp/merchant-fees) (2026-05-28); [AUP](https://www.paypal.com/us/legalhub/paypal/acceptableuse-full) (2022-10-29) |
| **Paddle** | yes (not on the blocked list) | 5% + $0.50; tax registration and remittance included | monthly, USD wire or Payoneer, no KRW, bank converts | yes | prohibited: "Virtual currency or stored value, including but not limited to store credit, gift cards, vouchers"; written confirmation needed that prepaid SaaS usage is not "store credit" | domain review 5–7 business days, business review 2–4 days | VERIFIED [countries](https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle); [pricing](https://www.paddle.com/pricing); [prohibited](https://www.paddle.com/help/start/intro-to-paddle/what-am-i-not-allowed-to-sell-on-paddle) (2026-04-13) |
| **Polar.sh** | yes (South Korea in the payout list) | 5% + $0.50 (Starter) down to 3.4% + $0.30; international cards +1.5%; payout $2 a month + 0.25% + $0.25 + up to 1% cross-border | Stripe Connect Express | yes | none; "AI Content Generation tools" get closer review | not verified | VERIFIED [countries](https://polar.sh/docs/merchant-of-record/supported-countries); [fees](https://polar.sh/docs/merchant-of-record/fees); [AUP](https://polar.sh/docs/merchant-of-record/acceptable-use) (2026-03-25) |
| **Lemon Squeezy** | yes (Republic of Korea listed) | 5% + $0.50; international +1.5%; payout 1% outside the US | twice monthly | yes | none | store activation review, duration not verified | VERIFIED [countries](https://docs.lemonsqueezy.com/help/getting-started/supported-countries); [fees](https://docs.lemonsqueezy.com/help/getting-started/fees); [2026 update](https://www.lemonsqueezy.com/blog/2026-update): migrating users to Stripe Managed Payments, which excludes Korea |
| **Eximbay** | Korean businesses only | 33만원 non-refundable review fee; global cards REPORTED 4.50%; USD 1,000 a month starting cap | weekly batches settled 3 weeks later; KRW or USD | no | none | about 2–3 weeks (REPORTED) | VERIFIED [fees](https://www.eximbay.com/guide/guide-fee-online.do); [PortOne help](https://help.portone.io/content/eximbay-international) |
| **PortOne** | yes | free plan under 5,000만원 monthly; cross-border 0.5% with USD 500 monthly minimum | per underlying PG | no | none | per PG | VERIFIED [pricing](https://www.portone.io/pricing) (2026-07-31) |
| **Stripe** | **no** (Korea absent from supported countries; Managed Payments excludes Korea) | 3.1% + 30¢ for Korean methods from a foreign account | | | "Seller-maintained stored value or credits may be subject to limits" | only via a foreign entity (Atlas $500 + $100 a year, EIN 10–45 business days) | VERIFIED [global](https://stripe.com/global); [restricted](https://stripe.com/legal/restricted-businesses) (2026-09-22); [Atlas](https://docs.stripe.com/atlas/signup) |
| Wise Business | no ("대한민국 국내 주소로 등록된 Wise 계정으로는 법인 계정을 만들 수 없습니다") | | | | | | VERIFIED [Wise KR](https://wise.com/kr/blog/corporate-account-opening) (2025-12-23) |
| KG Inicis, NHN KCP, Payletter | Korean only; KCP: "비실물 서비스인 '컨텐츠' 일 경우 입점이 불가합니다" | REPORTED 4.5–5% on foreign cards | KRW | no | | 특약 plus 보증보험 (Inicis) | VERIFIED [PortOne KCP](https://help.portone.io/content/kcp-international); [Inicis](https://help.portone.io/content/inicis-international) |
| Crypto | legal to accept but outside the FX bank channel; 외국환거래법 amendment on cross-border virtual-asset transfers effective December 2026 | | | | | not recommended | VERIFIED [etoday](https://www.etoday.co.kr/news/view/2621112) (2026-09-02) |

Unit economics that follow (INFERRED): every processor charges a fixed fee of $0.30 to $0.50 per transaction
plus 3.4% to 5%, and FX or payout fees on top for foreign customers. A metered request that costs cents
cannot be charged per request; the only workable billing is **prepaid top-ups** in amounts where the fixed
fee is under 1% (₩50,000 or $50 and up), which is also why the credit design in 6d matters. 외국환거래: a single
current-account receipt up to USD 10,000 needs no BOK 신고 (VERIFIED [BOK](https://www.bok.or.kr/portal/main/contents.do?menuNo=200404)).

---

## 8. Economics: what legitimate routing, caching and compression can capture

All numbers below are **list prices read on 2026-09-28** and published measurements; the savings are **inferred**
arithmetic, not a measured result on this business's traffic. The model is `tools/routing_economics.py`.

### 8a. The levers and their verified multipliers

| Lever | Verified multiplier | Applies to | Source (page date) |
|---|---|---|---|
| Provider prompt caching | Cache read 0.1x base input (0.025x on Claude Fable 5.1 and Mythos 5.1, 0.05x on Opus 5.5); 5-minute write 1.25x, 1-hour write 2x; minimum 512 to 4,096 tokens per model. OpenAI: cached input 0.1x on GPT-5.6 and later (gpt-4o 50%, o3 25%), automatic, 1,024-token minimum. Gemini: cached tokens 0.1x input plus storage $4.50 per 1M tokens per hour on Pro. | The stable prefix (system prompt, tool schemas, a document) re-read within the TTL | VERIFIED [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing); [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching); [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Batch / async | 50% on input and output at Anthropic, OpenAI, Gemini, Bedrock and Azure; 24-hour window; stacks with caching at Anthropic and OpenAI. OpenAI Flex = batch rates on a synchronous best-effort call. | Requests that can wait | VERIFIED [Anthropic batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing); [OpenAI batch](https://developers.openai.com/api/docs/guides/batch); [Gemini batch](https://ai.google.dev/gemini-api/docs/batch-mode) (2026-09-17); [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/); [Azure batch](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/batch) (2026-05-13) |
| Model routing | Price gap between tiers today: Claude Fable 5.1 $10/$50 vs Sonnet 5 $2/$10 vs Haiku 4.5 $1/$5; gpt-6-astra $10/$50 vs gpt-6-luna $0.10/$0.50; DeepSeek-V3.2 on DeepInfra $0.26/$0.38. RouteLLM held 95% of GPT-4 quality while sending only 14% to 54% of queries to the strong model, cutting cost "over 85% on MT Bench, 45% on MMLU, and 35% on GSM8K" with a 100:1 price gap. RouterBench: prices vary "2-5x for comparable levels of performance"; cascades beat naive mixing only while the judge's error rate stays at or below 0.1. | The share of requests a cheaper model answers to the quality bar | VERIFIED [RouteLLM](https://arxiv.org/abs/2406.18665) (2024-06-26); [RouterBench](https://arxiv.org/abs/2403.12031) (2024-03-18); [FrugalGPT](https://arxiv.org/abs/2305.05176) (2023-05-09, "range from 50% to 98%" on 2023 classification tasks); REPORTED [Not Diamond Code](https://www.notdiamond.ai/blog/not-diamond-code-intelligent-model-routing-for-coding-agents) (2026-08-04, 39% and 61% cost cuts, vendor benchmark) |
| Semantic cache (platform side) | About 31% of queries in a real log were repeats or near-repeats (MeanCache); 40-60% hit rates in high-repetition categories against 5-15% in the long tail; static similarity thresholds "result in unexpected error rates" (vCache). | Only the same tenant's traffic; never across customers, because one customer's answer must not reach another | VERIFIED [MeanCache](https://arxiv.org/abs/2403.02694); [arXiv 2510.26835](https://arxiv.org/abs/2510.26835) (2025-10-29); [vCache](https://arxiv.org/abs/2502.03771) (ICLR 2026); REPORTED [Redis LangCache](https://redis.io/langcache/) customer quote "70% cache hit rate" |
| Prompt compression / passage extraction | LLMLingua "up to 20x compression with little performance loss"; LLMLingua-2 2x to 5x; Selective Context "50% reduction in context cost"; RECOMP compresses retrieved documents "as low as 6%". Task-dependent quality loss; competes with prefix caching because a compressed prefix that changes per request cannot be cached. | The non-shared part of long inputs | VERIFIED [LLMLingua](https://arxiv.org/abs/2310.05736); [LLMLingua-2](https://arxiv.org/abs/2403.12968); [Selective Context](https://arxiv.org/abs/2310.06201); [RECOMP](https://arxiv.org/abs/2310.04408) |
| Long-context cliff | Gemini 3.1 Pro: $2.00 input up to 200k tokens, $4.00 above; output $12 vs $18. OpenAI: above 272K input tokens 2x input and 1.5x output. Current Claude models: "the full 1M token context window at standard pricing", no cliff. | Requests near 200k tokens on Gemini Pro and 272K on OpenAI | VERIFIED [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing); [OpenAI gpt-6-astra](https://developers.openai.com/api/docs/models/gpt-6-astra); [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Region choice | Anthropic: global routing is the default and cheapest; `inference_geo: "us"` costs 1.1x on Claude 4.6 and later; on Bedrock and Google Cloud "Regional and multi-region endpoints include a 10% premium over global endpoints"; Azure APAC Data Zone +20% in Korea Central. The provider itself prices the region choice, so picking the global endpoint when the customer allows it is a sanctioned saving, not an evasion. | Requests without a residency constraint | VERIFIED [Anthropic pricing, cloud platform section](https://platform.claude.com/docs/en/about-claude/pricing); section 4 |
| Quality judge cost | A small-model judge reading a 2,000-token answer costs about $0.002 (Haiku 4.5) or $0.0002 (gpt-6-luna) against a $0.045 frontier call it may avoid: 0.5% to 5% overhead. LLM judges reach 85% agreement with humans (humans agree 81%). | Every answer from the cheap tier | VERIFIED [MT-Bench judge paper](https://arxiv.org/abs/2306.05685); INFERRED overhead |

### 8b. Three workloads at list prices (inferred)

Assumptions per workload are in the script; the frontier tier is Claude Fable 5.1 ($10/$50), the judge is Claude Haiku 4.5, and "easy share" is the fraction the judge confirms a cheaper model answered to the bar (50%, 60%, 30%), a middle value inside RouteLLM's 46% to 86% range.

| Workload (per month) | Baseline, all frontier | Caching + batch only (the customer can do this alone) | Plus routing to Claude Sonnet 5 | Plus routing to gpt-6-luna |
|---|---|---|---|---|
| Chat assistant: 1,000,000 requests, 1,500 in (1,000 shared prefix) / 300 out, none batchable | $30,000 | $20,350 (-32%) | $11,994 (-60%) | $10,098 (-66%) |
| Document extraction: 100,000 requests, 20,000 in (2,000 shared) / 500 out, 80% batchable, half the input removable by extraction | $22,500 | $12,350 (-45%) | $3,682 (-84%) | $2,882 (-87%) |
| Coding agent: 50,000 turns, 60,000 in (40,000 shared) / 4,000 out, none batchable | $40,000 | $20,700 (-48%) | $14,414 (-64%) | $13,274 (-67%) |

Reading the table honestly:

- **A third to a half of the saving needs no router.** Prefix caching and batch are provider features any customer can switch on. A platform that charges a share of "verified savings" must measure against what the customer could do alone, or the customer's own engineer will.
- **The routing increment is worth 20 to 40 points** on these workloads and depends entirely on the routable share and the judge's error rate. RouterBench found learned routers of 2024 did not beat a cost-weighted mix of two models; the gain comes from the judge-verified cascade, which pays for the cheap model and the judge before any escalation.
- **The customer is often price-insensitive where the spend is.** Menlo Ventures reports coding users "are actually quite price-insensitive and will pay more for performance" (REPORTED, [2025-12-09](https://menlovc.com/perspective/2025-the-state-of-generative-ai-in-the-enterprise/)); the a16z CIO survey says the opposite for commodity tasks ("pricing has become a much more important factor", REPORTED, [2025-06-10](https://a16z.com/ai-enterprise-2025/)). The addressable customer is the one with high-volume, repetitive, latency-tolerant traffic.
- **Transport is free.** Vercel AI Gateway "charges no markup and no platform fee on tokens" (VERIFIED, [2026-09-08](https://vercel.com/docs/ai-gateway/pricing)) and OpenRouter's auto router has "no additional fee" (VERIFIED, [docs](https://openrouter.ai/docs/features/model-routing)). A Korean router cannot charge for access; it can only charge for measured savings or convenience.
- **The share of enterprise inference spend that is routable is not published** (not verified). The closest proxies are RouteLLM's routable fractions and MeanCache's 31% repeat rate.
- **Payment fees eat small tickets** (section 7): at 5% plus $0.50 a $10 top-up loses 10%; the platform's margin on a share of savings must clear the PG fee, FX, the refund reserve and the judge cost before it is profit.

---

## 9. What the build thread can gate on

Registry entries for task 13 carry these fields beyond schema v1 (the core loader ignores unknown fields, so
schema_version stays 1):

| Field | Values | Use in the router |
|---|---|---|
| `service` | `ai_inference`, `ai_inference_gateway`, `ai_inference_aggregator` (payment entries carry `roles = ["payment"]` and no `service`) | which entries are model suppliers |
| `customer_app_allowed` | `explicit` (terms grant serving own end users), `not_prohibited` (no clause either way), `unclear` (self-serve terms grant internal use only), `prohibited for resale` | route only through `explicit` in the first pilot; `not_prohibited` after counsel; never `unclear` without a written arrangement |
| `resale_prohibited` | true/false | always true for every provider read; the product must never present itself as resale |
| `training_on_inputs` | free text with the clause | never send customer content where training is the default |
| `data_residency` | free text | the residency option and its price, if any |
| `pricing_url` | https | the price page the ledger's list prices come from |
| `verdict`, `region_ok_for_korea`, `unknown_because` | schema v1 | as in [docs/platform_eligibility.md](platform_eligibility.md) |

Entry ids: `anthropic_api`, `openai_api`, `google_gemini_api`, `google_vertex_ai`, `aws_bedrock`,
`azure_openai_foundry`, `groq_cloud`, `cerebras_inference`, `mistral_la_plateforme`, `together_ai`,
`fireworks_ai`, `deepinfra`, `openrouter`, `vercel_ai_gateway`, `cloudflare_ai_gateway`, `upstage_solar`,
`naver_clova_studio`, `deepseek_api`, `alibaba_model_studio_intl`, `moonshot_kimi`, `zai_glm`,
`toss_payments`, `paypal_business_kr`, `paddle`, `polar_sh`, `lemon_squeezy`, `eximbay`, `portone`, `stripe`.
An entry moves to `connected = true` or `status = "live"` only in a PR that records the real request or
payment that was verified and when.

---

## 10. What was verified, inferred, and not reached

- **Verified on the provider's own pages:** Anthropic commercial terms, usage policy, supported regions,
  data residency, pricing, credit terms, help centre; OpenAI developer docs (pricing, supported countries,
  data controls, batch, Flex, fast mode, caching); Google Gemini terms, regions, pricing, batch, caching;
  Google Cloud terms, service-specific terms, reseller terms, Vertex locations, data residency, pricing;
  AWS customer agreement, service terms, Bedrock region, cross-region, caching and batch docs, the Bedrock
  price feed and Price List API; Microsoft Online Subscription Agreement, limited access, code of conduct,
  CSP overview, deployment types, region availability, data privacy, batch, caching, Retail Prices API;
  Groq, Cerebras, Mistral, Together, Fireworks, DeepInfra, OpenRouter, Vercel, Cloudflare terms and price
  pages; Upstage, Naver Cloud, DeepSeek, Alibaba, Moonshot, Z.ai pages; PIPC DeepSeek decision; Korean
  government pages on easylaw.go.kr, crms.go.kr, nts.go.kr, consumer.go.kr, seocho.go.kr, gov.kr, privacy.go.kr,
  korea.kr, bok.or.kr and the KLRI translations; Toss, PayPal, Paddle, Polar, Lemon Squeezy, Eximbay,
  PortOne, Stripe, Wise pages.
- **Verified from web.archive.org snapshots** because openai.com and help.openai.com return 403 here: the
  Services Agreement (2026-09-26 snapshot), usage policies (2026-09-27), service credit terms (2026-09-03),
  prepaid billing help (2026-04-26), key-safety help (2026-09-21), data-residency announcement (2026-07-15).
- **Reported only:** Microsoft Product Terms "Customer Solution" clause (mirror PDF of 2025-03-12); every
  Korean statute article quoted from lbox, bigcase, casenote or ulex; the FSC/FSS 법령해석; law-firm readings of
  전자금융거래법; Toss 해외카드 and Eximbay rates via PortOne's comparison; Groq batch discount; Naver CLOVA
  price ratio.
- **Not reached:** law.go.kr, fsc.go.kr, Microsoft licensing terms site, Google Partner Advantage, Vertex
  Claude regions page (404), Azure and Bedrock HTML price pages (placeholders), Naver CLOVA Studio price
  values and FAQ (404), Fireworks billing docs (404), the Gemini explicit-cache default TTL, OpenAI's Korean
  VAT behaviour, Anthropic's Korean VAT behaviour, the 시행규칙 payment methods for 영세율, the current
  콘텐츠이용자 보호지침, Paddle's position on prepaid SaaS usage, Toss 해외카드 rate, Alibaba Cloud International
  general terms, Kakao Pay direct 온라인 가맹점 timing beyond its own page.
- **Deliberately not done:** no account was opened, no key requested, no payment contract started, no
  message sent to any provider. Every registry entry is `connected = false`.
