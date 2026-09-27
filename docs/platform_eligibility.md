# Platform eligibility and Korean requirements

**Date of verification: 2026-09-27.** Owner: Claude, thread "Platform eligibility and Korea requirements",
branch `claude/platform-eligibility-aaclam`. The machine-readable companion is
[`integrations/registry.toml`](../integrations/registry.toml); every entry there is `connected = false`
and stays so until a real operation against the platform has been verified in a PR.

**Nothing in this document is live, connected, or authorised to spend.** It records what each platform's
own terms and Korean law allow, so the operating core can enforce the rules and the owner can see exactly
which accounts, registrations and credentials are still missing.

Evidence tags used below:

| Tag | Meaning |
|---|---|
| **VERIFIED** | read on the platform's own page or a Korean government page on 2026-09-27; the link and the page's own date are given |
| **REPORTED** | press, law-firm or seller-tool page; not confirmed on an official page |
| **INFERRED** | our reasoning from verified facts |
| **UNKNOWN** | could not be reached or found; treated as *not approved*, never as approval |

Unreachable from this environment on 2026-09-27 (curl: connection reset or timeout; WebFetch: JS shell or
403): `law.go.kr` article bodies, `safetykorea.kr`, `ftc.go.kr` (most pages), `consumer.go.kr`, `crms.go.kr`,
`open.temu.com`, Temu partner documentation pages, `portals.aliexpress.com`, `helpcenter.aliexpress.com`,
`sell.smartstore.naver.com` notices, `partners.coupang.com` API guide (403). Where a worker or this thread
reached a `customs.go.kr`, `nts.go.kr`, `easylaw.go.kr`, `korea.kr`, `kats.go.kr`, `rra.go.kr`, `mfds.go.kr`
or `moleg.go.kr` page, that page is cited as VERIFIED.

---

## 1. Go / no-go matrix

Supplier (sourcing) roles and sales-channel (selling) roles are separate, even for the same company.

### 1a. Suppliers (where we buy)

