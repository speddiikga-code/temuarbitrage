"""Decide whether two listings are the same physical product.

Signals, strongest first:
- a shared model code (WH-1000XM5, A2337, ...);
- a near-identical product image (resellers usually reuse the supplier's photos);
- title similarity, brand.

Different pack sizes, brands or model codes reject the pair outright: a missed
opportunity is cheap, listing the wrong product is not.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from .models import MatchResult, Offer

_TAG = re.compile(r"<[^>]+>")
_TOKEN = re.compile(r"[0-9a-z]+|[가-힣]+|[一-鿿]+")
_CODE_CANDIDATE = re.compile(r"[A-Za-z0-9]+(?:[-_/.][A-Za-z0-9]+)*")
_UNIT = re.compile(
    r"\d+(?:\.\d+)?(?:ML|L|G|KG|MG|CM|MM|M|GB|TB|MB|MAH|W|KW|V|HZ|PCS|PC|P|EA|OZ|LB|INCH|IN|K|X\d+)"
)
_SPEC = re.compile(r"(?:USB|WIFI|BT|HDMI|DDR|PD|QC|IPX?|LTE|TYPE[AC])\d*[A-Z]?\d*")
_PACK_PATTERNS = (
    re.compile(r"(\d{1,3})\s*(?:개입|개(?!월)|팩|세트|입)"),
    re.compile(r"(?<![0-9a-z])(\d{1,3})\s*(?:pcs|pc|ea|set|pack|p)(?![a-z])", re.I),
    re.compile(r"(?<![0-9a-z])[x×]\s*(\d{1,3})(?![0-9])", re.I),
)
_PLUS = re.compile(r"(?<!\d)(\d)\s*\+\s*(\d)(?!\d)")
_STOPWORDS = {
    "무료배송", "당일발송", "당일출고", "정품", "국내", "국내배송", "해외", "직구", "해외직구",
    "구매대행", "특가", "할인", "세일", "신상", "신제품", "최신", "최신형", "인기", "추천",
    "best", "new", "hot", "sale", "free", "shipping", "the", "for", "and", "with",
}


def clean_html(text: str) -> str:
    return html.unescape(_TAG.sub("", text)).strip()


def tokens(title: str) -> list[str]:
    return [t for t in _TOKEN.findall(clean_html(title).lower()) if t not in _STOPWORDS]


def model_codes(title: str) -> set[str]:
    """Tokens that look like manufacturer model numbers: letters + digits, not units or specs."""
    codes = set()
    for raw in _CODE_CANDIDATE.findall(clean_html(title)):
        code = re.sub(r"[-_/.]", "", raw).upper()
        if len(code) < 4 or not re.search(r"[A-Z]", code) or not re.search(r"\d", code):
            continue
        if _UNIT.fullmatch(code) or _SPEC.fullmatch(code):
            continue
        codes.add(code)
    return codes


def pack_count(title: str) -> int:
    """Units in one listing: "5개입" -> 5, "1+1" -> 2, "x3" -> 3, nothing -> 1."""
    text = clean_html(title)
    counts = [int(a) + int(b) for a, b in _PLUS.findall(text)]
    for pattern in _PACK_PATTERNS:
        counts += [int(n) for n in pattern.findall(text)]
    counts = [n for n in counts if 0 < n <= 100]
    return max(counts, default=1)


def _bigrams(text: str) -> set[str]:
    squashed = "".join(text.split())
    return {squashed[i : i + 2] for i in range(len(squashed) - 1)}


def title_similarity(a: str, b: str) -> float:
    """0..1. Token overlap plus character bigrams, so "블루투스이어폰" ~ "블루투스 이어폰"."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    shared = len(ta & tb)
    token_score = (shared / len(ta | tb) + shared / min(len(ta), len(tb))) / 2
    ba, bb = _bigrams(" ".join(sorted(ta))), _bigrams(" ".join(sorted(tb)))
    dice = 2 * len(ba & bb) / (len(ba) + len(bb)) if ba and bb else 0.0
    return (token_score + dice) / 2


@dataclass(frozen=True)
class MatchSettings:
    threshold: float = 0.55
    image_max_distance: int = 10


def _norm(text: str) -> str:
    return re.sub(r"\W", "", text).lower()


def match(a: Offer, b: Offer, hasher=None, settings: MatchSettings = MatchSettings()) -> MatchResult:
    """Score how likely `a` and `b` are the same product. `hasher` is an images.ImageHasher or None."""
    pa, pb = pack_count(a.title), pack_count(b.title)
    if pa != pb:
        return MatchResult(0.0, (f"pack size differs ({pa} vs {pb})",))
    if a.brand and b.brand and _norm(a.brand) != _norm(b.brand):
        return MatchResult(0.0, (f"different brand ({a.brand} vs {b.brand})",))

    codes_a = model_codes(a.title) | model_codes(a.model or "")
    codes_b = model_codes(b.title) | model_codes(b.model or "")
    score = 0.0
    reasons: list[str] = []
    if codes_a & codes_b:
        score += 0.5
        reasons.append("model " + ",".join(sorted(codes_a & codes_b)))
    elif codes_a and codes_b:
        return MatchResult(0.0, ("different model codes",))

    sim = title_similarity(a.title, b.title)
    score += 0.6 * sim
    reasons.append(f"title {sim:.2f}")

    if a.brand and b.brand:
        score += 0.1
        reasons.append("same brand")

    if hasher is not None and a.image_url and b.image_url:
        distance = hasher.distance(a.image_url, b.image_url)
        if distance is not None:
            if distance <= settings.image_max_distance // 2:
                score += 0.5
            elif distance <= settings.image_max_distance:
                score += 0.3
            reasons.append(f"image distance {distance}")

    return MatchResult(min(score, 1.0), tuple(reasons))
