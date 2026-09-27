"""Owner acceptance checks: an incomplete or zero mandate fails closed, pauses block only new commitments,
concurrent reservations cannot exceed a shared limit, and retained-profit allocations cannot be reused."""

import threading

import pytest

from arbitrage.ops import ledger as L
from arbitrage.ops.books import Order
from arbitrage.ops.core import build
from arbitrage.ops.errors import BudgetExceeded, PolicyRefused
from arbitrage.ops.policy import ActionRequest

from .conftest import mandate_with

SIM, LIVE = "simulated", "live"


def req(kind="supplier_purchase", mode=SIM, amount=50_000, key="k1", **kw):
    return ActionRequest(kind, key, mode, amount_krw=amount, amount=amount, **kw)


def fund(core, amount=1_000_000, mode=SIM):
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, mode, amount, "simulated:bank", f"cap:{mode}:{amount}")


# -- fail closed ------------------------------------------------------------------------------------------

def test_pending_live_mandate_refuses_every_live_action_and_reservation(db, pending):
    core = build(db, pending)
    with core.db.transaction() as tx:
        d = core.policy.evaluate(tx, req(mode=LIVE, integration="aliexpress"))
    assert not d.allowed
    assert any("pending field" in r for r in d.reasons)
    assert any("not permit" in r for r in d.reasons)
    with pytest.raises(BudgetExceeded, match="pending"):
        core.governor.reserve(LIVE, 1, "inventory", "initial_capital")
    # even the simulated path finds nothing to spend: pending limits read as zero
    with pytest.raises(BudgetExceeded, match="transaction limit 0"):
        core.governor.reserve(SIM, 1, "inventory", "initial_capital")


def test_zero_mandate_authorizes_nothing(db):
    zero = mandate_with(**{"limits.max_transaction_krw": 0, "funding.initial_capital_krw": 0})
    core = build(db, zero)
    fund(core)
    with pytest.raises(BudgetExceeded):
        core.governor.reserve(SIM, 1, "inventory", "initial_capital")
    with core.db.transaction() as tx:
        assert not core.policy.evaluate(tx, req(amount=1)).allowed


def test_simulated_mandate_can_never_authorize_live(db, simulated_mandate):
    core = build(db, simulated_mandate)
    with core.db.transaction() as tx:
        d = core.policy.evaluate(tx, req(mode=LIVE, integration="simulated:aliexpress"))
    assert not d.allowed and any("cannot authorize live" in r for r in d.reasons)
    with pytest.raises(BudgetExceeded, match="cannot fund live"):
        core.governor.reserve(LIVE, 1000, "inventory", "initial_capital")


def test_policy_checks_kind_category_limit_and_adapter(db, simulated_mandate):
    core = build(db, simulated_mandate)
    with core.db.transaction() as tx:
        assert core.policy.evaluate(tx, req(category="kitchen", integration="simulated:aliexpress")).allowed
        assert not core.policy.evaluate(tx, req(category="cosmetics")).allowed
        assert not core.policy.evaluate(tx, req(amount=200_001)).allowed
        assert core.policy.evaluate(tx, req(kind="customer_payment", amount=5_000_000)).allowed  # not our spend
        assert not core.policy.evaluate(tx, req(kind="refund", amount=5_000_000)).allowed
        assert not core.policy.evaluate(tx, req(kind="borrow")).allowed
        d = core.policy.evaluate(tx, req(integration="aliexpress"))
        assert not d.allowed and "simulated adapter" in d.reasons[0]
    assert core.audit.verify()[0]


# -- pauses -----------------------------------------------------------------------------------------------

