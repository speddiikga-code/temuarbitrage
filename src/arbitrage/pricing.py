"""Landed cost and resale profit.

Marketplace fees, ads and returns are all charged as a share of the *sale price*,
so the price that yields a target margin is

    price = landed_cost / (1 - fee - ads - returns - margin)

Multiplying cost by (1 + fee) instead under-prices every listing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import ConfigError
from .fx import FxRates
from .models import Offer, Quote


@dataclass(frozen=True)
class Policy:
    ad_rate: float = 0.10
    returns_rate: float = 0.03
    target_margin: float = 0.15
    fx_buffer: float = 0.03
    undercut: float = 0.0
    duty_free_usd: float = 150.0
    tariff_rate: float = 0.08
    import_vat_rate: float = 0.10
    # Why the goods cross the border. Goods bought to resell must be declared and taxed whatever they cost
    # (관세청 guidance, checked 2026-09-27), so the personal-use USD 150 exemption applies to personal_use only.
    # Samples get no exemption either until customs evidence says otherwise.
    import_basis: str = "commercial_resale"


IMPORT_BASES = ("commercial_resale", "personal_use", "genuine_sample")


def ceil_to(value: float, step: int = 100) -> int:
    # round() first so 25000.000000000004 doesn't become 25100.
    return math.ceil(round(value / step, 6)) * step


def floor_to(value: float, step: int = 100) -> int:
    return math.floor(round(value / step, 6)) * step


def landed_cost(offer: Offer, fx: FxRates, policy: Policy) -> tuple[int, list[str]]:
    """KRW it costs to get `offer` to a Korean customer, plus notes on what was assumed.

    Duty and VAT are estimates at the policy's flat rates until the product's HS classification is verified;
    the notes say so. Only `import_basis = "personal_use"` under the duty-free limit yields zero tax.
    """
    notes: list[str] = []
    goods = fx.to_krw(offer.price + offer.shipping, offer.currency)
    cost = goods
    if offer.currency.upper() != "KRW":
        cost *= 1 + policy.fx_buffer
    if offer.cross_border:
        if policy.import_basis not in IMPORT_BASES:
            raise ConfigError(f"policy.import_basis must be one of {', '.join(IMPORT_BASES)}, not {policy.import_basis!r}")
        value_usd = goods / fx.rate("USD")
        if policy.import_basis == "personal_use" and value_usd <= policy.duty_free_usd:
            notes.append(f"personal-use import under ${policy.duty_free_usd:g}: no duty assumed (not valid for resale)")
        else:
            duty = goods * policy.tariff_rate
            vat = (goods + duty) * policy.import_vat_rate
            cost += duty + vat
            why = {
                "commercial_resale": "commercial import for resale: declared and taxed at any value",
                "genuine_sample": "sample import: no exemption assumed without customs evidence",
                "personal_use": f"over ${policy.duty_free_usd:g} duty-free limit (${value_usd:,.0f})",
            }[policy.import_basis]
            notes.append(
                f"{why}: ~₩{duty + vat:,.0f} duty+VAT estimated at {policy.tariff_rate:.0%} + "
                f"{policy.import_vat_rate:.0%} (HS classification unverified)"
            )
    return math.ceil(cost), notes


def _kept_share(fee_rate: float, policy: Policy) -> float:
    return 1 - fee_rate - policy.ad_rate - policy.returns_rate


def price_for_margin(landed: float, fee_rate: float, policy: Policy, margin: float) -> int:
    keep = _kept_share(fee_rate, policy) - margin
    if keep <= 0:
        raise ConfigError(
            f"fees ({fee_rate:.1%}) + ads ({policy.ad_rate:.1%}) + returns "
            f"({policy.returns_rate:.1%}) + margin ({margin:.1%}) leave nothing to cover cost"
        )
    return ceil_to(landed / keep)


def profit_at(price: float, landed: float, fee_rate: float, policy: Policy) -> float:
    return price * _kept_share(fee_rate, policy) - landed


def quote(marketplace: str, fee_rate: float, landed: int, market_low: float, policy: Policy) -> Quote:
    """Profit from matching (or undercutting) the cheapest competitor on `marketplace`."""
    list_price = floor_to(market_low * (1 - policy.undercut))
    profit = profit_at(list_price, landed, fee_rate, policy)
    margin = profit / list_price if list_price > 0 else 0.0
    return Quote(
        marketplace=marketplace,
        list_price=list_price,
        break_even=price_for_margin(landed, fee_rate, policy, 0.0),
        min_viable=price_for_margin(landed, fee_rate, policy, policy.target_margin),
        profit=round(profit),
        margin=margin,
        viable=margin >= policy.target_margin,
    )
