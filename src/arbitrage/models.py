"""Plain data types shared across the pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Offer:
    """One listing of a product on one platform."""

    platform: str
    title: str
    price: float
    currency: str
    url: str
    shipping: float = 0.0
    image_url: str | None = None
    seller: str | None = None
    brand: str | None = None
    model: str | None = None
    product_id: str | None = None
    # True when the item ships from abroad and goes through Korean customs.
    cross_border: bool = True


@dataclass(frozen=True)
class MatchResult:
    """How confident we are that two offers are the same physical product."""

    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Quote:
    """What reselling one source product on one marketplace would earn."""

    marketplace: str
    list_price: int
    break_even: int
    min_viable: int
    profit: int
    margin: float
    viable: bool


@dataclass
class Opportunity:
    source: Offer
    matches: list[tuple[Offer, MatchResult]]
    landed_cost: int
    market_low: int
    quotes: dict[str, Quote]
    notes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """Stable across scans: platform + product id, or a hash of the URL."""
        key = self.source.product_id or hashlib.sha1(self.source.url.encode("utf-8")).hexdigest()[:12]
        return f"{self.source.platform}:{key}"

    @property
    def best(self) -> Quote:
        return max(self.quotes.values(), key=lambda q: q.profit)

    @property
    def best_match(self) -> tuple[Offer, MatchResult]:
        return max(self.matches, key=lambda m: m[1].score)
