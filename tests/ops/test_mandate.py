import pytest

from arbitrage.ops.errors import MandateError
from arbitrage.ops.mandate import FIELDS, load_mandate, parse_mandate, pending_mandate

from .conftest import ROOT, mandate_with


def test_repo_mandate_has_every_field_and_every_required_one_is_pending():
    m = load_mandate(ROOT / "mandate.toml")
    assert m.environment == "live"
    required = [f"{s}.{k}" for s, k, _, req in FIELDS if req]
    assert m.pending_fields() == required
    assert not m.complete
    # money limits read as zero while pending: nothing is authorized
    assert m.krw("limits.max_transaction_krw") == 0
    assert m.strings("permissions.external_actions") == ()
    assert not m.permits_action_kind("supplier_purchase")
    assert m.krw("goals.target_realized_profit_krw") == 1_000_000


def test_simulated_mandate_is_complete_but_can_never_be_live():
    m = load_mandate(ROOT / "mandate.simulated.toml")
    assert m.complete
    assert m.environment == "simulated"
    assert m.permits_action_kind("supplier_purchase")
    assert m.permits_category("kitchen") and not m.permits_category("cosmetics")


def test_partial_mandate_lists_exactly_what_is_missing():
    m = mandate_with(**{"limits.max_daily_spend_krw": "pending", "funding.initial_capital_krw": "pending"})
    assert m.pending_fields() == ["funding.initial_capital_krw", "limits.max_daily_spend_krw"]
    with pytest.raises(MandateError, match="pending"):
        m.require("limits.max_daily_spend_krw")


@pytest.mark.parametrize("field, bad", [
    ("limits.max_transaction_krw", -1),
    ("limits.max_transaction_krw", 1.5),
    ("limits.max_transaction_krw", True),
    ("reserves.refund_reserve_rate", 1.2),
    ("permissions.product_categories", "kitchen"),
    ("business.operating_country", ""),
])
def test_bad_values_are_rejected(field, bad):
    with pytest.raises(MandateError, match=field):
        mandate_with(**{field: bad})


def test_unknown_external_action_and_environment_are_rejected():
    with pytest.raises(MandateError, match="unknown action"):
        mandate_with(**{"permissions.external_actions": ["borrow_money"]})
    with pytest.raises(MandateError, match="environment"):
        parse_mandate({"mandate": {"environment": "production"}})


def test_fingerprint_changes_with_values():
    assert pending_mandate().fingerprint != mandate_with(**{"limits.max_transaction_krw": 1}).fingerprint
