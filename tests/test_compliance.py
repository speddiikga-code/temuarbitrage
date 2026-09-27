import pytest

from arbitrage.compliance import ComplianceRules, Rule, check, contains, should_drop
from arbitrage.config import load_settings
from arbitrage.fx import FxRates
from arbitrage.matching import MatchSettings
from arbitrage.models import Offer
from arbitrage.pricing import Policy
from arbitrage.report import format_table, to_json
from arbitrage.scanner import ScanSettings, scan

RULES = load_settings().compliance


def offer(title, platform="temu", brand=None, model=None, cross_border=True, price=5.0, currency="USD"):
    return Offer(platform, title, price, currency, f"https://{platform}/{title}", brand=brand, model=model, cross_border=cross_border)


def categories(title, **kw):
    return {f.category for f in check(offer(title, **kw), RULES)}


def test_keyword_matching_rules():
    assert contains("Silicone kids cup", "kid") is False  # whole word for Latin
    assert contains("Silicone kid cup", "kid")
    assert contains("어린이용 컵", "어린이")  # substring for Korean
    assert contains("5000mAh power bank", "~mah")  # ~ forces substring
    assert contains("<b>블루투스</b> 스피커", "블루투스")  # HTML from Naver is stripped
    assert not contains("Adapter", "ac adapter")


@pytest.mark.parametrize("title, expected", [
    ("Bluetooth 5.3 wireless earbuds", {"radio", "kc_supplier"}),
    ("무선 블루투스 이어폰", {"radio", "kc_supplier"}),
    ("USB C 65W GaN 충전기", {"kc_safety_confirm", "kc_supplier"}),
    ("전기장판 싱글 220V", {"kc_safety_cert"}),
    ("Montessori wooden toy for toddlers", {"children"}),
    ("아기 젖병 세척 브러시", {"children"}),
    ("10000mAh power bank", {"batteries"}),
    ("Vitamin C gummies 60ct", {"food"}),
    ("KF94 마스크 50매", {"medical"}),
    ("Digital forehead thermometer", {"medical"}),
    ("Rechargeable arc lighter", {"restricted"}),
    ("Li-ion 18650 rechargeable cell", {"batteries"}),
    ("Nike running shoes", {"brand"}),
    ("나이키 에어포스 운동화", {"brand"}),
    ("실리콘 주방 집게 세트", set()),
    ("Stainless steel kitchen tongs", set()),
])
def test_default_rules_on_typical_titles(title, expected):
    assert categories(title) == expected


@pytest.mark.parametrize("title", [
    "Meat thermometer for grilling",   # kitchen, not medical
    "Coffee grinder manual",           # appliance, not food
    "Ice cream maker",                 # not a cosmetic cream
    "Weed puller garden tool",         # not cannabis
    "Hot glue gun 20W",                # not a weapon
    "Dog chew toy rope",               # pet, not children's product
    "아기자기한 인테리어 소품",             # 아기자기 != 아기
    "Mouse pad large gaming",          # not an electrical mouse
    "Food storage container set",      # container, not food
])
def test_common_false_positives_are_excluded(title):
    assert categories(title) == set(), title


def test_brand_and_model_fields_are_checked_too():
    assert categories("Wireless headphones", brand="Sony") == {"radio", "kc_supplier", "brand"}
    assert categories("헤드폰", model="Airpods Pro") >= {"brand"}


def test_flag_says_why_and_where():
    (flag,) = check(offer("KF94 마스크"), RULES)
    assert flag.action == "drop"
    assert "의료기기법" in flag.reason
    assert flag.matched == "kf94" and flag.where == "source"
    assert flag.label().startswith("medical: 의료기기법")
    assert set(flag.as_dict()) == {"category", "action", "reason", "matched", "where"}


