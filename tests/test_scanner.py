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


def test_item_query_turns_english_title_into_korean_search():
    assert item_query(offer("temu", "Silicone Kitchen Tongs Set Heat Resistant", 1)) == "실리콘 주방집게 세트 내열"
    # Model codes still win, and untranslatable English stays English rather than becoming empty.
    assert item_query(offer("temu", "Frobnicator WH-1000XM5", 1)) == "WH1000XM5"
    assert item_query(offer("temu", "Frobnicator deluxe", 1)) == "frobnicator deluxe"


def test_per_item_scan_searches_market_in_korean_and_counts_photos():
    temu = Offer("temu", "Silicone kitchen tongs set", 3.2, "USD", "https://temu/1", image_url="https://t/1.jpg")
    supplier = StaticSource("temu", [temu, offer("temu", "Frobnicator", 1.0, "USD")])
    market = StaticSource("naver", [
        Offer("naver", "실리콘 주방 집게", 12_900, "KRW", "https://n/1", image_url="https://n/1.jpg", cross_border=False),
    ])
    settings = ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663}, per_item=True)

    class SamePhoto:
        def distance(self, a, b):
            return 2

    result = scan("tongs", [supplier], market, FX, settings, SamePhoto())
    assert market.queries == ["실리콘 주방집게 세트", "frobnicator"]
    assert [o.source.title for o in result.opportunities] == ["Silicone kitchen tongs set"]
    assert result.image_count == 1
    # Without the photo the same pair is left unmatched.
    assert scan("tongs", [supplier], market, FX, settings).opportunities == []


def test_compliance_and_glossary_work_together_in_one_scan():
    """Integration of the compliance filter (dropped) with cross-language matching (image_count)."""
    from arbitrage.config import load_settings

    rules = load_settings().compliance
    supplier = StaticSource("temu", [
        Offer("temu", "Silicone kitchen tongs set", 3.2, "USD", "https://temu/1", image_url="https://t/1.jpg"),
        Offer("temu", "Gummy candy 500g", 2.0, "USD", "https://temu/2", image_url="https://t/2.jpg"),
        Offer("temu", "Wireless Bluetooth earbuds", 9.0, "USD", "https://temu/3", image_url="https://t/3.jpg"),
    ])
    market = StaticSource("naver", [
        Offer("naver", "실리콘 주방 집게", 12_900, "KRW", "https://n/1", image_url="https://n/1.jpg", cross_border=False),
        Offer("naver", "무선 블루투스 이어폰", 29_900, "KRW", "https://n/3", image_url="https://n/3.jpg", cross_border=False),
    ])
    settings = ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663}, per_item=True, compliance=rules)

    class Photos:
        def distance(self, a, b):
            return 2 if a[-5] == b[-5] else 40  # same number = same photo

    result = scan("x", [supplier], market, FX, settings, Photos())

    # Food is dropped before the market is searched; the other two are searched in Korean.
    assert [o.title for o, _ in result.dropped] == ["Gummy candy 500g"]
    assert result.dropped[0][1][0].category == "food"
    assert market.queries == ["실리콘 주방집게 세트", "무선 블루투스 이어폰"]
    # Both new ScanResult fields are populated side by side.
    assert result.image_count == 3
    assert result.source_count == 3
    # Tongs match through glossary + photo and carry no flags; the earbuds match but are flagged (radio).
    by_title = {o.source.title: o for o in result.opportunities}
    assert set(by_title) == {"Silicone kitchen tongs set", "Wireless Bluetooth earbuds"}
    assert by_title["Silicone kitchen tongs set"].flags == []
    assert {f.category for f in by_title["Wireless Bluetooth earbuds"].flags} >= {"radio"}
    assert any(r.endswith("(translated)") for r in by_title["Silicone kitchen tongs set"].best_match[1].reasons)