def test_purchasing_pause_blocks_new_commitments_but_not_existing_obligations(db, simulated_mandate):
    core = build(db, simulated_mandate)
    pid = core.pause("purchasing", "owner review", "owner")
    assert core.pause("purchasing", "again", "owner") == pid  # one active pause per scope and kind
    with core.db.transaction() as tx:
        for kind in ("supplier_purchase", "advertising", "reinvestment", "listing"):
            d = core.policy.evaluate(tx, req(kind=kind, key=kind))
            assert not d.allowed and "paused" in d.reasons[0], kind
        for kind in ("fulfillment", "refund", "customer_payment", "shipping_purchase", "customer_support"):
            assert core.policy.evaluate(tx, req(kind=kind, key=kind, amount=1000)).allowed, kind
    core.pause("all", "stop everything", "owner")
    with core.db.transaction() as tx:
        assert not core.policy.evaluate(tx, req(kind="fulfillment", amount=0)).allowed
    assert core.resume(pid, "owner")
    assert not core.resume(pid, "owner")


def test_guardrails_pause_purchasing_automatically_and_do_not_lift_themselves(db, simulated_mandate):
    core = build(db, simulated_mandate)
    fund(core, 100_000)  # below the 200,000 minimum cash reserve
    with core.db.transaction() as tx:
        result = core.guardrails.evaluate(tx, SIM)
    assert "cash_below_reserve" in result.triggered
    with core.db.transaction() as tx:
        again = core.guardrails.evaluate(tx, SIM)
        assert again.pauses == result.pauses  # same pause, not a second one
        assert not core.policy.evaluate(tx, req()).allowed
        assert core.policy.evaluate(tx, req(kind="fulfillment", amount=0)).allowed
    fund(core, 900_000)
    with core.db.transaction() as tx:
        assert core.guardrails.evaluate(tx, SIM).triggered == []
        assert len(core.pauses.active(tx)) == 1  # the owner resumes; the system does not


def test_loss_limit_pauses_and_refuses_reservations(db, simulated_mandate):
    core = build(db, simulated_mandate)
    fund(core)
    with core.db.transaction() as tx:
        core.books.record_expense(tx, SIM, L.ADVERTISING, 160_000, "burned on ads", "ads:1")
        assert "loss_limit_exceeded" in core.guardrails.evaluate(tx, SIM).triggered
    with pytest.raises(BudgetExceeded, match="cumulative loss"):
        core.governor.reserve(SIM, 10_000, "inventory", "initial_capital")


# -- headroom and reservations -----------------------------------------------------------------------------

def test_headroom_formula(db, simulated_mandate):
    core = build(db, simulated_mandate)
    fund(core)
    with core.db.transaction() as tx:
        h = core.governor.headroom(tx, SIM)
        # 1,000,000 settled − 0 commitments − (200,000 min cash + 50,000 operating reserve)
        assert h.available == 750_000
        r = core.governor.reserve(SIM, 100_000, "inventory", "initial_capital", tx=tx)
        h = core.governor.headroom(tx, SIM)
        assert h.reserved_by_workflows == 100_000 and h.available == 650_000
        assert core.governor.exposure(tx, SIM) == 100_000
        core.governor.commit(tx, r.id, 90_000)
        assert core.governor.headroom(tx, SIM).reserved_by_workflows == 0  # committed money shows up in the ledger instead
        with pytest.raises(BudgetExceeded, match="was committed"):
            core.governor.release(tx, r.id)
        r2 = core.governor.reserve(SIM, 50_000, "inventory", "initial_capital", tx=tx)
        with pytest.raises(BudgetExceeded, match="outside the reserved"):
            core.governor.commit(tx, r2.id, 50_001)
        core.governor.release(tx, r2.id, reason="cancelled")
        assert core.governor.daily_spend(tx, SIM) == 90_000
        assert core.governor.initial_capital_remaining(tx, SIM) == 910_000


def test_limits_each_refuse(db):
    m = mandate_with(**{"limits.max_sku_exposure_krw": 60_000, "limits.max_inventory_value_krw": 120_000})
    core = build(db, m)
    fund(core)
    with pytest.raises(BudgetExceeded, match="transaction limit"):
        core.governor.reserve(SIM, 200_001, "inventory", "initial_capital")
    with pytest.raises(BudgetExceeded, match="per-product limit"):
        core.governor.reserve(SIM, 60_001, "inventory", "initial_capital", sku="tongs")
    core.governor.reserve(SIM, 60_000, "inventory", "initial_capital", sku="tongs")
    core.governor.reserve(SIM, 60_000, "inventory", "initial_capital", sku="mount")
    with pytest.raises(BudgetExceeded, match="inventory limit"):
        core.governor.reserve(SIM, 1, "inventory", "initial_capital", sku="cable")
    core.governor.reserve(SIM, 100_000, "advertising", "initial_capital")  # not inventory: only the other limits apply
    with pytest.raises(BudgetExceeded, match="daily limit"):
        core.governor.reserve(SIM, 200_000, "advertising", "initial_capital")


