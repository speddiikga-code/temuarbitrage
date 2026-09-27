# First transaction: sample order sheet and the path to the first sale

Written 2026-09-27 (UTC) by the "Make the first transaction" thread. Task 12 in [TASKS.md](../../TASKS.md).

Everything here is **research and a purchase plan**. Nothing has been bought. The sample is a
**procurement expense in import mode C (genuine sample)**, never inventory and never profit. Every price
below is an observation with a source and a time; the checkout price, the freight quote and the delivery
promise are confirmed on the AliExpress order page by the owner before paying. No figure in this file is
executable profit.

**Result of the skeptic check (section 8):** none of the three shortlisted items has a verified price gap
against the Korean market. The pet sling bag is refuted on market economics (domestic generic sling bags
sell at ₩8,280-9,370 before shipping, and 구매대행 listings of the same type already exist). So the sample
below is a **process-validation order**: it buys the first real supplier transaction, the real freight, the
real delivery days and a real customs clearance for about ₩10,000, and it produces the first ledger entry.
It does not buy a product to list. Product selection continues separately.

Related: [docs/platform_eligibility.md](../platform_eligibility.md) (PR #4) for the go/no-go matrix,
import modes and the credentials checklist; the compliance filter (PR #2); the pricing math in
`src/arbitrage/pricing.py`.

---

## 1. The sample: small-pet sling carrier bag (강아지·고양이 슬링백), process-validation order

| Field | Value | Source / status |
|---|---|---|
| AliExpress listing | https://www.aliexpress.com/item/1005006887446144.html | Product id 1005006887446144 |
| Listing title (KR) | 편안한 강아지 가방 애완동물 크로스바디 숄더백 야외 여행 휴대용 고양이 강아지 슬링 캐리어 가방 | as shown on the search card |
| Price shown to Korea | **₩9,160** (promo price on the search card); seller list price ₩8,950 | AliExpress public search, ship-to KR, KRW, observed 2026-09-27 11:16 and 11:18 UTC (`observed_aliexpress.csv`) |
| Orders / rating / program | 3,728 orders, 4.7 stars, **Choice** (platform-managed shipping) | same observation |
| Shipping to Korea | **not observed** (product pages are captcha-walled from the research container). Choice items ship free above a threshold reported as about ₩10,000; below it a fee reported as ₩1,300 applies. Read the exact amount at checkout. | reported, unverified |
| Delivery estimate | Choice to Korea is reported at 5-10 calendar days; read the date promised at checkout | reported, unverified |
| Quantity | **1 unit** (one colour; pick the colour shown in the most reviews). A second unit only if the listing offers two sizes and the owner wants to compare them. | decision |
| Expected charge | ₩9,160 + freight (₩0-1,300 expected) = **about ₩9,200-10,500**, billed in KRW by AliExpress at its own rate; the card statement is the ledger amount | estimate |
| Customs | Parcel value about USD 7-8, far under the USD 150 personal-use limit. The owner enters their own 개인통관고유부호 at checkout. Import mode **C (sample)**: the unit is for inspection and listing photos and is **not sold**. | rule, see PR #4 section 3 |
| What this unit is for | Prove the path (order, payment, freight, delivery days, 목록통관 clearance, packaging) and produce the first ledger entry. The unit is inspected and kept; it is **not resold**: a parcel cleared duty-free as 자가사용 may not legally be sold (관세법 제269조·제270조, section 8). | purpose |

### Why this item for the process test

- **Compliance is clear** (skeptic check, section 8): a fabric pet carrier is not on the KATS
  안전기준준수대상 생활용품 list, not 안전인증/안전확인/공급자적합성, not an 어린이제품, no battery, no radio, not
  food-contact. Nothing in the parcel can be held at customs for a certificate.
- **Consistent supplier price**: promo ₩9,160 vs list ₩8,950, so the checkout price is unlikely to jump (the
  golf and laptop-stand candidates show a 2-5x gap between promo and list price, which only the order page can
  resolve). Cheap enough that the whole test costs about ₩10,000.
- **Sound listing**: top result by orders for two different queries, 3,728 orders, 4.7 stars, Choice, on sale
  since 2024-04; the skeptic found no better alternative listing.
- Light (about 300 g), soft, unbreakable, colour variants only (sizes not verified; pick the default SKU).

**Why not a product to list**: the Korean market low for a generic sling bag is ₩8,720 (레드퍼피 on Coupang) and
the most comparable generic item is ₩9,370 + ₩3,000 shipping across 50 malls; the branded tier at
₩16,800-19,800 competes on next-day delivery and reviews, which a 10-15 day 구매대행 listing cannot match.

### Runner-ups (kept in `observed_*.csv`)

| Candidate | AliExpress promo / list (KRW) | Korean comparables (KRW) | Why not first |
|---|---|---|---|
| Golf head-cover set, PU leather, driver+fairway+hybrid (1005009012434425; 448 orders, 4.9, Choice) | 7,400 / 16,446 | HACC 3-piece set 12,350 (1 mall); 스포틴 3종 36,000; 덱스골프 스컬 3종 54,910 (39 malls); single 겜프 driver cover 9,120 (282 malls) | Promo and list price differ 2.2x; margin only exists if the checkout price is near the promo. Good second sample. |
| Foldable aluminium laptop stand (1005007562753306; 22,677 orders, 4.7, Choice; alt 1005011940143389 at 5,581 list) | 1,750 / 8,837 | 컴튜 N8 9,900 (4 malls); NEXTU NBS5705 13,500 (106 malls); 감성공장 18,500; AOC L2 19,380 | Korean market is crowded at ₩9,900-13,500; against the list price the margin is negative. |
| Self-cleaning cat brush (1005007540006670; 14,625 orders, 4.9, Choice) | 1,000 / 4,136 | 6,000-9,400 (Coupang, 지그재그 snippets); 라무달리 14,840 | Absolute profit under ₩1,500 per order. |
| Hanging toiletry bag (1005006220525619; 29,068 orders, 4.7, Choice) | 1,500 / 7,565 | 8,710 (snippet); 라일리 10,310-11,460 (88 malls) | Headroom 1.2-1.4x only. |

Dropped for compliance or logistics, with the observation kept in the CSVs: silicone kitchen tongs
(food-contact: 수입식품 구매대행업 registration), shower heads (KC 위생안전), umbrellas, cable boxes, pilates
rings, bike phone mounts (Korean prices at or below AliExpress), trunk organisers and camping tables (bulky),
branded goods (UGREEN, Baseus, TARKA).

---

## 2. Unit economics, three customs modes (reference only, not executable profit)

Computed with the repo's `arbitrage.pricing` (no re-implemented fee math): landed = (item + freight) x 1.03
FX buffer; Naver fee 6.63%, Coupang 11.88%, ads 10%, returns 3%, target margin 15%. Live FX 1 USD = ₩1,357.05
(open.er-api.com, 2026-09-27). Coupang figures are built on Naver reference prices and are **reference only**
(PR #4 rule 4).

| Scenario | Item | Freight | Landed | Sell at | Naver profit (margin) | Coupang profit (margin) | Naver min. viable price |
|---|---|---|---|---|---|---|---|
| **A 구매대행**, Choice free shipping, sell at the branded-tier low | ₩8,950 | ₩0 | ₩9,219 | ₩16,800 | ₩4,283 (25.5%) | ₩3,401 (20.2%) | ₩14,200 |
| A, sell at the skeptic's comparable generic delivered price | ₩8,950 | ₩0 | ₩9,219 | ₩12,300 | ₩666 (5.4%) | -₩117 | ₩14,200 |
| **B commercial resale** (stock import; 8% duty placeholder + 10% VAT, no exemption) | ₩8,950 | ₩0 | ₩10,902 | ₩16,800 | ₩2,600 (15.5%) | ₩1,718 (10.2%) | ₩16,700 |
| A, worst case: promo price, ₩3,000 freight, undercut to ₩14,900 | ₩9,160 | ₩3,000 | ₩12,525 | ₩14,900 | -₩550 | -₩1,332 | ₩19,200 |
| **C sample** (this order) | ₩9,160 | at checkout | about ₩9,200-10,500 | not sold | expense | expense | — |

Reading: the product clears the 15% target in mode A only if Choice shipping is free and the listing sells
at the branded tier (about ₩16,800 or more) while generic domestic stock sells at ₩8,720-12,370 delivered.
The skeptic judged that gap absent (section 8), so no listing is planned from this sheet. Mode B is marginal on
Naver and fails on Coupang. The tariff in mode B is a placeholder; the HS code and rate are **unknown, not
zero**. What the sample order does answer: the real freight, the real delivery time and how a China parcel
under USD 150 clears, which every later product needs.

---

## 3. Korean market evidence (observed 2026-09-27, `observed_korea_market.csv`)

| Listing | Price | Malls | Source |
|---|---|---|---|
| 라일리 Rly 반려동물 이동 가방 강아지 고양이 슬링백 501 | ₩16,830 | 9 | Danawa search "강아지 슬링백", 11:10 UTC |
| 라일리 Rly 501720 이동 강아지 고양이 가방 슬링백 | ₩17,010 | 9 | same |
| 제이에스글로벌 TBZ 탈출금지 애견 메쉬 슬링백 | ₩19,350 | 5 | same |
| 라일리 Rly 강아지 반려견 이동 산책 외출 슬링백 숄더백 | ₩26,610 | 9 | same |
| 한샘몰 애착 슬링백 강아지가방 | ₩25,900 | 1 | web search snippet (store.hanssem.com), 11:19 UTC |
| **레드퍼피 모던슬링백 그레이(중형)** | **₩8,720** | 6 | Danawa pcode 33161168, Coupang price, skeptic check 11:22 UTC |
| 대도 강아지 애완견 이동가방 슬링 | ₩8,280 (옥션, free shipping) | 3 | Danawa pcode 39958487, skeptic check 11:22 UTC |
| 셀러허브 강아지 이동가방 슬링백 포대기 S42288714 | ₩9,370 + ₩3,000 shipping | 50 | Danawa pcode 107735954, domestic stock, registered 2026-03, skeptic check 11:22 UTC |
| 코스트몰 강아지슬링백 (11st 3458075914) | ₩18,450 (regular ₩21,120, free shipping) | 1 | 11st product page, skeptic check |

Danawa mostly lists catalogued items; small Smart Store sellers, including other 구매대행 sellers offering
the same AliExpress item, can be cheaper and are not fully visible from the research container (naver.com
and coupang.com are blocked). The skeptic check found several '[해외]' 구매대행 sling-bag listings registered
on Danawa in August and September 2026 (prices not shown), so the niche is already occupied. **Before listing, check the
Naver price by hand with URL and date** (the Naver 쇼핑 검색 API ended 2026-07-31; the scanner has no
licensed market source).

---

## 4. Inspection checklist on arrival

1. Photograph the parcel, the customs label and the invoice before opening; note the delivery date and the
   number of days from payment.
2. Confirm the customs route on the tracking page (목록통관 expected; no tax expected under USD 150).
3. Compare with the listing: dimensions, strap length, buckle and zipper type, mesh window, inner safety
   hook, pocket layout, colour, and the weight of the bag itself.
4. Load test: a 5 kg bag of rice on the strap for ten minutes; check seams, buckle and hook.
5. Smell and finish: strong chemical smell, loose threads, glue marks, print defects.
6. Wash test: one hand-wash cycle, check colour bleed and shape.
7. Packaging: is it presentable enough to ship straight to a customer in mode A, or does the listing need to
   say "simple packaging"?
8. Shoot the owner's own photos (the listing must not reuse the supplier's copyrighted images without
   permission) and write down the exact spec for the Korean listing.
9. Record the actual delivery days and the total charged; update the ledger entry.

---

## 5. Ledger entry (post once the owner pastes the order number)

Mode C sample, funded from **initial capital**, booked as a product-validation expense. Never inventory, never
COGS, never revenue. Fill the bracketed values from the AliExpress order page and the card statement.

```jsonc
{
  "entry_type": "procurement_expense",
  "import_mode": "C_sample",
  "funding": "initial_capital",
  "counterparty": "AliExpress seller of item 1005006887446144",
  "reference": { "aliexpress_order_no": "[order number]", "ordered_at": "[ISO time]", "paid_by": "owner card, owner-approved" },
  "lines": [
    { "debit": "expenses:product_validation_samples", "credit": "assets:cash:owner_card", "amount_krw": "[total charged on the card statement]",
      "memo": "1 x pet sling carrier bag, item [price at checkout] + freight [freight at checkout], AliExpress KRW billing" }
  ],
  "evidence": ["order page screenshot", "card statement line", "tracking number", "customs clearance status"],
  "customs": { "declared_value_usd": "[from order]", "personal_customs_code": "owner's own code, entered at checkout, not stored here", "tax_paid_krw": 0, "tax_status": "expected 목록통관 (자가사용, 물품가격 under USD 150, 관세법 시행규칙 제45조 제2항); confirm on the tracking page; unit may not be resold" },
  "follow_up": { "delivered_at": null, "delivery_days": null, "inspection": "docs/first_transaction/README.md section 4", "resale_allowed": false }
}
```

---

## 6. Verification status (what was checked, what was not)

- **Checked**: AliExpress search-card prices to Korea in KRW (about 50 queries, 588 listings recorded);
  Danawa lowest prices (about 50 queries, 589 listings recorded); web-search snippets for Coupang, 11st,
  brand-shop prices; live FX. Files: `observed_aliexpress.csv`, `observed_korea_market.csv`.
- **Not reachable from the research container**: AliExpress product pages (captcha), naver.com, coupang.com,
  customs.go.kr, korea.kr, safetykorea.kr. So the checkout price, freight and delivery promise are read by the
  owner on the order page, and the Naver price is checked by hand before listing.
- **How the prices were read**: a small script fetched the public search pages at low volume (one request
  per query, 1.5 s apart). AliExpress's terms restrict automated access, so the script is not part of the repo;
  the operating core uses the Affiliate and Dropshipping APIs (PR #4 section 2). The Danawa fetch is likewise
  one-off research.
- **Skeptic checks** (one per shortlisted item: market low, supplier listing, compliance, return risk) and
  the sourced customs summary are in section 8. Still running at the time of writing: the safety-scope summary
  and the channel-operations summary; they are appended when they finish.

---

## 7. From this sample to the first customer sale (Naver Smart Store, mode A)

The full path with sources is PR #4 section 6. Condensed, with what only the owner can do marked **owner**:

| # | Step | Who | Notes |
|---|---|---|---|
| 0 | Place this sample order (today) | **owner** pays; a Remote Control session fills the order up to the payment step | needs only an AliExpress buyer account, a card and the owner's 개인통관고유부호 |
| 1 | 사업자등록 (홈택스, 개인사업자, 간이과세, 업종 525105 해외직구대행업) | **owner** | Naver's overseas-product selling rights are 사업자-only since 2026-06-24 |
| 2 | Naver Smart Store seller signup as 사업자 (사업자등록증, 통장사본, phone check; about 3 business days) | **owner** | |
| 3 | 판매자정보 › 상품판매권한 신청: consent to 해외상품판매; print the 구매안전서비스 이용확인증 | **owner** | instant |
| 4 | 통신판매업 신고 at 정부24 with that certificate; enter the number in the seller center | **owner** | required by Naver at 50 구매확정, by Coupang at signup |
| 5 | Sample arrives: inspection (section 4), own photos, final spec, hand-checked Naver price with URL and date | thread | decides go / no-go for listing |
| 6 | List on Naver: '해외' prefix, overseas 출고지, 구매대행 disclosures (delivery period, duty above USD 150 on the buyer, 7-day 청약철회, real return cost), price at or above the Naver minimum viable price (section 2) | thread drafts, **owner** publishes | listing copy is task 5 |
| 7 | First order: read the buyer's 개인통관고유부호 from the order, place the AliExpress order to the buyer's address, enter the tracking number within 3 business days | thread prepares, **owner** pays until the mandate allows API payment | mode A: the buyer is the importer |
| 8 | Buyer receives, 구매확정, Naver settles one business day after order end; reconcile settlement against the supplier charge, fees, FX and a returns reserve | core | profit is recognised only on settled cash |

Calendar: about two weeks, dominated by 사업자등록, Naver review and 통신판매업 신고. The sample (step 0) can
be ordered today and arrives while the registrations run.

Owner-only items, in one list: 사업자등록번호; Naver Smart Store seller account with the 해외상품판매 consent;
통신판매업 신고번호; AliExpress buyer account (and later the Dropshipping Center and the two Open Platform apps);
a card in the owner's or business's name for supplier payments; the owner's own 개인통관고유부호 for samples;
the mandate values (capital, per-transaction and daily limits, reserves); later a fixed Korean IPv4 for the
Naver Commerce API.

---

## 8. Appendix: skeptic and rules results (2026-09-27, about 11:21-11:24 UTC)

### 8.1 Pet sling carrier bag (1005006887446144): refuted on market economics, high confidence

- Market: revised market low ₩8,720 (레드퍼피 모던슬링백, Coupang, Danawa pcode 33161168); 대도 애견 슬링 ₩8,280
  on 옥션 with free shipping (pcode 39958487); 셀러허브 강아지 이동가방 슬링백 포대기 ₩9,370 + ₩3,000 shipping on 50
  malls (pcode 107735954, domestic stock, registered 2026-03); typical price ₩17,000 (라일리 Rly ₩16,830 on 9 malls,
  11st 코스트몰 ₩18,450, Coupang ₩19,800). Ratio to the AliExpress card price: 0.95 on the floor, 1.35 on the
  delivered generic price, both under the 1.5 rule. '[해외]' 구매대행 sling-bag listings registered on Danawa in
  2026-08 and 2026-09 (prices not shown; identity with this item not verified).
- Supplier: sound (top by orders for "pet sling carrier bag" and "dog sling bag crossbody", sale ₩9,160 above
  the regular ₩8,950 so the card price is real; store name and SKU table not visible; shipping not included).
  No better alternative: 1005006997647168 (1,723 orders, sale ₩8,500 vs regular ₩18,050, inflated anchor) and
  1005007159600609 (cotton sling, 579 orders, ₩9,800 / ₩9,581) do not change the economics.
- Compliance: free. Not on the KATS 안전기준준수대상 생활용품 list (kats.go.kr cmsid=553, fetched 2026-09-27),
  not 안전인증/안전확인/공급자적합성, not 어린이제품, no battery or radio, not food-contact; 반려동물용품 is an open
  구매대행 category on Coupang and Naver; unbranded, no design-copy match checked image by image.
- Return risk medium-high: size and fit (S/M/L by pet weight) drive returns; a returned soft-goods item cannot
  economically go back to China, so each return is a full loss; 10-15 day delivery raises cancellations.
- Verdict quoted: "Do not buy the sample for a price-gap play; only a differentiated/branded angle would work."

### 8.2 Golf head-cover set (1005009012434425): refuted on market economics, medium confidence

- Market low ₩12,350 (HACC 드라이버+우드+유틸리티 세트, Coupang 로켓배송, Danawa pcode 95285147); HACC PU set
  ₩14,110 free shipping (pcode 14431196); hacc.co.kr 투라인 set ₩14,900; typical ₩22,000. The ₩7,400 promo is
  most likely a single-cover SKU (the sibling listing 1005009170205520 shows ₩2,915 for a 4-cover image), so
  the set checkout price is probably near the ₩16,446 regular price, above Korean retail.
- Compliance free (sports accessory; 'Efunist' store mark on the product, do not present it as a Korean brand).
- Return risk high: per-piece SKU confusion (buyer expects 3종 세트, receives one cover), PU peeling after
  transit, next-day Coupang alternative at ₩12,350.

### 8.3 Foldable aluminium laptop stand (1005007562753306): refuted on market economics, high confidence

- Market low ₩4,810 (코시 NS2093, 76 malls); 벨레스 ₩5,090; 올더쉘 ₩5,100; 해피앤몰 HPN-041 ₩6,470 (299 reviews);
  Coupang 로켓직구 JUNLV 6단 about ₩4,800-5,040; Coupang own brands 홈플래닛 CP-LS01 ₩8,380 and 탐사 ₩9,990; typical
  ₩9,900. Ratio to the conservative supplier cost 0.78; 1.42 on a delivered basis. Ten or more near-identical
  AliExpress clones at ₩1,000-1,750 and Korean brands (NEXTU, 알파스캔 AOC L2, ANYZONE T2) sell the same OEM shape
  with domestic stock. Compliance free (non-electrical aluminium accessory).

### 8.4 Customs frame (sourced; law.go.kr, easylaw.go.kr, 관세청 releases via mirrors; customs.go.kr blocked)

- USD 150 self-use limit (USD 200 only for US-origin KORUS parcels) still in force in September 2026:
  관세법 제94조 제4호 (시행 2026-08-11) and 시행규칙 제45조 제2항 (시행 2026-07-31); no enacted change found.
- The limit is judged on 물품가격 (goods price plus taxes and transport inside the sending country);
  international freight to Korea is excluded from the test but added to the taxable value once taxable. How
  customs treats the AliExpress shipping line in practice was not checked.
- 목록통관 for a China parcel needs 자가사용 (or a duty-free commercial sample), 물품가격 under USD 150 and
  no 목록통관 배제 item; otherwise 수입신고. The USD 200 tier never applies to China-origin goods.
- 합산과세 since 2022-11-17: parcels are aggregated only when split within one waybill, or bought from the same
  supplier on the same date and split. Two AliExpress orders from the same store on the same day that together
  exceed USD 150 are aggregated.
- **Resale prohibition (verified)**: goods cleared duty-free as 자가사용 may not be sold; 관세청 treats resale as
  밀수입죄 (관세법 제269조) or 관세포탈죄 (제270조). Duty-paid, properly cleared goods may be resold under 관세법,
  subject to product rules. So the sample unit is kept, never sold.
- Commercial sample exemption (관세법 제94조 제3호, 시행규칙 제45조 제1항): duty and VAT free if recognised as a
  견본품 and the taxable value is at most USD 250; discretionary, and a 수입신고 is still filed. Whether
  AliExpress's carriers will file a 견본품 declaration for a non-registered individual was not checked. For the
  owner today (no 사업자 yet), the parcel clears as a private 자가사용 목록통관 parcel.
- 개인통관고유부호: one-year validity from 2026-01-01 (codes issued before 2026 expire on the holder's birthday in
  2027); since 2026-02-02 customs matches the delivery postcode against the addresses registered on the code, so
  the owner registers the delivery address on UNI-PASS before ordering.
- 관세청 전자상거래업자 registration system opened 2026-06-05; platform pilot from 2026-08-28 with a one-time
  인증번호 tied to the code. Whether every 구매대행 seller must register (or only those above the KRW 1 billion
  구매대행업자 threshold) is an open question.
- Mode B stock import: 사업자통관고유부호 (UNI-PASS, 기업용 공동인증서), 수입신고 in the business's name with duty
  plus 10% VAT on CIF; 관세사 fees typically ₩30,000-50,000 per entry. Indicative 2026 basic tariffs: plastics
  8%, rubber 8%, textile made-up articles 10%, steel articles 8% (한중FTA lower with a certificate of origin;
  the HS heading of any specific item is unverified).
- Not reachable: customs.go.kr FAQ pages, consumer.go.kr FAQ on resale of duty-free goods (503).
