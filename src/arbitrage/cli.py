"""Command line: `arbitrage scan` finds price gaps, `arbitrage price` checks one product."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from .config import Settings, load_dotenv, load_settings
from .errors import ArbitrageError, ConfigError
from .fx import FxRates
from .images import ImageHasher
from .models import Offer
from .pricing import landed_cost, price_for_margin, quote
from .report import format_table, write_csv
from .scanner import ScanSettings, scan
from .sources import AliExpress, CsvSource, NaverShopping

NO_API = {
    "temu": "Temu has no public API and its terms forbid scraping",
    "1688": "1688 has no open product API",
    "taobao": "Taobao has no open product API",
}


def build_source(spec: str, settings: Settings):
    if spec == "aliexpress":
        return AliExpress.from_env(default_shipping=settings.aliexpress_shipping_krw)
    if spec.startswith("csv:"):
        return CsvSource(spec[4:])
    if spec.endswith(".csv"):
        return CsvSource(spec)
    if spec.lower() in NO_API:
        raise ConfigError(f"{NO_API[spec.lower()]}. Export products to a CSV and pass --source csv:PATH")
    raise ConfigError(f"unknown source {spec!r}: use aliexpress or csv:PATH")


def build_market():
    return NaverShopping.from_env()


def _marketplaces(value: str, settings: Settings) -> list[str]:
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in settings.fee_rates]
    if unknown or not names:
        raise ConfigError(f"--sell-on accepts: {', '.join(settings.fee_rates)}")
    return names


def _load(args) -> tuple[Settings, list[str]]:
    settings = load_settings(args.config)
    if args.min_margin is not None:
        settings = replace(settings, policy=replace(settings.policy, target_margin=args.min_margin))
    marketplaces = _marketplaces(args.sell_on, settings)
    return replace(settings, fee_rates={m: settings.fee_rates[m] for m in marketplaces}), marketplaces


def _fx(args, settings: Settings) -> FxRates:
    if args.offline_fx:
        return FxRates(settings.fx_fallback, origin="config")
    return FxRates.live(settings.fx_fallback)


def cmd_scan(args) -> int:
    settings, marketplaces = _load(args)
    sources = [build_source(spec, settings) for spec in (args.source or ["aliexpress"])]
    market = build_market()
    fx = _fx(args, settings)

    hasher = None
    if not args.no_images:
        if ImageHasher.available():
            hasher = ImageHasher()
        else:
            print("note: Pillow not installed, matching without images", file=sys.stderr)

    scan_settings = ScanSettings(
        policy=settings.policy,
        fee_rates=settings.fee_rates,
        match=settings.match,
        per_item=args.per_item,
        source_limit=args.limit,
        market_limit=args.market_limit,
    )
    result = scan(args.query, sources, market, fx, scan_settings, hasher)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    viable = [o for o in result.opportunities if o.best.viable]
    shown = result.opportunities if args.all else viable
    print(
        f"{result.source_count} supplier products checked, {len(result.opportunities)} found on "
        f"{market.name}, {len(viable)} clear {settings.policy.target_margin:.0%} margin "
        f"(FX: {fx.origin}, USD={fx.rate('USD'):,.0f} KRW)"
    )
    if shown:
        print(format_table(shown, args.top))
    if result.opportunities:
        write_csv(result.opportunities, args.out, marketplaces)
        print(f"wrote {len(result.opportunities)} rows to {args.out} (check each match by hand before listing)")
    return 0


def cmd_price(args) -> int:
    settings, marketplaces = _load(args)
    fx = _fx(args, settings)
    offer = Offer(
        platform="manual",
        title="",
        price=args.cost,
        currency=args.currency.upper(),
        url="",
        shipping=args.shipping,
        cross_border=not args.domestic,
    )
    landed, notes = landed_cost(offer, fx, settings.policy)
    print(f"landed cost: ₩{landed:,}")
    for note in notes:
        print(f"  note: {note}")
    policy = settings.policy
    for m in marketplaces:
        rate = settings.fee_rates[m]
        line = (
            f"{m:<8} break-even ₩{price_for_margin(landed, rate, policy, 0.0):,}  "
            f"for {policy.target_margin:.0%} margin ₩{price_for_margin(landed, rate, policy, policy.target_margin):,}"
        )
        if args.market_price:
            q = quote(m, rate, landed, args.market_price, policy)
            line += f"  | at ₩{q.list_price:,}: profit ₩{q.profit:,} ({q.margin:.1%}){'' if q.viable else '  ✗'}"
        print(line)
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sell-on", default="naver,coupang", help="marketplaces to price for (default: naver,coupang)")
    p.add_argument("--min-margin", type=float, help="required net margin, e.g. 0.2 (default from config)")
    p.add_argument("--config", help="TOML file overriding default.toml")
    p.add_argument("--offline-fx", action="store_true", help="use [fx] rates from config instead of today's rates")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arbitrage", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="find products that cost less at a supplier than they sell for in Korea")
    p_scan.add_argument("query", help="product keyword, e.g. '무선 청소기'")
    p_scan.add_argument("--source", action="append", help="aliexpress (default) or csv:PATH; repeatable")
    p_scan.add_argument("--limit", type=int, default=50, help="supplier products to check (default 50)")
    p_scan.add_argument("--market-limit", type=int, default=100, help="market listings per search (default 100)")
    p_scan.add_argument("--per-item", action="store_true", help="search the market separately for each supplier product")
    p_scan.add_argument("--no-images", action="store_true", help="skip image comparison (faster, fewer matches)")
    p_scan.add_argument("--all", action="store_true", help="also show matches below the target margin")
    p_scan.add_argument("--top", type=int, default=20, help="rows to print (default 20)")
    p_scan.add_argument("--out", default="opportunities.csv", help="CSV report path")
    _common(p_scan)
    p_scan.set_defaults(func=cmd_scan)

    p_price = sub.add_parser("price", help="landed cost, break-even and profit for one product")
    p_price.add_argument("--cost", type=float, required=True, help="supplier price")
    p_price.add_argument("--currency", default="KRW", help="supplier currency (KRW, USD, CNY, ...)")
    p_price.add_argument("--shipping", type=float, default=0.0, help="shipping to Korea, same currency")
    p_price.add_argument("--domestic", action="store_true", help="supplier ships inside Korea (no customs)")
    p_price.add_argument("--market-price", type=float, help="cheapest competitor price in KRW")
    _common(p_price)
    p_price.set_defaults(func=cmd_price)

    args = parser.parse_args(argv)
    load_dotenv()
    try:
        return args.func(args)
    except ArbitrageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
