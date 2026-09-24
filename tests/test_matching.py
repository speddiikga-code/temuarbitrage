import pytest

from arbitrage.matching import MatchSettings, clean_html, match, model_codes, pack_count, title_similarity
from arbitrage.models import Offer


def offer(title, brand=None, image=None, model=None):
    return Offer("t", title, 1000, "KRW", f"https://x/{title}", image_url=image, brand=brand, model=model)


class FakeHasher:
    def __init__(self, distance):
        self._distance = distance

    def distance(self, a, b):
        return self._distance


@pytest.mark.parametrize(
    "title, expected",
    [
        ("소니 WH-1000XM5 무선 헤드폰", {"WH1000XM5"}),
        ("Apple 맥북 에어 A2337 13인치", {"A2337"}),
        ("스텐 텀블러 500ml 2024 신상", set()),
        ("USB3.0 허브 4포트 IPX7 방수", set()),
        ("64GB 메모리 1080p 5000mAh", set()),
    ],
)
def test_model_codes(title, expected):
    assert model_codes(title) == expected


@pytest.mark.parametrize(
    "title, expected",
    [
        ("국산 양말 5개입", 5),
        ("1+1 스텐 텀블러", 2),
        ("텀블러", 1),
        ("kitchen tongs x3", 3),
        ("Silicone tongs 2pcs", 2),
        ("3개월 사용 가능 필터", 1),
        ("1080p 웹캠", 1),
    ],
)
def test_pack_count(title, expected):
    assert pack_count(title) == expected


def test_clean_html_strips_tags_and_entities():
    assert clean_html("뒤집개 <b>집게</b> &amp; 세트") == "뒤집개 집게 & 세트"


def test_title_similarity_handles_korean_spacing():
    assert title_similarity("블루투스이어폰 무선 충전", "무선 충전 블루투스 이어폰") > 0.6
    assert title_similarity("블루투스 이어폰 무선", "스텐 전기포트 1.7L") < 0.2


def test_shared_model_code_matches_despite_different_wording():
    a = offer("WH-1000XM5 Wireless Noise Cancelling Headphones")
    b = offer("소니 WH1000XM5 노이즈캔슬링 헤드폰 블랙")
    result = match(a, b)
    assert result.score >= 0.55
    assert "model WH1000XM5" in result.reasons


def test_different_model_codes_reject():
    assert match(offer("소니 WH-1000XM5 헤드폰"), offer("소니 WH-1000XM4 헤드폰")).score == 0


def test_pack_size_mismatch_rejects():
    result = match(offer("실리콘 주방 집게 2개입"), offer("실리콘 주방 집게"))
    assert result.score == 0
    assert "pack size" in result.reasons[0]


def test_brand_mismatch_rejects():
    assert match(offer("무선 청소기", brand="다이슨"), offer("무선 청소기", brand="샤오미")).score == 0


def test_near_identical_titles_match_without_other_signals():
    assert match(offer("실리콘 주방 뒤집개 집게 세트"), offer("실리콘 주방 뒤집개 & 집게 세트")).score >= 0.55


def test_same_category_different_product_does_not_match():
    assert match(offer("실리콘 주방 집게 세트"), offer("스텐 주방 가위 세트")).score < 0.55


def test_same_image_matches_translated_titles():
    a = offer("주방 실리콘 요리 집게 내열", image="a.jpg")
    b = offer("요리용 집게 실리콘 논슬립 주방용품", image="b.jpg")
    assert match(a, b).score < 0.55
    assert match(a, b, FakeHasher(3)).score >= 0.55
    assert match(a, b, FakeHasher(40)).score < 0.55


def test_image_threshold_is_configurable():
    a, b = offer("집게", image="a.jpg"), offer("요리 도구", image="b.jpg")
    loose = MatchSettings(image_max_distance=30)
    assert match(a, b, FakeHasher(12), loose).score > match(a, b, FakeHasher(12)).score