| Platform | Verdict | Why | Key source (page date) |
|---|---|---|---|
| **AliExpress** (buyer account + Dropshipping Center + Open Platform DS API) | **GO** | Dropshipping is officially supported: "The dropshipper is considered to be a buyer", sell "to any other eCommerce platform". Terms of Use (updated 2026-08-26, effective 2026-09-26) contain no resale or third-party-address restriction; they ban copying and systematic retrieval of site content (3.2(a)), so **API only, never HTML**. | VERIFIED [Terms of Use](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_aliexpress/suit_bu1_aliexpress202204182115_66077.html) (2026-08-26); [Beginner's Guide for Dropshipping](https://openservice.aliexpress.com/doc/doc.htm#/?docId=1646) (2025-01-13); [Business Program agreement](https://terms.alicdn.com/legal-agreement/terms/c_end_product_protocol/20240204100040824/20240204100040824.html) (2024-02-01) |
| **Temu** consumer site/app as a sourcing supplier | **NO-GO today: not approved** | Korean Terms of Use (발효일 2026-08-31): §3.1 use for yourself, not for the benefit of a third party; §7.4 personal, non-commercial access; §7.5 commercial use or use for another business needs Temu's prior express permission; §3.4 restricts the listed automation and scraping. These are service-use restrictions, not a statutory ban on reselling physical goods, and the introduction contemplates company representatives. No commercial terms or permission exist for this business, so automated consumer-checkout sourcing is **not approved**. An authorised public buyer-purchasing API was **not verified** (none found; `open.temu.com` unreachable). Re-evaluate only with written permission from Temu. | VERIFIED [temu.com/kr/terms-of-use.html](https://www.temu.com/kr/terms-of-use.html) (2026-08-31); [global ToU](https://www.temu.com/terms-of-use.html) (2025-11-07); UNKNOWN `open.temu.com` |
| **1688.com** | CONDITIONAL (stock model only) | Ships inside mainland China only; needs a forwarding warehouse or agent; payment by international card or KakaoPay (+2%); API only for partner tiers. Every lot is a commercial import (mode B below). | REPORTED [windly 1688 payment](https://www.windly.cc/blog/1688-how-to-pay) (2025-08-08); [howtotao partner program](https://www.howtotao.com/1688-cross-border-partner-program/) (2024-06-13) |
| **Alibaba.com** | CONDITIONAL (replenishment of a proven product) | Wholesale with MOQ, Trade Assurance, no buyer API; stock model. | VERIFIED [Trade Assurance](https://buyer.alibaba.com/page/tradeassurance/buyer/story.html) |
| Taobao/Tmall, DHgate, Banggood | later | Ship to the account holder (Taobao 官方直邮) or worldwide (DHgate, Banggood); no buyer APIs; not needed for the first sale. | REPORTED only |

### 1b. Sales channels (where we sell)

| Platform | Verdict | Why | Key source (page date) |
|---|---|---|---|
| **Naver Smart Store** | **GO, 사업자 판매자 only** — recommended first channel | Since 2026-06-24 the overseas-product selling right (해외상품판매권한) is granted to 국내사업자 only; a 국내 개인 seller cannot obtain it, so cannot list 구매대행 items. Fees for a new business about 6.63% (판매수수료 3% + Npay 3.63%), 1% instead of 3% on orders from the seller's own links or Naver ads. Payout 1 business day after order end. Commerce API is free and self-service. | VERIFIED [faqId=3757](https://help.sell.smartstore.naver.com/faq/content.help?faqId=3757); [faqId=3664](https://help.sell.smartstore.naver.com/faq/content.help?faqId=3664); [faqId=15759](https://help.sell.smartstore.naver.com/faq/content.help?faqId=15759) (from 2025-06-02); [faqId=3713](https://help.sell.smartstore.naver.com/faq/content.help?faqId=3713) (from 2025-10-01); [faqId=3630](https://help.sell.smartstore.naver.com/faq/content.help?faqId=3630) |
| **Coupang Marketplace** (WING + Open API) | **GO, 사업자 only** — second channel | Registration documents exist only for 개인사업자/법인; 통신판매업신고증 can be uploaded later and is waived for 간이과세자 since 2026-06. Commission 4-10.9% by category + 10% VAT on the commission, ₩55,000/month once monthly sales reach ₩1,000,000. 주정산 pays 70% about 15 business days after the week, 30% later. 구매대행 listings use `deliveryMethod = AGENT_BUY`, `pccNeeded = true`; the buyer's customs code comes back in the order sheet. Open API needs no approval, a fixed-IP whitelist (10 IPs), keys expire after 180 days, no sandbox. | VERIFIED [mba/register](https://marketplace.coupang.com/mba/register); [간이과세자 signup](https://marketplace.coupang.com/information-center/kupang-panmaeja-gaib-ije-seoryu-junbi-eobsi-1bunimyeon-ggeut-feat-ganigwaseja-ibjeom-gansohwa); [Fee table](https://cloud.mkt.coupang.com/Fee-Table) (2019-11-25); [수수료 explainer](https://marketplace.coupang.com/information-center/almyeon-alsurog-deo-joheun-kupang-susuryo-2); [구매대행 listing FAQ](https://developers.coupang.com/ko/faq/how-can-i-list-products-as-an-overseas-buying-agent); [order sheet](https://developers.coupang.com/ko/api/shipments/single-po-query-using-orderid); [API key](https://developers.coupang.com/hc/en-us/articles/20288952179993-Issue-Open-API-Key-NEW); REPORTED [settlement timing](https://www.windly.cc/blog/coupang-settlement-guide-pre-2026) (2025-11-24) |
| Gmarket / Auction (ESM PLUS) | CONDITIONAL (third channel) | Real seller API (ESM Trading API, notices dated 2026); ₩55,000 server fee at ₩5,000,000 monthly sales; ownership moved to the Shinsegae-Alibaba joint venture in 2025. | VERIFIED [fee page](https://www.esmplus.com/commonpopup/gmarketusecost); [etapi.gmarket.com](https://etapi.gmarket.com/) |
| 11st | CONDITIONAL | Open API Center, key valid 180 days (notice 2026-06-24); fees reported 7-13%. | VERIFIED [Open API Center](https://openapi.11st.co.kr/openapi/OpenApiFrontMain.tmall) |
| **Temu Korea local seller** (kr.seller.temu.com) | CONDITIONAL — a *selling* role, not sourcing | Free registration, review within one business day (landing page). Reported requirements: 사업자등록증, 통신판매업신고번호, Korean stock and self-fulfilment. Commission and settlement not published; Partner Platform apps are seller-authorised (terms 2025-02-26); scopes and Korean hosts UNKNOWN (documentation renders only behind login). | VERIFIED [Korea Seller Center](https://kr.seller.temu.com/login.html?login_scene=302); [Partner Platform terms](https://partner.temu.com/protocol/temu_partner_platform_terms_20250523.pdf) (2025-02-26); UNKNOWN [seller authorization guide](https://partner.temu.com/documentation?menu_code=38e79b35d2cb463d85619c1c786dd303); REPORTED [Korea Herald](https://www.koreaherald.com/article/10423905) (2025-02-19) |
| AliExpress K-Venue | CONDITIONAL | Selling Korean-stocked goods on AliExpress; 사업자등록증, ~5 business days review; commissions since 2025-02-01 (reported). | REPORTED [klnews](https://www.klnews.co.kr/news/articleView.html?idxno=315149) (2025-01-02) |
| Cafe24 own store + 마켓플러스 | CONDITIONAL | One Admin API fanning out to about 60 channels; needs a PG contract (Toss Payments card 3.4%, signup ₩220,000). | VERIFIED [마켓플러스](https://www.cafe24.com/commerce/channel/market.html); [Toss fees](https://www.tosspayments.com/about/fee) |
| Kakao 톡스토어, SSG.com | later | API granted selectively (Kakao) or via tools; not for the first sale. | VERIFIED [Kakao fees](https://kakaobusiness.gitbook.io/main/tool/talkstore) |
| Qoo10 Korea | NO-GO | Korean site effectively gone after the 2024 settlement crisis. | REPORTED |

### 1c. Affiliate channels and research sources

| Service | Verdict | Why | Key source |
|---|---|---|---|
| AliExpress Affiliate (Portals) + Affiliate API | **GO** (research feed and affiliate income) | Individuals allowed; app key without user OAuth; `aliexpress.affiliate.product.query` (already in `src/arbitrage/sources/aliexpress.py`) plus `product.shipping.get`. Must live in a different Open Platform account from the DS app. Data may only be used inside the approved app. | VERIFIED [Affiliate agreement](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_aliexpress/suit_bu1_aliexpress202003132026_84536.html) (2022-03-31); [one account one role](https://openservice.aliexpress.com/doc/doc.htm#/?docId=1935) (2025-06-13); [API Use Agreement](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_aliexpress/suit_bu1_aliexpress202201220006_10755.html) |
| Temu Affiliate (Korea) | GO (referral income only) | Up to 30% commission, ₩15,000 per referred download, 30-day cookie, ₩14,000,000 monthly cap. Does not license resale. | VERIFIED [affiliate_recruit](https://www.temu.com/kr/affiliate_recruit.html) |
| Coupang Partners API | CONDITIONAL | Only legitimate programmatic source of Coupang prices found. Key issued only after 최종승인 (a real content channel). Search limited to 10 calls/hour, about 10 products per call; one violation blocks the API for 24 hours. Fits spot checks, not scans. | VERIFIED [Partners guide PDF](https://partners.coupangcdn.com/partners-guide/partners-guide-20240711135620.pdf) (v.1, 2021-07, 2024-08 update) |
| **Naver Developers 검색 API › 쇼핑** (current market source in `src/arbitrage/sources/naver_shopping.py`) | **NO-GO: discontinued** | NAVER API 서비스 이용약관 (2026-09-07 개정, 부칙 2026-07-31) 제2조③: the 쇼핑, 책 and 학술정보 search services "2026년 7월 31일 24:00부로 종료" and existing users "2026년 8월 1일 00:00부터는 해당 API를 더 이상 이용할 수 없습니다". Its terms never allowed storing or reselling results. NAVER API HUB lists no product search. | VERIFIED [developers.naver.com/products/terms](https://developers.naver.com/products/terms/) (2026-09-07) |
| 한국수출입은행 FX API | GO | Free key, 1,000 calls/day, KRW rates about 11:00 on business days. Replaces open.er-api.com, unreachable from this environment. | VERIFIED [koreaexim API](https://www.koreaexim.go.kr/ir/HPHKIR020M01?apino=2&viewtype=C); [data.go.kr](https://www.data.go.kr/data/3068846/openapi.do) (2026-04-30) |

### 1d. Logistics

| Option | Verdict | Why | Key source |
|---|---|---|---|
| AliExpress lines to Korea (Cainiao / AliExpress Standard / Choice; CJ대한통운 last leg) | GO for 구매대행 (mode A) | Chosen per order; cost and days come from the AliExpress freight API; reported 7-15 days Standard, 21-40 Super Economy, Choice within 5 days. | VERIFIED [CJ O-NE](https://www.cjlogistics.com/ko/newsroom/news/NR_00001035) (2023-03-15); REPORTED line timings |
| Malltail Weihai forwarding | CONDITIONAL (mode B) | Air from $10.77 per 0.5 kg, $10 business-clearance fee. | VERIFIED [price list](https://post.malltail.com/services/price_list/CN/KR/KR) |
| Hanjin 원클릭 / CJ 소호 contract | CONDITIONAL (mode B) | No-contract ₩4,500 falling to ₩2,650; CJ contract ₩2,990 at 30+ boxes/month, individuals excluded. | VERIFIED [CJ 소호](https://m.logii.com/Logii_Taekbae/BizCompany.asp); REPORTED Hanjin |
| Coupang Rocket Growth | CONDITIONAL (mode B, later) | Korean stock, 한글표시사항 mandatory from 2026-01-01 (reported), KC for electronics/children's goods. | VERIFIED [rocket-growth](https://marketplace.coupang.com/rocket-growth) |
| Naver N배송 / NFA | later | Through a partner WMS, not a Naver API for us. | REPORTED |

---

## 2. Recommendation: first channel and first supplier

**First sales channel: Naver Smart Store, as a 사업자 판매자.** Evidence: lower take (about 6.63% for a new
business versus Coupang's 9-11% plus VAT plus ₩55,000/month), faster cash (order end + 1 business day versus
Coupang's 70/30 split about 15 business days after the week), a free self-service Commerce API that returns
the buyer's customs code, and no monthly fee. Coupang is the second channel once the first products prove out:
its API is complete and needs no approval, but its refund policies (셀프/보장/직권환불), seller score and
slower settlement hit overseas-sourced goods hardest. Both channels require 사업자등록 (Naver since 2026-06-24
for overseas goods; Coupang always).

**First supplier: AliExpress, through the Affiliate API for discovery and a Dropshipping app for buyer
prices, freight quotes and orders.** It is the only supplier whose own terms and documentation support
selling its goods on another marketplace. Temu sourcing is not approved under its consumer terms. 1688 and
Alibaba.com are stock models for replenishment later.

**First business model: 구매대행 (mode A below).** The Korean customer is the importer of record, the parcel
ships from the AliExpress seller to the customer, and the company earns a fee. This is the only model that
uses the USD 150 personal-use exemption lawfully, keeps VAT on the fee only, and needs no stock capital.
Stocking goods in Korea (mode B) is a later step for proven products.

---

## 3. Import modes the operating core must distinguish

Korea Customs Service (관세청) on resale goods, VERIFIED on the page the owner supplied
([상담사례 idx=133](https://www.customs.go.kr/call/ad/crmcc/selectIssueView.do?idx=133&mi=6828), undated):
"판매를 목적으로 하는 물품을 구입한다면, 구입금액에 상관없이 수입신고하여 관련 제세를 납부하고 수입요건을
득해야 합니다", and the USD 150 exemption exists only because the goods are "국내거주자인 개인이 자가사용할
물품으로 인정되었기 때문". A second 관세청 answer (VERIFIED,
[2024-08-26](https://www.customs.go.kr/call/ad/crmcc/selectBoardView.do?mi=6827&cnslAcapSrno=3391992)):
"판매를 위한 물품 및 사업장에서 사용하는 물품은 금액과 상관없이 사업자(개인사업자 포함) 명의로 수입 …
정식 수입통관 절차를 이행".

| | **Mode A: 구매대행 (personal-use parcel)** | **Mode B: commercial resale (stock import)** | **Mode C: genuine sample** |
|---|---|---|---|
| Importer of record | The Korean customer, with their own 개인통관고유부호 | The business (사업자 명의) | The business |
| Declaration route | 목록통관 when goods ≤ USD 150 (≤ USD 200 from the US) and not on the exclusion list; otherwise 간이수입신고 (USD 150-2,000) or 일반수입신고 | 일반수입신고 regardless of amount, via UNIPASS or a 관세사; 수입요건 (KC, 식약처 등) must be met | Declared; duty exemption possible under 관세법 시행규칙 제45조①3 for goods "과세가격 미화 250달러 이하 … 견본품으로 사용될 것으로 인정되는 물품" (text seen only on secondary sites; law.go.kr unreachable → UNKNOWN until confirmed) |
| Duty and VAT | None up to the threshold. Above it the **whole** value (goods + international freight + insurance) is taxed: duty (간이세율 by category; 기본관세 8% common) then VAT 10% on value + duty | Duty by HS code on CIF value (8% basic for many goods; 0% for ITA electronics; FTA rates only with origin proof) then VAT 10%; import VAT is creditable input VAT | If accepted as a sample: duty exempt; VAT still per customs decision. Unknown → not zero |
| Exclusions from the exemption | 12 categories excluded from 목록통관 (의약품, 건강기능식품, 식품·주류·담배, 기능성/태반/스테로이드 화장품, 방송통신기자재(전파법), 검역대상, 지재권 의심 등); 합산과세 when one waybill is split or same-day purchases from the same seller are split under the threshold; 반복·분할 수입 | No exemption at all | A sample later resold is not a sample |
| Certification | KC: unmarked 안전인증/안전확인 goods may not be 구매대행-ed except 시행규칙 별표 13 items; 어린이제품 without KC banned outright; 전파법: one unit per person for personal use with the required notice; food and cosmetics need 식약처 registrations | Certification in the business's own name; no 전파법 1대 exemption (법제처 해석 21-0097, 2021-05-12: resale of an exempt unit needs 적합성평가) | 전파법 시장조사 up to 3 units (RRA) |
| VAT accounting | VAT base = agency fee only, when the customer pays goods, shipping, duty and fee itemised, clears under their own code and the seller holds no stock (국세청 guidance, 업종코드 525105) | VAT base = full sale price; 업종코드 525101 | Procurement expense, never revenue or profit |
| Customs registration | 구매대행업자 등록 with 세관 once prior-year 구매대행 import value reaches ₩1,000,000,000 (관세법 §222①7; fine up to ₩20,000,000); joint tax liability when the agent collects duty and gives false price information, widened by the 2026 amendment (reported) | 사업자통관고유부호 | — |
| Sources | VERIFIED [법제처 easylaw](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=1504&ccfNo=3&cciNo=1&cnpClsNo=2) (2026-08-15); [목록통관 배제](https://www.customs.go.kr/kcs/cm/cntnts/cntntsView.do?mi=2821&cntntsId=819); [합산과세](https://www.customs.go.kr/kcs/na/ntt/selectNttInfo.do?mi=2891&nttSn=10069842&nttSnUrl=search); [국세청 525105](https://nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=40574&cntntsId=239004); [구매대행업자 등록](https://www.gov.kr/mw/AA020InfoCappView.do?CappBizCD=12200000398); [KC 구매대행](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=1504&ccfNo=2&cciNo=2&cnpClsNo=2); [RRA FAQ](https://www.rra.go.kr/ko/notice/D_e_faq2_1.do?fa_type=e&fa_category=compt) | VERIFIED 관세청 answers above; [법제처 해석 21-0097](https://www.moleg.go.kr/lawinfo/nwLwAnInfo.mo?mid=a10106020000&cs_seq=426749) | REPORTED [시행규칙 제45조 text](https://www.lawnb.com/Info/ContentView?sid=L000025FA75B2C31_45); VERIFIED [RRA 시장조사](https://www.rra.go.kr/ko/popup/popup_100430.jsp) |

Rules that follow (INFERRED from the verified facts):

1. The USD 150 (USD 200 US) exemption applies **only in mode A**, per parcel, per customer, when the category is
   not excluded and the parcel is not part of a split or same-day repeat. It never applies to goods the business
   imports for resale, whatever the value.
2. In mode A the seller does not pay the duty; the customer does. A listing must say so. The seller must still
   know whether a parcel will exceed the threshold, because a customer who is surprised by a tax bill returns
   the goods (7-day 청약철회 is unconditional).
3. Unknown HS classification or rate must produce "tax unknown", never a verified zero.
4. A 개인통관고유부호 belongs to the customer, is personal data, is collected by the marketplace, is deleted by
   Naver when the order ends, and must never be reused. From 2026 codes expire yearly.

---

## 4. The three pricing assumptions in `src/arbitrage`, resolved

| Assumption in the code today | Finding | Requirement |
|---|---|---|
| `pricing.landed_cost` waives duty and VAT below `duty_free_usd = 150` for every `cross_border` offer | Correct only for mode A parcels to a personal-use customer in a non-excluded category (section 3). Wrong for stock imports, samples that are resold, excluded categories, split shipments. | `landed_cost` takes an explicit import mode. Mode A: duty 0 below the threshold only when the category is not excluded and the customer is the importer; the note must say the customer pays duty above it. Mode B: duty by rate table (or "unknown") plus VAT on every unit. Mode C: expense, no margin. Regression: a commercial-resale offer at USD 120 must **not** get the exemption. |
| `sources/aliexpress.py` sets `shipping = default_shipping` = 0 (`default_shipping_krw = 0` in `default.toml`) because `aliexpress.affiliate.product.query` returns no shipping | Shipping is never zero by default. Per-product cost and days are available from `aliexpress.affiliate.product.shipping.get` (Affiliate group), `aliexpress.ds.freight.query` and `aliexpress.logistics.buyer.freight.calculate` (DS group, buyer token). Choice items carry a per-item ₩1,300 fee since 2024-06-03 and "free shipping" thresholds are promotional (REPORTED). | An offer without a freight quote is **unpriced**: no landed cost, no quote, not an opportunity. The scan must call the freight API (or read a `shipping` column in CSV) before pricing. |
| `scanner.evaluate` prices Coupang from the Naver Shopping `market_low`, with one `fee_rate = 0.1188` | Coupang exposes no price search to non-partners; the only lawful feed is the Coupang Partners search API (10 calls/hour, approval-gated). Coupang commission is 4-10.9% **by category** plus 10% VAT on the commission plus ₩55,000/month above ₩1,000,000 sales. | A Coupang quote built from a Naver price is labelled `reference_price_source = "naver"` and `viable = false` until a Coupang price is recorded (Partners API or a manual check with a URL and date). Coupang fee comes from the category, not one number. |
| (new) `sources/naver_shopping.py` relies on the Naver Developers 쇼핑 search API | **The service ended 2026-07-31** (terms 2026-09-07, 부칙 제2조③). Its terms never permitted storing or reselling results. NAVER API HUB has no product search. | Every `market_low` from this source is unverifiable from 2026-08-01. No opportunity is "executable profit" until a licensed Korean price source exists (manual checks with URL and date, Coupang Partners spot checks, a data vendor, or our own sales history). Scraping Naver Shopping is not an option. |

---

## 5. Korean requirements before the first sale

| # | Requirement | Rule and source | Status |
|---|---|---|---|
| 1 | **사업자등록** at 홈택스 within 20 days of starting; 업종코드 525105 (해외직구대행업) for mode A, 525101 when holding stock; 간이과세자 while prior-year supply < ₩104,000,000 | VERIFIED [easylaw](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=25&ccfNo=2&cciNo=1&cnpClsNo=1); [국세청 FAQ 525105](https://www.nts.go.kr/nts/na/ntt/selectNttInfo.do?nttSn=1322104&mi=40580) (2023-03-08); [간이과세 threshold](https://www.korea.kr/news/policyNewsView.do?newsId=148930428) | Not done (owner) |
| 2 | **통신판매업 신고** at 정부24 with the 구매안전서비스 이용확인증 (printable from the Naver seller center even during review); exempt below 50 transactions or as 간이과세자, but Naver requires the number at 50 구매확정 and Coupang asks for it at signup (waived for 간이과세자 since 2026-06); 등록면허세 ₩12,000-40,500 a year (reported) | VERIFIED [faqId=3664](https://help.sell.smartstore.naver.com/faq/content.help?faqId=3664); [Coupang 간이과세자](https://marketplace.coupang.com/information-center/kupang-panmaeja-gaib-ije-seoryu-junbi-eobsi-1bunimyeon-ggeut-feat-ganigwaseja-ibjeom-gansohwa); REPORTED [exemption criteria](https://view.asiae.co.kr/article/2020052110140895154) | Not done (owner) |
| 3 | **Storefront and listing disclosures** (전자상거래법 §10, §13): business identity and 신고번호; on each 구매대행 listing: that it is 구매대행, '해외' prefix (Naver), overseas 출고지, delivery period, that duty and VAT above the threshold are borne by the buyer, the 7-day 청약철회 and the real return-cost policy (공정위 fined 11 구매대행 sellers in 2015 for fake overseas return fees), exchange-rate note | VERIFIED [easylaw 표시의무](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=25&ccfNo=3&cciNo=1&cnpClsNo=1); [청약철회](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=25&ccfNo=3&cciNo=3&cnpClsNo=3); [공정위 2015](https://m.korea.kr/news/policyNewsView.do?newsId=156062404); [Naver '해외' prefix](https://help.sell.smartstore.naver.com/faq/content.help?faqId=17353) | Template needed |
| 4 | **Customs**: customer's 개인통관고유부호 on every order (collected by the marketplace; consent and deletion after use); parcel ≤ USD 150 per customer per day per seller unless the buyer accepts tax; excluded categories never in mode A | Section 3 sources; [PCC issuance](https://www.gov.kr/portal/service/serviceInfo/122000000014); [annual renewal from 2026](https://www.korea.kr/news/reporterView.do?newsId=148945198) (2025-07-02) | Enforced by the core |
| 5 | **Product gates** (record evidence per SKU, the keyword filter only triages): exclude 어린이제품 without KC, unmarked 안전인증/안전확인 electricals (except 별표 13), 의약품, 담배, 주류, 의료기기 without approval, standalone lithium batteries/power banks (not mailable), counterfeit goods; flag food/supplements (식약처 구매대행업 등록), cosmetics (책임판매업 수입대행형), Bluetooth/Wi-Fi/RF (전파법 one unit with notice), LED 등기구, 레이저, 헬멧 (high 2026 failure rates), branded goods (병행수입 check) | VERIFIED [KC tiers](https://www.kats.go.kr/content.do?cmsid=44); [어린이제품](https://www.kats.go.kr/content.do?cmsid=496); [RRA](https://www.rra.go.kr/ko/notice/D_e_faq2_1.do?fa_type=e&fa_category=compt); [식약처](https://www.mfds.go.kr/brd/m_824/view.do?seq=35125); [화장품](https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=1301&ccfNo=2&cciNo=2&cnpClsNo=2); [우체국 lithium](https://ems.epost.go.kr/front.Introduction04New.postal); [Coupang prohibited items](https://marketplace.coupang.com/information-center/blog-news7); UNKNOWN safetykorea.kr | Partly in PR #2 (triage only) |
| 6 | **Tax calendar**: VAT (간이과세자: by 1/25; 일반: 1/25 and 7/25 plus 4월/10월 고지); 종합소득세 in May; 현금영수증 for cash ≥ ₩100,000; keep platform invoices and card statements as 증빙; do not claim input VAT on goods in mode A | VERIFIED [VAT dates](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=2273&cntntsId=7694); [현금영수증](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7796); [국세청 525105 guidance](https://nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=40574&cntntsId=239004) | Ledger rule |
| 7 | **Customs registration** as 구매대행업자 once prior-year import value reaches ₩1,000,000,000 | VERIFIED [정부24](https://www.gov.kr/mw/AA020InfoCappView.do?CappBizCD=12200000398) | Later |

---

## 6. Shortest eligible path to one real customer sale

Mode A on Naver Smart Store, sourced from AliExpress. Every step marked **owner** needs the owner's own
identity, signature or money; nothing is spent or connected until the mandate and accounts exist.

| Step | Who | What | Depends on |
|---|---|---|---|
| 1 | owner | 사업자등록 at 홈택스 (개인사업자, 간이과세, 업종 525105 해외직구대행업) | — |
| 2 | owner | Naver Smart Store signup as 사업자 판매자: 사업자등록증, 사업자등록증명원, 통장사본, phone verification; review 3 business days | 1 |
| 3 | owner | In 판매자정보 › 상품판매권한 신청: consent to the 해외상품판매 terms (instant); print the 구매안전서비스 이용확인증 | 2 |
| 4 | owner | 통신판매업 신고 at 정부24 with that certificate; enter the number in the seller center (mandatory at 50 구매확정, required by Coupang at signup) | 3 |
| 5 | owner | Own 개인통관고유부호 at UNIPASS (for samples) and a 사업자 명의 card with low overseas fees for supplier payment | 1 |
| 6 | owner | AliExpress: buyer account, activate the Dropshipping Center and accept the Business Program agreement; Portals affiliate account; two Open Platform developer profiles (Affiliates app, Dropshipping app), each approved with a written reason (1-2 business days reported) | — |
| 7 | owner | 커머스API센터 account (통합매니저), one 내스토어 애플리케이션 with the fixed IPv4 of the server; Koreaexim FX key | 2, a fixed IP |
| 8 | core | Register the credentials by name only; verify one read-only call per API (AliExpress product query, freight quote; Naver token; Koreaexim rate) and flip the registry entry to `sandbox` or `live` in a PR that records the call | 6, 7 |
| 9 | core | Pick 1-3 products that pass the gates in section 5 (no KC/전파법/food/cosmetics exposure), landed cost priced with a real freight quote, Korean reference price checked by hand with URL and date, priced for ≥ 15% net after Naver fees | 8, licensed price check |
| 10 | owner | Optional sample order (mode C, procurement expense) to check quality and delivery days; it is an expense, not profit | mandate |
| 11 | core | List on Naver with overseas 출고지, '해외' prefix, 구매대행 disclosures, correct 발송기한 | 9 |
| 12 | core → owner | On the first order: read the customs code from the order API, place the AliExpress order to the customer's address (payment by the owner until API payment is bound), enter the tracking number within the 3-business-day window (CH1 기타택배), handle the 15-business-day tracking rule | 11, mandate for the supplier payment |
| 13 | core | Reconcile: Naver settlement (order end + 1 business day) against the supplier charge, fees, FX and a returns reserve; profit is recognised only on settled cash | 12 |

Minimum calendar time (INFERRED): about two weeks, dominated by 사업자등록, Naver review (3 business days),
통신판매업 신고 and the AliExpress app approvals.

---

## 7. Exact accounts, registrations and credentials the owner must supply

| Item | Where | Credential name(s) in the registry | Needed for |
|---|---|---|---|
| 사업자등록번호 | 홈택스 | `BUSINESS_REGISTRATION_NUMBER` | every marketplace, 세금계산서 |
| 통신판매업 신고번호 | 정부24 / 구청 | `MAIL_ORDER_REGISTRATION_NUMBER` | Naver (at 50 orders), Coupang signup |
| Naver Smart Store seller account (사업자, 해외상품판매 consent) | sell.smartstore.naver.com | — | listing |
| Naver Commerce API app | apicenter.commerce.naver.com | `NAVER_COMMERCE_CLIENT_ID`, `NAVER_COMMERCE_CLIENT_SECRET` (+ fixed IPv4) | orders, listing, customs code, settlement |
| AliExpress buyer account with DS Center activated | aliexpress.com | — | dropship orders |
| AliExpress Dropshipping app | openservice.aliexpress.com | `ALIEXPRESS_DS_APP_KEY`, `ALIEXPRESS_DS_APP_SECRET`, `ALIEXPRESS_DS_ACCESS_TOKEN`, `ALIEXPRESS_DS_REFRESH_TOKEN` | buyer price, freight, order, tracking |
| AliExpress Portals + Affiliates app (separate account) | portals.aliexpress.com, openservice.aliexpress.com | `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_APP_SECRET`, `ALIEXPRESS_TRACKING_ID` (already in `.env.example`) | discovery feed |
| PayPal bound to the DS account (only if API payment is wanted) | paypal.com | — | `try_to_pay` |
| 사업자 명의 card for supplier payments | bank | — | manual checkout |
| Korean fixed IPv4 (Cafe24 VPS ₩9,000/month, AWS Seoul, Oracle free tier) | hosting | — | Naver and Coupang API whitelists |
| 한국수출입은행 FX key | koreaexim.go.kr | `KOREAEXIM_API_KEY` | landed cost |
| Owner's 개인통관고유부호 | UNIPASS | (not stored) | samples only |
| Later: Coupang WING account and API key | wing.coupang.com | `COUPANG_VENDOR_ID`, `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY` | second channel |
| Later: Coupang Partners key (after approval) | partners.coupang.com | `COUPANG_PARTNERS_ACCESS_KEY`, `COUPANG_PARTNERS_SECRET_KEY` | Coupang price spot checks |

Retired: `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` (Naver Developers 검색 API) no longer give shopping data.

---

## 8. Requirements for the operating core (to enforce or record)

1. **Import mode is a required field** on every offer, order and ledger line: `personal_use_agent` (A),
   `commercial_resale` (B) or `sample` (C). Missing mode fails closed (no price, no order).
2. **Duty and VAT**: mode A applies the USD 150/200 exemption per parcel only when the category is not on the
   목록통관 exclusion list and the parcel is not a split or same-day repeat; above the threshold the whole
   value is taxed and the customer pays. Mode B taxes every unit by an explicit rate or marks the cost
   "unknown". Mode C books an expense. Unknown classification never yields a verified zero.
3. **Landed cost requires a freight quote** from the AliExpress freight API (or an explicit CSV column). No
   zero default.
4. **Channel-specific fees**: Naver 3% (or 1% with own-link attribution) + Npay by NTS grade (3.63% for a new
   business) on product and shipping amounts; Coupang by category + 10% VAT + ₩55,000/month amortised;
   settlement timing per channel as in section 1b.
5. **Market prices** need a source, URL and date. Naver Developers 쇼핑 API data is not licensed after
   2026-07-31; anything derived from it is "reference, unverified". A Coupang quote built on a Naver price is
   not viable until a Coupang price is recorded.
6. **Eligibility evidence per SKU** (certificate number or exemption basis, category not excluded) is a
   precondition for listing; the keyword compliance filter is triage only.
7. **Customs code handling**: read from the marketplace order, use once for that order, do not persist beyond
   the order, never reuse the owner's code for a customer.
8. **Registry discipline**: an integration becomes `sandbox`/`live` only in a PR that names the verified
   operation and date; credentials by name only.
9. **Profit recognition**: only on settled cash (Naver order end + 1 business day; Coupang 주정산/월정산 dates)
   net of supplier charge, fees, FX and a returns reserve; the KRW 1,000,000 target is measured on reconciled
   net profit, never on price gaps, demo sales or samples.
10. **No spend** until the mandate (limits, funding, payout) and the accounts above exist; samples count as
    procurement expenses within that mandate.

---

## 9. What was verified, inferred, and not reached

- **Verified on official pages**: Temu KR/global terms, shipping, returns, payment, affiliate pages and the
  Partner Platform terms; AliExpress Terms of Use, DS agreement, dropshipping guide, API docs, affiliate
  agreement, buyer protection; Coupang registration, fee, settlement, 구매대행 listing, API key, rate-limit and
  prohibited-item pages; Naver seller FAQs (eligibility, fees, settlement, listing rules, API), Commerce API
  auth and rate-limit docs, and the Naver Developers terms; 법제처 easylaw, 관세청 answers and lists, 국세청,
  정부24, 국표원, RRA, 식약처, 법제처 해석, 한국수출입은행, CJ, Malltail, Cafe24, Toss Payments, ESM PLUS, 11st.
- **Reported only**: Coupang 주정산 percentages and days, Coupang overseas return-fee caps, Temu local-seller
  requirements and settlement, AliExpress shipping-line timings and the ₩1,300 Choice fee, affiliate commission
  rates, 1688 payment and API access, 11st and Gmarket fee levels, 등록면허세 amounts, 관세법 시행규칙 제45조
  wording, the 2026 customs amendment on 구매대행업자 liability, Hanjin rates.
- **Inferred**: the ten rules in section 8, the mode table's "rules that follow", the two-week calendar, the
  recommendation itself.
- **Unknown (not reached)**: Temu buyer-purchasing API existence and Temu seller API scopes and hosts; Temu
  local-seller commission; AliExpress Portals commission tables; the Korean field for the customs code in
  `ds.order.create` (needs a test order); Naver's auto-구매확정 day table (image); Coupang's own consumer
  return-policy page; safetykorea.kr and ftc.go.kr guideline pages; law.go.kr article bodies.