def test_concurrent_reservations_cannot_exceed_the_shared_daily_limit(db, simulated_mandate):
    """Eight workers race for 150,000 each; the daily limit is 400,000, so exactly two may win."""
    core = build(db, simulated_mandate)
    fund(core)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        try:
            results.append(core.governor.reserve(SIM, 150_000, "advertising", "initial_capital", actor=f"w{i}"))
        except BudgetExceeded as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 2 and len(errors) == 6
    with core.db.transaction() as tx:
        assert core.governor.daily_spend(tx, SIM) == 300_000
    assert all("daily limit" in e for e in errors)


def test_retained_profit_allocations_cannot_be_reused(db):
    """Reinvestment draws on realized profit once: two reservations cannot both spend the same earnings."""
    m = mandate_with(**{"reinvestment.reinvestment_rate": 1.0, "reserves.min_cash_reserve_krw": 0,
                        "funding.authorized_operating_expenses_krw": 0, "reserves.refund_reserve_rate": 0.0,
                        "reserves.dispute_reserve_rate": 0.0})
    core = build(db, m)
    fund(core, 100_000)
    with core.db.transaction() as tx:
        assert core.governor.reinvestment_budget(tx, SIM).budget == 0  # no realized profit: nothing to reinvest
        with pytest.raises(BudgetExceeded, match="reinvestment budget 0"):
            core.governor.reserve(SIM, 1, "inventory", "reinvestment", tx=tx)
        # a closed, settled order with 40,000 of profit
        o = Order("ord_1", "simulated:naver", "N1", "tongs", 1, 60_000, 0, 0, 0, SIM)
        tx.insert("orders", {"id": o.id, "channel": o.channel, "external_order_id": "N1", "sku": "tongs", "quantity": 1,
                             "gross_amount": 60_000, "discount": 0, "tax_collected": 0, "expected_fee": 0, "currency": "KRW",
                             "import_mode": "commercial_resale", "placed_at": "2026-09-01T00:00:00+00:00", "status": "closed", "mode": SIM})
        core.books.pay_supplier(tx, SIM, "pur_1", 20_000, 0, "pur_1:paid")
        core.books.receive_inventory(tx, SIM, "pur_1", "tongs", 1, 20_000, 0, 0, "pur_1:received")
        core.books.record_sale(tx, o)
        core.books.record_fulfillment(tx, o, 0)
        core.books.record_settlement(tx, o, 60_000, 0, 0, "settle:1")
        rb = core.governor.reinvestment_budget(tx, SIM)
        assert rb.realized_profit == 40_000 and rb.eligible_unallocated == 40_000 and rb.budget == 40_000
        first = core.governor.reserve(SIM, 30_000, "inventory", "reinvestment", tx=tx)
        rb = core.governor.reinvestment_budget(tx, SIM)
        assert rb.already_allocated == 30_000 and rb.budget == 10_000
        with pytest.raises(BudgetExceeded, match="reinvestment budget 10,000"):
            core.governor.reserve(SIM, 30_000, "inventory", "reinvestment", tx=tx)
        core.governor.commit(tx, first.id, 30_000)
        assert core.governor.reinvestment_budget(tx, SIM).budget == 10_000  # spent allocations stay allocated
        core.governor.reserve(SIM, 10_000, "inventory", "reinvestment", tx=tx)
        assert core.governor.reinvestment_budget(tx, SIM).budget == 0
        # initial capital is a separate pool with its own ceiling
        assert core.governor.initial_capital_remaining(tx, SIM) == 1_000_000
