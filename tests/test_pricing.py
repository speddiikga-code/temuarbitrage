import pytest

from arbitrage.errors import ConfigError
from arbitrage.fx import FxRates
from arbitrage.models import Offer
from arbitrage.pricing import Policy, ceil_to, landed_cost, price_for_margin, profit_at, quote

FX = FxRates({"USD": 1365, "CNY": 202})
NO_EXTRAS = Policy(ad_rate=0, returns_rate=0, fx_buffer=0)


def offer(price, currency="USD", shipping=0.0, cross_border=True):
    return Offer("test", "item", price, currency, "https://x", shipping=shipping, cross_border=cross_border)


def test_price_for_margin_divides_by_what_is_left_after_fees():
    # ₩20,000 landed, 11.9% fee, 20% margin -> 20,000 / 0.681 = 29,368.6 -> ₩29,400
    assert price_for_margin(20_000, 0.119, NO_EXTRAS, 0.20) == 29_400


def test_cost_times_one_plus_fee_formula_misses_the_target_margin():
    # The "(cost) x (1 + fee) x markup" formula lists at ₩26,856 for a "20%" markup...
    naive_price = 20_000 * 1.119 * 1.2
    margin = profit_at(naive_price, 20_000, 0.119, NO_EXTRAS) / naive_price
    assert margin == pytest.approx(0.136, abs=0.001)  # ...but earns 13.6%
    # ...and ads at 10% of revenue leave almost nothing.
    with_ads = Policy(ad_rate=0.10, returns_rate=0, fx_buffer=0)
    assert profit_at(naive_price, 20_000, 0.119, with_ads) / naive_price == pytest.approx(0.036, abs=0.001)


def test_ceil_to_ignores_float_noise():
    assert ceil_to(20_000 / 0.8) == 25_000


def test_impossible_margin_is_reported():
    with pytest.raises(ConfigError, match="leave nothing"):
        price_for_margin(10_000, 0.5, Policy(ad_rate=0.3, returns_rate=0.1), 0.2)


def test_landed_cost_converts_and_adds_fx_buffer():
    cost, notes = landed_cost(offer(10, shipping=2), FX, Policy(fx_buffer=0.03))
    assert cost == pytest.approx(12 * 1365 * 1.03, abs=1)
    assert notes == []


def test_landed_cost_adds_duty_and_vat_over_150_usd():
    cost, notes = landed_cost(offer(200), FX, Policy(fx_buffer=0, tariff_rate=0.08, import_vat_rate=0.10))
    goods = 200 * 1365
    assert cost == pytest.approx(goods + goods * 0.08 + goods * 1.08 * 0.10, abs=1)
    assert "duty-free" in notes[0]


def test_domestic_krw_offer_has_no_buffer_or_customs():
    cost, notes = landed_cost(offer(300_000, "KRW", shipping=3000, cross_border=False), FX, Policy())
    assert cost == 303_000
    assert notes == []


def test_quote_matches_cheapest_competitor_and_checks_margin():
    policy = Policy(ad_rate=0.10, returns_rate=0.03, target_margin=0.15)
    good = quote("naver", 0.0663, landed=10_000, market_low=29_950, policy=policy)
    assert good.list_price == 29_900
    assert good.profit == round(29_900 * (1 - 0.0663 - 0.13) - 10_000)
    assert good.viable
    assert good.break_even < good.min_viable <= good.list_price

    thin = quote("coupang", 0.1188, landed=10_000, market_low=15_000, policy=policy)
    assert not thin.viable
    assert thin.margin < 0.15


def test_undercut_lowers_list_price():
    q = quote("naver", 0.0663, landed=10_000, market_low=30_000, policy=Policy(undercut=0.05))
    assert q.list_price == 28_500
