import pytest

from arbitrage.ops.errors import MandateError
from arbitrage.ops.mandate import FIELDS, load_mandate, parse_mandate, pending_mandate, required_fields

from .conftest import ROOT, mandate_with


def test_repo_mandate_has_every_field_and_every_required_one_is_pending():
    m = load_mandate(ROOT / "mandate.toml")
    assert m.environment == "live"
    # the owner switched the business to the router: that is the one decided field; everything the router needs is pending
    assert m.domain == "compute_router"
    required = [name for name in required_fields("compute_router") if name != "business.domain"]
    assert m.pending_fields() == required
    assert "router.providers" in required and "connections.storefronts" not in required
    assert not m.complete
    # money limits read as zero while pending: nothing is authorized
    assert m.krw("limits.max_transaction_krw") == 0
    assert m.strings("permissions.external_actions") == ()
    assert not m.permits_action_kind("supplier_purchase")
    assert m.krw("goals.target_realized_profit_krw") == 1_000_000


def test_simulated_mandate_is_complete_but_can_never_be_live():
    m = load_mandate(ROOT / "mandate.simulated.toml")
    assert m.complete and m.domain == "ecommerce"
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


def test_domain_decides_which_fields_are_required():
    every = required_fields(None)
    assert set(required_fields("ecommerce")) | set(required_fields("compute_router")) == set(every)
    assert "limits.max_inventory_value_krw" in required_fields("ecommerce") and "limits.max_inventory_value_krw" not in required_fields("compute_router")
    assert "router.billing_modes" in required_fields("compute_router") and "router.billing_modes" not in required_fields("ecommerce")
    assert set(FIELDS) and pending_mandate().pending_fields() == [n for n in every]   # no domain yet: everything pending
    with pytest.raises(MandateError, match="business.domain"):
        mandate_with(**{"business.domain": "banking"})
    with pytest.raises(MandateError, match="billing_modes"):
        mandate_with(**{"router.billing_modes": ["barter"]})
    with pytest.raises(MandateError, match="permitted_task_types"):
        mandate_with(**{"router.permitted_task_types": ["mining"]})


def test_fingerprint_changes_with_values():
    assert pending_mandate().fingerprint != mandate_with(**{"limits.max_transaction_krw": 1}).fingerprint
