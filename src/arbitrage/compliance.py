"""Flag products that Korea does not let you import and resell freely.

A keyword filter, not a legal opinion: it catches the obvious cases (a Bluetooth speaker
needs 전파법 certification, a kids' toy needs KC 안전인증, a power bank has lithium
batteries, a Nike title is a brand risk) and tells you why, so a human decides. Rules are
data in ``default.toml`` under ``[compliance]`` and can be overridden with ``--config``.

Each category has a ``reason`` shown in the report, an ``action`` (``flag`` keeps the
product and notes it, ``drop`` removes it from the scan) and keyword lists. Korean keywords
match anywhere in the text (Korean has no word spacing to rely on); Latin keywords match
whole words, so "kid" does not hit "skid", unless written ``~mah`` (then ``5000mah`` matches).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .matching import clean_html
from .models import Offer

ACTIONS = ("flag", "drop")
_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class Rule:
    category: str
    reason: str
    action: str
    keywords: tuple[str, ...]
    # Matches only when every one of these also appears, e.g. "충전" only with "전기".
    requires_any: tuple[str, ...] = ()
    # Matches never fire when one of these appears, e.g. "무선" but not "무선 청소기 필터".
    unless: tuple[str, ...] = ()

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"compliance action for {self.category!r} must be one of {ACTIONS}, not {self.action!r}")


@dataclass(frozen=True)
class Flag:
    category: str
    action: str
    reason: str
    matched: str  # the keyword that fired
    where: str = "source"  # "source" or "market": whose title had the keyword

    def label(self) -> str:
        return f"{self.category}: {self.reason} ({self.matched}, {self.where})"

    def as_dict(self) -> dict:
        return {"category": self.category, "action": self.action, "reason": self.reason,
                "matched": self.matched, "where": self.where}


@dataclass(frozen=True)
class ComplianceRules:
    rules: tuple[Rule, ...]
    brand_blocklist: tuple[str, ...] = ()
    brand_action: str = "flag"
    enabled: bool = True

    @classmethod
    def from_config(cls, data: dict) -> "ComplianceRules":
        """Build from the ``[compliance]`` table of a TOML config."""
        data = dict(data)
        enabled = bool(data.pop("enabled", True))
        mode = data.pop("mode", None)  # "flag" or "drop" overrides every category's action
        brands = data.pop("brands", {}) or {}
        rules = []
        for category, spec in data.items():
            if not isinstance(spec, dict):
                raise ValueError(f"compliance.{category} must be a table")
            rules.append(Rule(
                category=category,
                reason=str(spec.get("reason", category)),
                action=str(mode or spec.get("action", "flag")),
                keywords=tuple(str(k) for k in spec.get("keywords", [])),
                requires_any=tuple(str(k) for k in spec.get("requires_any", [])),
                unless=tuple(str(k) for k in spec.get("unless", [])),
            ))
        brand_action = str(mode or brands.get("action", "flag"))
        if brand_action not in ACTIONS:
            raise ValueError(f"compliance.brands.action must be one of {ACTIONS}, not {brand_action!r}")
        return cls(tuple(rules), tuple(str(b) for b in brands.get("blocklist", [])), brand_action, enabled)

    def with_mode(self, mode: str | None) -> "ComplianceRules":
        """Copy with every action forced to ``mode`` ("flag"/"drop"), or disabled for "off"."""
        if mode is None:
            return self
        if mode == "off":
            return ComplianceRules(self.rules, self.brand_blocklist, self.brand_action, enabled=False)
        if mode not in ACTIONS:
            raise ValueError(f"compliance mode must be flag, drop or off, not {mode!r}")
        rules = tuple(Rule(r.category, r.reason, mode, r.keywords, r.requires_any, r.unless) for r in self.rules)
        return ComplianceRules(rules, self.brand_blocklist, mode, self.enabled)


def _text(offer: Offer) -> str:
    return " ".join(filter(None, (offer.title, offer.brand, offer.model)))


def contains(text: str, keyword: str) -> bool:
    """Case-insensitive; substring for Korean and for keywords written ``~like-this``, whole word otherwise."""
    text = clean_html(text).lower()
    keyword = keyword.lower()
    if keyword.startswith("~"):
        return keyword[1:] in text
    if _HANGUL.search(keyword):
        return keyword in text
    return re.search(rf"(?<![0-9a-z]){re.escape(keyword)}(?![0-9a-z])", text) is not None


def first_hit(text: str, keywords) -> str | None:
    for keyword in keywords:
        if contains(text, keyword):
            return keyword
    return None


def check_text(text: str, rules: ComplianceRules, where: str = "source") -> list[Flag]:
    flags = []
    if not rules.enabled:
        return flags
    for rule in rules.rules:
        hit = first_hit(text, rule.keywords)
        if hit is None:
            continue
        if rule.requires_any and first_hit(text, rule.requires_any) is None:
            continue
        if first_hit(text, rule.unless) is not None:
            continue
        flags.append(Flag(rule.category, rule.action, rule.reason, hit, where))
    brand = first_hit(text, rules.brand_blocklist)
    if brand is not None:
        flags.append(Flag("brand", rules.brand_action, "brand on the blocklist (counterfeit/IP risk)", brand, where))
    return flags


def check(offer: Offer, rules: ComplianceRules, where: str = "source") -> list[Flag]:
    """Every rule the offer's title, brand or model trips."""
    return check_text(_text(offer), rules, where)


def should_drop(flags) -> bool:
    return any(f.action == "drop" for f in flags)
