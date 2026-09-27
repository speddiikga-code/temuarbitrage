"""The owner's operating mandate: what the business may do, with how much, and where the money may go.

`mandate.toml` holds every field from the owner's brief.  A value that is the literal string "pending"
has not been decided yet.  Nothing here fills a value in: the policy controller and the budget governor
refuse live actions while any required field is pending, and a zero limit refuses everything too.

Only the owner changes the mandate, by editing the file.  Agents cannot raise limits, add funding sources
or change payout destinations, because no code path writes this file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import LIVE, MODES, SIMULATED, fingerprint
from .errors import MandateError

PENDING = "pending"

# (section, key, type, required).  Types: str, str_list, krw (non-negative int), rate (0..1), int, days.
FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("business", "operating_country", "str", True),
    ("business", "business_identity", "str", True),
    ("business", "target_markets", "str_list", True),
    ("connections", "storefronts", "str_list", True),
    ("connections", "marketplaces", "str_list", True),
    ("connections", "suppliers", "str_list", True),
    ("connections", "payment_processors", "str_list", True),
    ("funding", "funding_sources", "str_list", True),
    ("funding", "payout_destinations", "str_list", True),
    ("funding", "initial_capital_krw", "krw", True),
    ("funding", "authorized_operating_expenses_krw", "krw", True),
    ("limits", "max_transaction_krw", "krw", True),
    ("limits", "max_daily_spend_krw", "krw", True),
    ("limits", "max_total_exposure_krw", "krw", True),
    ("limits", "max_cumulative_loss_krw", "krw", True),
    ("limits", "max_inventory_value_krw", "krw", True),
    ("limits", "max_sku_exposure_krw", "krw", True),
    ("reserves", "min_cash_reserve_krw", "krw", True),
    ("reserves", "refund_reserve_rate", "rate", True),
    ("reserves", "refund_reserve_days", "days", True),
    ("reserves", "dispute_reserve_rate", "rate", True),
    ("reinvestment", "reinvestment_rate", "rate", True),
    ("budgets", "ai_credit_budget", "int", True),
    ("budgets", "infrastructure_budget_krw", "krw", True),
    ("permissions", "product_categories", "str_list", True),
    ("permissions", "external_actions", "str_list", True),
    ("goals", "target_realized_profit_krw", "krw", False),
)

# What the mandate's `external_actions` list may contain, and which action kinds each word covers.
EXTERNAL_ACTIONS: dict[str, tuple[str, ...]] = {
    "purchase_inventory": ("supplier_purchase",),
    "purchase_samples": ("sample_purchase",),
    "pay_supplier": ("supplier_payment",),
    "buy_shipping": ("shipping_purchase",),
    "pay_software": ("software_expense",),
    "pay_infrastructure": ("infrastructure_expense",),
    "run_ads": ("advertising",),
    "collect_payment": ("customer_payment",),
    "issue_refund": ("refund",),
    "reinvest": ("reinvestment",),
    "list_products": ("listing",),
}


@dataclass(frozen=True)
class Mandate:
    environment: str                 # 'live' (the owner's real mandate) or 'simulated' (test numbers only)
    path: str
    values: dict[str, Any]           # "section.key" -> parsed value, or PENDING
    schema_version: int = 1
    fingerprint: str = ""
    notes: dict[str, str] = field(default_factory=dict)

    # -- state ---------------------------------------------------------------------------------------

    def pending_fields(self) -> list[str]:
        return [f"{s}.{k}" for s, k, _, required in FIELDS if required and self.values.get(f"{s}.{k}") == PENDING]

    @property
    def complete(self) -> bool:
        return not self.pending_fields()

    def get(self, name: str, default=None):
        value = self.values.get(name, PENDING)
        return default if value == PENDING else value

    def require(self, name: str):
        value = self.values.get(name, PENDING)
        if value == PENDING:
            raise MandateError(f"mandate field {name} is pending")
        return value

    # -- typed accessors used by the services --------------------------------------------------------

    def krw(self, name: str) -> int:
        """A money limit. Pending counts as zero, so an unfinished mandate authorizes nothing."""
        value = self.values.get(name, PENDING)
        return 0 if value == PENDING else int(value)

    def rate(self, name: str) -> float:
        value = self.values.get(name, PENDING)
        return 0.0 if value == PENDING else float(value)

    def days(self, name: str) -> int:
        value = self.values.get(name, PENDING)
        return 0 if value == PENDING else int(value)

    def strings(self, name: str) -> tuple[str, ...]:
        value = self.values.get(name, PENDING)
        return () if value == PENDING else tuple(value)

    def permits_action_kind(self, kind: str) -> bool:
        allowed = self.strings("permissions.external_actions")
        return any(kind in EXTERNAL_ACTIONS.get(word, ()) for word in allowed)

    def permits_category(self, category: str | None) -> bool:
        if category is None:
            return True
        return category in self.strings("permissions.product_categories")

    def summary(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "path": self.path,
            "schema_version": self.schema_version,
            "complete": self.complete,
            "pending_fields": self.pending_fields(),
            "fingerprint": self.fingerprint,
            "values": {k: v for k, v in self.values.items()},
        }


def _parse(name: str, kind: str, raw: Any) -> Any:
    if raw == PENDING:
        return PENDING
    try:
        if kind == "str":
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("expected a non-empty string")
            return raw.strip()
        if kind == "str_list":
            if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
                raise ValueError("expected a list of strings")
            return [x.strip() for x in raw]
        if kind in ("krw", "int", "days"):
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError("expected a non-negative integer")
            return int(raw)
        if kind == "rate":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= float(raw) <= 1:
                raise ValueError("expected a number between 0 and 1")
            return float(raw)
    except ValueError as e:
        raise MandateError(f"mandate field {name}: {e} (got {raw!r})") from None
    raise MandateError(f"unknown field type {kind} for {name}")


def parse_mandate(data: dict[str, Any], path: str = "<memory>") -> Mandate:
    if not isinstance(data, dict):
        raise MandateError("mandate must be a table")
    meta = data.get("mandate", {})
    environment = meta.get("environment", PENDING)
    if environment not in MODES:
        raise MandateError(f"mandate.environment must be '{LIVE}' or '{SIMULATED}', not {environment!r}")
    version = int(meta.get("schema_version", 1))
    values: dict[str, Any] = {}
    for section, key, kind, required in FIELDS:
        raw = data.get(section, {}).get(key, PENDING)
        values[f"{section}.{key}"] = _parse(f"{section}.{key}", kind, raw)
    for word in values.get("permissions.external_actions", []) if values["permissions.external_actions"] != PENDING else []:
        if word not in EXTERNAL_ACTIONS:
            raise MandateError(f"permissions.external_actions: unknown action {word!r}; known: {', '.join(EXTERNAL_ACTIONS)}")
    if values["goals.target_realized_profit_krw"] == PENDING:
        values["goals.target_realized_profit_krw"] = 1_000_000
    return Mandate(environment=environment, path=str(path), values=values, schema_version=version,
                   fingerprint=fingerprint({"environment": environment, "values": values}))


def load_mandate(path: str | Path) -> Mandate:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise MandateError(f"can't read mandate {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise MandateError(f"mandate {path} is not valid TOML: {e}") from e
    return parse_mandate(data, str(path))


def pending_mandate(environment: str = LIVE) -> Mandate:
    """Every required field pending: what the repo ships with, and what fails closed in tests."""
    return parse_mandate({"mandate": {"environment": environment}}, "<pending>")
