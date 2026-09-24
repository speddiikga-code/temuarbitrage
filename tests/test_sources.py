import pytest

from arbitrage.errors import ConfigError, SourceError
from arbitrage.sources import AliExpress, CsvSource, NaverShopping
from arbitrage.sources.aliexpress import parse_products, sign
from arbitrage.sources.naver_shopping import parse_items

from conftest import FakeResponse, FakeSession, load_fixture


def test_naver_parse_keeps_new_items_and_cleans_titles():
    offers = parse_items(load_fixture("naver_shop.json")["items"])
    assert [o.product_id for o in offers] == ["1", "2"]  # used item and priceless item dropped
    assert offers[0].title == "소니 WH-1000XM5 무선 노이즈캔슬링 헤드폰"
    assert offers[1].title == "실리콘 주방 뒤집개 & 집게 세트"
    assert offers[1].price == 12900
    assert offers[1].brand is None
    assert not offers[0].cross_border


def test_naver_search_sends_credentials_and_paginates():
    page = {"items": load_fixture("naver_shop.json")["items"][:2] * 50}  # full page of 100
    session = FakeSession(FakeResponse(page), FakeResponse({"items": []}))
    naver = NaverShopping("id", "secret", session=session)
    offers = naver.search("집게", limit=150)
    assert len(offers) == 100
    first, second = session.calls
    assert first[2]["headers"] == {"X-Naver-Client-Id": "id", "X-Naver-Client-Secret": "secret"}
    assert first[2]["params"]["display"] == 100 and first[2]["params"]["start"] == 1
    assert second[2]["params"]["display"] == 50 and second[2]["params"]["start"] == 101


def test_naver_error_status_raises():
    session = FakeSession(FakeResponse({"errorMessage": "Authentication failed"}, status_code=401))
    with pytest.raises(SourceError, match="401"):
        NaverShopping("id", "bad", session=session).search("x")


def test_naver_requires_credentials():
    with pytest.raises(ConfigError):
        NaverShopping.from_env({})


def test_aliexpress_signature_matches_official_sdk():
    params = {
        "app_key": "12345", "method": "aliexpress.affiliate.product.query", "format": "json", "v": "2.0",
        "sign_method": "md5", "timestamp": "1700000000000", "keywords": "휴대폰 케이스", "page_no": "1",
    }
    # Computed with the sign() function of the official Taobao/AliExpress Python SDK.
    assert sign("secret", params) == "9B059398AA46005B8DF318D9182FEA49"


def test_aliexpress_parse_products():
    products = load_fixture("aliexpress_query.json")["aliexpress_affiliate_product_query_response"]["resp_result"]["result"]["products"]["product"]
    offers = parse_products(products, default_shipping=500)
    assert len(offers) == 1  # untitled product dropped
    o = offers[0]
    assert (o.price, o.currency, o.shipping, o.product_id) == (4210, "KRW", 500, "1005001")
    assert o.url == "https://www.aliexpress.com/item/1005001.html"
    assert o.cross_border


def test_aliexpress_search_signs_request():
    session = FakeSession(FakeResponse(load_fixture("aliexpress_query.json")))
    ali = AliExpress("key", "secret", tracking_id="tr", session=session, clock=lambda: 1700000000)
    offers = ali.search("집게", limit=10)
    assert len(offers) == 1
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", "https://api-sg.aliexpress.com/sync")
    system, body = kwargs["params"], kwargs["data"]
    assert system["timestamp"] == "1700000000000"
    assert body["ship_to_country"] == "KR" and body["target_currency"] == "KRW" and body["tracking_id"] == "tr"
    unsigned = {k: v for k, v in system.items() if k != "sign"}
    assert system["sign"] == sign("secret", {**unsigned, **body})


def test_aliexpress_error_response_raises():
    session = FakeSession(FakeResponse({"error_response": {"code": "IncompleteSignature", "msg": "bad sign"}}))
    with pytest.raises(SourceError, match="IncompleteSignature"):
        AliExpress("key", "secret", session=session).search("x")


def test_csv_source(fixtures_dir):
    temu, dome = CsvSource(fixtures_dir / "suppliers.csv").search("ignored", 10)
    assert (temu.platform, temu.price, temu.currency, temu.shipping, temu.cross_border) == ("temu", 3.2, "USD", 1.5, True)
    assert (dome.platform, dome.currency, dome.cross_border) == ("domeggook", "KRW", False)


def test_csv_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("title,price\nx,1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="url"):
        CsvSource(path).search("", 10)
