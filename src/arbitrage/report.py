"""CSV and JSON export, and a terminal summary of scan results."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .fx import FxRates
from .models import Opportunity
from .pricing import Policy

BASE_COLUMNS = [
    "source_platform", "source_title", "source_url", "source_price", "source_currency",
    "landed_cost_krw", "market_low_krw", "matched_listings",
    "best_match_score", "best_match_title", "best_match_seller", "best_match_url", "match_reasons",
]
QUOTE_FIELDS = ["list_price", "profit", "margin", "break_even", "min_viable", "viable"]


def write_csv(opportunities: list[Opportunity], path: str | Path, marketplaces: list[str]) -> None:
    columns = BASE_COLUMNS + [f"{m}_{f}" for m in marketplaces for f in QUOTE_FIELDS] + ["notes"]
    # utf-8-sig so Excel shows Korean correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for o in opportunities:
            best, result = o.best_match
            row = {
                "source_platform": o.source.platform,
                "source_title": o.source.title,
                "source_url": o.source.url,
                "source_price": o.source.price,
                "source_currency": o.source.currency,
                "landed_cost_krw": o.landed_cost,
                "market_low_krw": o.market_low,
                "matched_listings": len(o.matches),
                "best_match_score": f"{result.score:.2f}",
                "best_match_title": best.title,
                "best_match_seller": best.seller or "",
                "best_match_url": best.url,
                "match_reasons": "; ".join(result.reasons),
                "notes": "; ".join(o.notes),
            }
            for m in marketplaces:
                q = o.quotes[m]
                row.update({
                    f"{m}_list_price": q.list_price,
                    f"{m}_profit": q.profit,
                    f"{m}_margin": f"{q.margin:.3f}",
                    f"{m}_break_even": q.break_even,
                    f"{m}_min_viable": q.min_viable,
                    f"{m}_viable": q.viable,
                })
            writer.writerow(row)


# Bump when a field is renamed or removed; adding fields keeps the version.
SCHEMA_VERSION = 1


def to_json(
    opportunities: list[Opportunity],
    *,
    query: str,
    source_count: int,
    warnings: list[str],
    fx: FxRates,
    policy: Policy,
    fee_rates: dict[str, float],
) -> dict:
    """Scan results as plain data: the contract other tools (e.g. the review workbench) read."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "source_count": source_count,
        "warnings": warnings,
        "fx": {"origin": fx.origin, "USD": fx.rate("USD")},
        "policy": asdict(policy),
        "fee_rates": fee_rates,
        "opportunities": [
            {
                "id": o.id,
                "source": asdict(o.source),
                "landed_cost": o.landed_cost,
                "market_low": o.market_low,
                "best_marketplace": o.best.marketplace,
                "quotes": {name: asdict(q) for name, q in o.quotes.items()},
                "matches": [
                    {"offer": asdict(offer), "score": round(result.score, 3), "reasons": list(result.reasons)}
                    for offer, result in sorted(o.matches, key=lambda m: m[1].score, reverse=True)
                ],
                "notes": o.notes,
            }
            for o in opportunities
        ],
    }


def write_json(data: dict, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def format_table(opportunities: list[Opportunity], top: int = 20) -> str:
    header = f"{'#':>3}  {'profit':>9}  {'margin':>6}  {'sell on':<8}  {'price':>9}  {'cost':>9}  {'match':>5}  {'rivals':>6}  title"
    lines = [header, "-" * len(header)]
    for i, o in enumerate(opportunities[:top], start=1):
        q = o.best
        lines.append(
            f"{i:>3}  {q.profit:>9,}  {q.margin:>6.1%}  {q.marketplace:<8}  {q.list_price:>9,}  "
            f"{o.landed_cost:>9,}  {o.best_match[1].score:>5.2f}  {len(o.matches):>6}  "
            f"[{o.source.platform}] {_truncate(o.source.title, 50)}"
        )
    return "\n".join(lines)
