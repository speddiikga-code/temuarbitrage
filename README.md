# arbitrage

Finds the **same product at different prices** on different platforms, works out what
reselling it would really earn after fees, ads, returns and customs, and ranks the gaps.

Phase 1 of a dropship setup (buy from the supplier only after a customer orders):

```
supplier offers ──► find the same product on the Korean market ──► landed cost vs. market price ──► ranked CSV
(AliExpress API,     (Naver Shopping API: prices across            (fees, ads, returns, FX,
 CSV for anything     Korean malls)                                  $150 duty-free check)
 else)
```

Listing products and placing orders come later (see Roadmap). This tool only *finds and prices*
opportunities. **Check every match by hand before you list anything.**

## Setup

```bash
pip install -e ".[images]"        # Pillow enables image matching (recommended)
cp .env.example .env              # then fill in the keys below
```

| Key | Where to get it | Cost |
|---|---|---|
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | [Naver Developers](https://developers.naver.com/apps) → register an app → add **검색 API** | Free, 25,000 calls/day |
| `ALIEXPRESS_APP_KEY` / `ALIEXPRESS_APP_SECRET` / `ALIEXPRESS_TRACKING_ID` | [AliExpress Open Platform](https://openservice.aliexpress.com) → affiliate app | Free |

## Usage

```bash
# Supplier = AliExpress, market = Naver Shopping, priced for Naver and Coupang
arbitrage scan "차량용 휴대폰 거치대"

# More precise: search the market separately for each supplier product
arbitrage scan "차량용 휴대폰 거치대" --per-item --limit 30

# Temu / 1688 / Taobao / wholesale sites: put products in a CSV (see below)
arbitrage scan "주방 집게" --source csv:my_temu_picks.csv

# One product: what must it sell for?
arbitrage price --cost 5.2 --currency USD --shipping 1.5 --market-price 19900
```

`scan` prints the best opportunities and writes every match to `opportunities.csv`
(opens correctly in Excel). Useful flags: `--sell-on naver`, `--min-margin 0.2`,
`--all` (include thin margins), `--no-images`, `--config my.toml`.

### CSV suppliers

Required columns are `title,price,url`. Optional columns are `platform,currency,shipping,image_url,brand,model,cross_border`.
`cross_border` defaults to true unless the currency is KRW.

```csv
platform,title,price,currency,shipping,url,image_url
temu,Silicone kitchen tongs set,3.20,USD,1.50,https://www.temu.com/...,https://...jpg
```

Temu has no public API and its terms forbid scraping, so the tool reads Temu products from
a CSV you prepare instead of scraping the site.

## How it decides

**Same product?** (`matching.py`) The strongest signals are a shared model code (`WH-1000XM5`) and a near-identical product photo.
Resellers usually reuse the supplier's photos. Title similarity and brand add weight.
A different pack size (`2개입` vs single), brand or model code rejects the pair outright.
Title-only matching is strict on purpose. Generic goods mostly match through images, so run with Pillow installed.

**Worth it?** (`pricing.py`) Fees, ads and returns are charged on the sale price, so the tool uses:

```
price for margin = landed cost ÷ (1 − marketplace fee − ads − returns − margin)
landed cost      = (item + shipping) × FX × (1 + FX buffer) [+ duty & VAT above $150]
```

The tool lists at the cheapest matched competitor's price, or below it with `undercut`, and calls the product viable when
net margin ≥ `target_margin`. Defaults are in `src/arbitrage/default.toml`:

| Setting | Default | Note |
|---|---|---|
| Naver fee | 6.63% | 판매수수료 3% + 주문관리수수료 ≤3.63%; check your seller grade |
| Coupang fee | 11.88% | 10.8% category commission + VAT; check your category |
| Ads / returns | 10% / 3% | of sale price |
| Target margin | 15% | |
| FX | live (open.er-api.com), fallback in config | +3% buffer on foreign currency |

## Known limits

- Naver prices exclude the competitor's shipping fee, and the AliExpress API doesn't return shipping (`default_shipping_krw`).
- Naver Shopping is the market *reference* for both Naver and Coupang. Coupang's own prices can differ.
- KC certification, 전파법, food/cosmetics/medical rules and trademarks are **not** checked yet.
- Matching is heuristic. The CSV includes `match_reasons` so you can see why each pair matched.

## Roadmap

1. **Now:** find and price opportunities (this).
2. Compliance filter (KC tiers, restricted categories, brand blocklist) and Korean listing copy.
3. List on Coupang (WING Open API) and Naver (Commerce API). Both require calls from a registered fixed IP, so this runs on a Seoul server.
4. Order sync: pull orders + 개인통관고유부호, create purchase tasks, push tracking numbers back.

## Development

```bash
pip install -e ".[dev]"
pytest
```