def test_config_mode_and_cli_overrides():
    rules = ComplianceRules.from_config({"toys": {"keywords": ["toy"], "action": "flag"}, "brands": {"blocklist": ["nike"]}})
    assert should_drop(check(offer("toy"), rules)) is False
    assert should_drop(check(offer("toy"), rules.with_mode("drop"))) is True
    assert check(offer("nike toy"), rules.with_mode("off")) == []
    forced = ComplianceRules.from_config({"mode": "drop", "toys": {"keywords": ["toy"]}, "brands": {"blocklist": ["nike"]}})
    assert should_drop(check(offer("nike"), forced))
    with pytest.raises(ValueError):
        Rule("x", "x", "maybe", ("a",))
    with pytest.raises(ValueError):
        rules.with_mode("loud")


def test_requires_any_and_unless():
    rules = ComplianceRules((Rule("heat", "hot", "flag", ("heater",), requires_any=("electric",), unless=("hand warmer",)),))
    assert check(offer("electric heater"), rules)
    assert not check(offer("gas heater"), rules)
    assert not check(offer("electric heater hand warmer"), rules)


class StaticSource:
    def __init__(self, name, offers):
        self.name, self.offers, self.queries = name, offers, []

    def search(self, query, limit):
        self.queries.append(query)
        return self.offers[:limit]


FX = FxRates({"USD": 1365})


def test_scan_drops_flags_and_reports():
    supplier = StaticSource("temu", [
        offer("KF94 mask 50pcs", price=4),                 # dropped before the market search
        offer("실리콘 주방 집게 세트", price=3),                 # clean
        offer("미니 휴대용 스피커 speaker", price=6),            # source: kc_supplier; market title adds radio
        offer("곰돌이 무드등 인테리어", price=5),                # market title reveals a food item -> dropped
    ])
    market = StaticSource("naver", [
        offer("실리콘 주방 집게 세트 국내배송", "naver", price=12_900, currency="KRW", cross_border=False),
        offer("미니 휴대용 스피커 speaker 블루투스", "naver", price=25_000, currency="KRW", cross_border=False),
        offer("곰돌이 무드등 인테리어 젤리 간식", "naver", price=15_000, currency="KRW", cross_border=False),
    ])
    # Title-only matching is strict by design; loosen it here so the market titles (which add a word) still match.
    settings = ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663}, match=MatchSettings(threshold=0.45), compliance=RULES)
    result = scan("x", [supplier], market, FX, settings)

    assert result.source_count == 4
    titles = {o.source.title for o in result.opportunities}
    assert titles == {"실리콘 주방 집게 세트", "미니 휴대용 스피커 speaker"}
    dropped = {o.title: [f.category for f in flags] for o, flags in result.dropped}
    assert dropped["KF94 mask 50pcs"] == ["medical"]
    assert "food" in dropped["곰돌이 무드등 인테리어"]

    speaker = next(o for o in result.opportunities if "스피커" in o.source.title)
    by_cat = {f.category: f for f in speaker.flags}
    assert by_cat["kc_supplier"].where == "source"
    assert by_cat["radio"].where == "market" and by_cat["radio"].matched == "블루투스"
    tongs = next(o for o in result.opportunities if "집게" in o.source.title)
    assert tongs.flags == []

    table = format_table(result.opportunities)
    assert "check" in table and "kc_supplier" in table
    data = to_json(result.opportunities, query="x", source_count=4, warnings=[], fx=FX, policy=Policy(),
                   fee_rates={"naver": 0.0663}, dropped=result.dropped)
    assert data["dropped"][0]["compliance"][0]["category"] == "medical"
    assert {f["category"] for f in next(o for o in data["opportunities"] if "스피커" in o["source"]["title"])["compliance"]} == {"kc_supplier", "radio"}


def test_scan_with_default_settings_is_unfiltered():
    supplier = StaticSource("temu", [offer("KF94 mask", price=4)])
    market = StaticSource("naver", [offer("KF94 mask 마스크", "naver", price=12_900, currency="KRW", cross_border=False)])
    result = scan("x", [supplier], market, FX, ScanSettings(policy=Policy(), fee_rates={"naver": 0.0663}))
    assert len(result.opportunities) == 1 and result.dropped == []
