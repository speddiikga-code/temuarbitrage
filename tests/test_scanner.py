from arbitrage.errors import SourceError
from arbitrage.fx import FxRates
from arbitrage.models import Offer
from arbitrage.pricing import Policy
from arbitrage.scanner import ScanSettings, item_query, scan

FX = FxRates({"USD": 1365})
SETTINGS = ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663, "coupang": 0.1188})


def offer(platform, title, price, currency="KRW", cross_border=True):
    return Offer(platform, title, price, currency, f"https://{platform}/{title}", cross_border=cross_border)


class StaticSource:
    def __init__(self, name, offers=None, error=None):
        self.name = name
        self.offers = offers or []
        self.error = error
        self.queries = []

    def search(self, query, limit):
        self.queries.append(query)
        if self.error:
            raise SourceError(self.error)
        return self.offers[:limit]


def test_scan_ranks_matches_by_profit_and_skips_unmatched():
    supplier = StaticSource("aliexpress", [
        offer("aliexpress", "소니 WH-1000XM5 헤드폰", 250_000),
        offer("aliexpress", "실리콘 주방 뒤집개 집게 세트", 4_000),
        offer("aliexpress", "스텐 전기포트 1.7L", 9_000),
    ])
    market = StaticSource("naver", [
        offer("naver", "소니 WH1000XM5 노이즈캔슬링", 389_000, cross_border=False),
        offer("naver", "실리콘 주방 뒤집개 & 집게 세트", 12_900, cross_border=False),
        offer("naver", "실리콘 주방 뒤집개 집게 세트 국내배송", 14_900, cross_border=False),
    ])
    result = scan("x", [supplier], market, FX, SETTINGS)

    assert result.source_count == 3
    assert [o.source.title for o in result.opportunities] == ["소니 WH-1000XM5 헤드폰", "실리콘 주방 뒤집개 집게 세트"]
    tongs = result.opportunities[1]
    assert tongs.market_low == 12_900
    assert len(tongs.matches) == 2
    assert tongs.best.marketplace == "naver"  # lower fees
    assert market.queries == ["x"]


def test_failing_supplier_becomes_a_warning():
    ok = StaticSource("csv", [offer("csv", "실리콘 주방 뒤집개 집게 세트", 4_000)])
    broken = StaticSource("aliexpress", error="quota exceeded")
    market = StaticSource("naver", [offer("naver", "실리콘 주방 뒤집개 집게 세트", 12_900, cross_border=False)])
    result = scan("x", [broken, ok], market, FX, SETTINGS)
    assert len(result.opportunities) == 1
    assert result.warnings == ["aliexpress: quota exceeded"]


def test_per_item_searches_market_by_model_code_once():
    supplier = StaticSource("aliexpress", [
        offer("aliexpress", "WH-1000XM5 headphones", 250_000),
        offer("aliexpress", "Sony WH-1000XM5 black", 251_000),
    ])
    market = StaticSource("naver", [offer("naver", "소니 WH1000XM5", 389_000, cross_border=False)])
    settings = ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663}, per_item=True)
    result = scan("headphones", [supplier], market, FX, settings)
    assert market.queries == ["WH1000XM5"]
    assert len(result.opportunities) == 2


def test_item_query_falls_back_to_key_words():
    assert item_query(offer("a", "[무료배송] 실리콘 주방 뒤집개 집게 세트 특가", 1)) == "실리콘 주방 뒤집개 집게 세트"
