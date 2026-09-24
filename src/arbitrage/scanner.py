"""The pipeline: supplier offers -> matching market listings -> resale profit, best first."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import SourceError
from .fx import FxRates
from .matching import MatchSettings, match, model_codes, tokens
from .models import Offer, Opportunity
from .pricing import Policy, landed_cost, quote


@dataclass(frozen=True)
class ScanSettings:
    policy: Policy
    fee_rates: dict[str, float]
    match: MatchSettings = MatchSettings()
    # Search the market once per supplier item (precise, more API calls) instead of once per keyword.
    per_item: bool = False
    source_limit: int = 50
    market_limit: int = 100


@dataclass
class ScanResult:
    opportunities: list[Opportunity]
    source_count: int
    warnings: list[str] = field(default_factory=list)


def item_query(offer: Offer) -> str:
    """Market search query for one supplier item: its model code if it has one, else its key words."""
    codes = model_codes(offer.title) | model_codes(offer.model or "")
    if codes:
        return max(codes, key=len)
    return " ".join(tokens(offer.title)[:6])


def evaluate(source: Offer, market_offers: list[Offer], fx: FxRates, settings: ScanSettings, hasher=None) -> Opportunity | None:
    matches = []
    for candidate in market_offers:
        if candidate.url and candidate.url == source.url:
            continue
        result = match(source, candidate, hasher, settings.match)
        if result.score >= settings.match.threshold:
            matches.append((candidate, result))
    if not matches:
        return None

    landed, notes = landed_cost(source, fx, settings.policy)
    market_low = round(min(fx.to_krw(m.price + m.shipping, m.currency) for m, _ in matches))
    quotes = {
        name: quote(name, rate, landed, market_low, settings.policy)
        for name, rate in settings.fee_rates.items()
    }
    return Opportunity(source, matches, landed, market_low, quotes, notes)


def scan(query: str, sources: list, market, fx: FxRates, settings: ScanSettings, hasher=None) -> ScanResult:
    warnings: list[str] = []
    supplier_offers: list[Offer] = []
    for source in sources:
        try:
            supplier_offers += source.search(query, settings.source_limit)
        except SourceError as e:
            warnings.append(f"{source.name}: {e}")

    market_cache: dict[str, list[Offer]] = {}
    if not settings.per_item:
        market_cache[query] = market.search(query, settings.market_limit)

    opportunities = []
    for offer in supplier_offers:
        market_query = item_query(offer) if settings.per_item else query
        if market_query not in market_cache:
            try:
                market_cache[market_query] = market.search(market_query, settings.market_limit)
            except SourceError as e:
                warnings.append(f"{market.name} ({market_query}): {e}")
                market_cache[market_query] = []
        opportunity = evaluate(offer, market_cache[market_query], fx, settings, hasher)
        if opportunity:
            opportunities.append(opportunity)

    opportunities.sort(key=lambda o: o.best.profit, reverse=True)
    return ScanResult(opportunities, len(supplier_offers), warnings)
