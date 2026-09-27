"""Owner acceptance checks on the gateway: illegal transitions are rejected, nothing is paid or received without
an external confirmation, duplicate events cannot duplicate postings or charges, an ambiguous payment must
reconcile before retry, and the whole order/payment/refund/reconciliation path runs without spending anything."""

import pytest

from arbitrage.ops import ledger as L
from arbitrage.ops.adapters import AMBIGUOUS, FAILED, SimulatedCarrier, SimulatedProcessor, SimulatedSupplier
from arbitrage.ops.core import build
from arbitrage.ops.errors import (ConfirmationRequired, IdempotencyConflict, InvalidTransition, NotConfigured, OpsError,
                                  PolicyRefused, ReconciliationRequired)
from arbitrage.ops.metrics import compute
from arbitrage.ops.policy import ActionRequest
from arbitrage.ops.purchases import PurchaseProposal

SIM = "simulated"
FX = 1365.0


def adapters():
    return {"simulated:aliexpress": SimulatedSupplier("simulated:aliexpress"),
            "simulated:naverpay": SimulatedProcessor("simulated:naverpay"),
            "simulated:cj": SimulatedCarrier("simulated:cj")}


@pytest.fixture
def core(db, simulated_mandate):
    c = build(db, simulated_mandate, adapters())
    with c.db.transaction() as tx:
        c.books.contribute_capital(tx, SIM, 1_000_000, "simulated:bank", "cap:1")
    return c


def proposal(key="po-1", qty=10, unit=3.2, shipping=1.5, **kw):
    amount_krw = round((unit * qty + shipping) * FX)
    defaults = dict(idempotency_key=key, supplier="simulated:aliexpress", sku="tongs", quantity=qty, unit_price=unit,
                    currency="USD", shipping=shipping, fx_rate=FX, amount_krw=amount_krw, duty_krw=round(amount_krw * 0.188),
                    category="kitchen", import_basis="commercial_resale",
                    price_evidence={"source": "smartstore listing", "url": "https://smartstore.naver.com/x/products/1", "date": "2026-09-27"})
    defaults.update(kw)
    return PurchaseProposal(**defaults)


def quote(**kw):
    q = {"sku": "tongs", "quantity": 10, "in_stock": True, "unit_price": 3.2, "currency": "USD", "shipping": 1.5,
         "delivery_days": 12, "destination": "KR"}
    q.update(kw)
    return q


def event(order_id, kind, ref, **kw):
    return {"source": "simulated:naverpay", "kind": kind, "reference": ref, "mode": SIM, "order_id": order_id, **kw}


# -- state machines ----------------------------------------------------------------------------------------

def test_illegal_transitions_and_missing_confirmations_are_rejected(core):
    action = core.purchasing.propose(proposal(), SIM)
    assert action.state == "proposed"
    with core.db.transaction() as tx:
        with pytest.raises(InvalidTransition, match="cannot go from proposed to paid"):
            core.gateway.transition(tx, action.id, "paid", confirmation={"source": "simulated:aliexpress", "kind": "payment_receipt",
                                                                            "reference": "X", "mode": SIM})
        with pytest.raises(InvalidTransition, match="cannot go from proposed to reserved"):
            core.gateway.transition(tx, action.id, "reserved")
        with pytest.raises(InvalidTransition, match="no state"):
            core.gateway.transition(tx, action.id, "teleported")
        core.gateway.transition(tx, action.id, "verified")
        core.gateway.transition(tx, action.id, "reserved")
        with pytest.raises(ConfirmationRequired, match="needs a supplier_order confirmation"):
            core.gateway.transition(tx, action.id, "ordered")
        with pytest.raises(ConfirmationRequired, match="needs a supplier_order confirmation, got payment_receipt"):
            core.gateway.transition(tx, action.id, "ordered", confirmation={"source": "simulated:aliexpress", "kind": "payment_receipt",
                                                                               "reference": "P1", "mode": SIM})
        with pytest.raises(OpsError, match="accepts only simulated confirmations"):
            core.gateway.transition(tx, action.id, "ordered", confirmation={"source": "aliexpress", "kind": "supplier_order",
                                                                               "reference": "PO1", "mode": SIM})
        with pytest.raises(OpsError, match="cannot advance a simulated action"):
            core.gateway.transition(tx, action.id, "ordered", confirmation={"source": "aliexpress", "kind": "supplier_order",
                                                                               "reference": "PO1", "mode": "live"})
        assert core.gateway.get(tx, action.id).state == "reserved"


def test_idempotency_key_returns_the_same_action_and_refuses_a_different_request(core):
    a = core.purchasing.propose(proposal(), SIM)
    assert core.purchasing.propose(proposal(), SIM).id == a.id
    with pytest.raises(IdempotencyConflict):
        core.purchasing.propose(proposal(qty=11), SIM)
    with core.db.transaction() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM actions") == 1


def test_one_confirmation_cannot_advance_two_actions(core):
    a = core.purchasing.propose(proposal("po-a"), SIM)
    b = core.purchasing.propose(proposal("po-b"), SIM)
    conf = {"source": "simulated:aliexpress", "kind": "supplier_order", "reference": "PO-SHARED", "mode": SIM}
    with core.db.transaction() as tx:
        for x in (a, b):
            core.gateway.transition(tx, x.id, "verified")
            core.gateway.transition(tx, x.id, "reserved")
        core.gateway.transition(tx, a.id, "ordered", confirmation=conf)
        assert core.gateway.transition(tx, a.id, "ordered", confirmation=conf).state == "ordered"  # redelivered: no-op
        with pytest.raises(OpsError, match="already belongs to action"):
            core.gateway.transition(tx, b.id, "ordered", confirmation=conf)
        assert len(core.gateway.transitions(tx, a.id)) == 3


# -- supplier purchases ------------------------------------------------------------------------------------

def test_verification_rejects_what_the_owner_listed(core):
    bad = core.purchasing.propose(proposal("po-bad", import_basis="personal_use", duty_krw=0), SIM)
    with pytest.raises(OpsError, match="personal use") as e:
        core.purchasing.verify(bad.id, quote(unit_price=3.4, in_stock=False, delivery_days=45))
    msg = str(e.value)
    assert "no stock" in msg and "above the proposed" in msg and "longer than 30 days" in msg and "zero duty" in msg
    with core.db.transaction() as tx:
        assert core.gateway.get(tx, bad.id).state == "rejected"
    # unknown classification, zero duty, no evidence: refused; the same with an evidence reference is allowed
    z = core.purchasing.propose(proposal("po-zero", duty_krw=0), SIM)
    with pytest.raises(OpsError, match="zero duty needs import evidence"):
        core.purchasing.verify(z.id, quote())
    ok = core.purchasing.propose(proposal("po-ev", duty_krw=0, import_evidence="KCS ruling 2026-1234"), SIM)
    assert core.purchasing.verify(ok.id, quote()).state == "verified"
    # wrong destination and a bigger price than the cap
    d = core.purchasing.propose(proposal("po-dest", destination="JP"), SIM)
    with pytest.raises(OpsError, match="destination must be KR"):
        core.purchasing.verify(d.id, quote(destination="JP"))


def test_purchase_needs_verification_reservation_and_policy_before_it_is_sent(core):
    a = core.purchasing.propose(proposal(), SIM)
    with pytest.raises(InvalidTransition, match="verified and reserved first"):
        core.purchasing.place(a.id)
    core.purchasing.verify(a.id, quote())
    with pytest.raises(InvalidTransition, match="verified and reserved first"):
        core.purchasing.place(a.id)
    core.purchasing.reserve(a.id)
    core.pause("purchasing", "owner review", "owner")
    with pytest.raises(PolicyRefused, match="paused"):
        core.purchasing.place(a.id)
    with core.db.transaction() as tx:
        assert core.gateway.get(tx, a.id).state == "reserved"
        assert core.adapters["simulated:aliexpress"].calls == []  # nothing was sent


def test_failed_supplier_order_releases_the_budget(core):
    core.adapters["simulated:aliexpress"].script("supplier_order", FAILED)
    a = core.purchasing.propose(proposal(), SIM)
    core.purchasing.verify(a.id, quote())
    core.purchasing.reserve(a.id)
    a = core.purchasing.place(a.id)
    assert a.state == "failed"
    with core.db.transaction() as tx:
        assert core.governor.get(tx, a.reservation_id).state == "released"
        assert core.governor.headroom(tx, SIM).reserved_by_workflows == 0
        assert core.ledger.balance(tx, L.PREPAID, SIM) == 0


def test_ambiguous_payment_must_reconcile_before_retry(core):
    supplier = core.adapters["simulated:aliexpress"]
    supplier.script("supplier_order", AMBIGUOUS)
    a = core.purchasing.propose(proposal(), SIM)
    core.purchasing.verify(a.id, quote())
    core.purchasing.reserve(a.id)
    with pytest.raises(ReconciliationRequired):
        core.purchasing.place(a.id)
    with core.db.transaction() as tx:
        a = core.gateway.get(tx, a.id)
        assert a.state == "payment_unknown"
        assert core.governor.get(tx, a.reservation_id).state == "reserved"  # still held: the money may have left
        assert core.ledger.balance(tx, L.PREPAID, SIM) == 0                # but nothing is booked as paid
    with pytest.raises(ReconciliationRequired, match="reconcile it before retrying"):
        core.purchasing.place(a.id)
    assert sum(1 for k, _ in supplier.calls if k == "supplier_order") == 1  # the retry never reached the supplier
    a = core.purchasing.reconcile(a.id)
    assert a.state == "paid"
    with core.db.transaction() as tx:
        assert core.governor.get(tx, a.reservation_id).state == "committed"
        assert core.ledger.balance(tx, L.PREPAID, SIM) == a.amount_krw
        assert tx.scalar("SELECT COUNT(*) FROM external_confirmations WHERE action_id = ?", (a.id,)) == 2
    assert core.purchasing.reconcile(a.id).state == "paid"  # nothing more to do


def test_ambiguous_order_that_never_existed_fails_and_frees_the_budget(core):
    supplier = core.adapters["simulated:aliexpress"]
    supplier.script("supplier_order", AMBIGUOUS)
    a = core.purchasing.propose(proposal(), SIM)
    core.purchasing.verify(a.id, quote())
    core.purchasing.reserve(a.id)
    with pytest.raises(ReconciliationRequired):
        core.purchasing.place(a.id)
    supplier.orders.clear()  # the supplier has no record of it
    a = core.purchasing.reconcile(a.id)
    assert a.state == "failed"
    with core.db.transaction() as tx:
        assert core.governor.get(tx, a.reservation_id).state == "released"


def test_live_purchase_is_impossible_without_a_live_complete_mandate_and_verified_integration(db, simulated_mandate, pending):
    from .conftest import mandate_with
    from .test_registry import entry

    live_core = build(db, pending, adapters())
    with pytest.raises(PolicyRefused, match="pending"):
        live_core.purchasing.propose(proposal("live-1", supplier="aliexpress_supplier"), "live")
    # a complete live mandate still needs a production-ready integration and a live adapter
    complete_live = mandate_with(**{"mandate.environment": "live"})
    core2 = build(db, complete_live, adapters())
    with core2.db.transaction() as tx:
        core2.books.contribute_capital(tx, "live", 1_000_000, "test:bank", "cap:live-test")  # test ledger, not real money
        core2.registry.load(tx, [entry()])  # as in integrations/registry.toml: not connected
    with pytest.raises(PolicyRefused, match="not production-ready"):
        core2.purchasing.propose(proposal("live-2", supplier="aliexpress_supplier"), "live")
    with core2.db.transaction() as tx:
        with pytest.raises(OpsError, match="needs the external reference"):
            core2.registry.mark_verified(tx, "aliexpress_supplier", "ds.order.create", "", "owner")
        core2.registry.mark_verified(tx, "aliexpress_supplier", "ds.order.create", "real-order-8812", "owner")
        assert not core2.registry.get(tx, "aliexpress_supplier")["production_ready"]  # the file still says not connected
    with pytest.raises(PolicyRefused, match="not production-ready"):
        core2.purchasing.propose(proposal("live-2", supplier="aliexpress_supplier"), "live")
    with core2.db.transaction() as tx:
        core2.registry.load(tx, [entry(status="live", connected=True)])  # the PR that records the verified operation
        assert core2.registry.get(tx, "aliexpress_supplier")["production_ready"]
    a = core2.purchasing.propose(proposal("live-2", supplier="aliexpress_supplier"), "live")
    core2.purchasing.verify(a.id, quote())
    core2.purchasing.reserve(a.id)
    with pytest.raises(NotConfigured, match="no live adapter"):
        core2.purchasing.place(a.id)
    with core2.db.transaction() as tx:
        assert core2.ledger.balance(tx, L.PREPAID, "live") == 0
        assert compute(tx, core2.ledger, "live").realized_profit == 0
        assert core2.gateway.get(tx, a.id).state == "reserved"


# -- the no-spend end-to-end path ------------------------------------------------------------------------------

def run_happy_path(core, key="po-1", order_no="N-1001"):
    """Purchase 10 units, receive them, sell one, ship it, settle, close the return window. All simulated."""
    supplier, processor, carrier = (core.adapters[k] for k in ("simulated:aliexpress", "simulated:naverpay", "simulated:cj"))
    a = core.purchasing.propose(proposal(key), SIM)
    core.purchasing.verify(a.id, quote())
    core.purchasing.reserve(a.id)
    a = core.purchasing.place(a.id)
    assert a.state == "paid"
    a = core.purchasing.mark_shipped(a.id, supplier.shipment(a.id, "PO"))
    a = core.purchasing.receive(a.id, {"source": "simulated:warehouse", "kind": "receiving", "reference": f"RCV-{key}", "mode": SIM},
                                freight_krw=0, duties_krw=a.payload["duty_krw"])
    assert a.state == "received"

    order, payment = core.payments.create_order(SIM, "simulated:naver", order_no, "tongs", 1, 22_000, 0, 2_000, 1_500,
                                                "simulated:naverpay", "commercial_resale", placed_at="2026-09-01T00:00:00+00:00")
    auth = processor.authorize(payment.id, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "authorization", auth.reference, amount=22_000))
    cap = processor.capture(payment.id, auth.reference, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "capture", cap.reference, amount=22_000))
    f = core.fulfillment.create(order.id, "simulated:cj")
    core.fulfillment.allocate(f.id)
    core.fulfillment.pack(f.id)
    f = core.fulfillment.ship(f.id, shipping_cost_krw=3_000)
    core.fulfillment.deliver(f.id, carrier.confirm_delivery(f.id, f.payload["tracking"]))
    core.payments.apply_event(event(order.id, "settlement", f"SET-{order_no}", payout=20_200, marketplace_fee=1_600, payment_fee=200))
    closed = core.fulfillment.close_return_windows(SIM, now="2026-10-01T00:00:00+00:00")
    assert closed == [order.id]
    return a, order, payment, f


def test_end_to_end_simulated_path_without_spending_anything(core):
    purchase, order, payment, f = run_happy_path(core)
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT status FROM orders WHERE id = ?", (order.id,))["status"] == "closed"
        m = compute(tx, core.ledger, SIM)
        assert m.trial_balance_ok
        landed_unit = (purchase.amount_krw + purchase.payload["duty_krw"]) // 10
        assert m.inventory_value == landed_unit * 9
        assert m.gross_sales == 20_000 and m.net_revenue == 20_000 and m.payment_receivables == 0
        assert m.provisions == 0 and m.provisional_profit == 0
        # 20,000 − landed cost − 3,000 shipping − 1,800 fees − rounding write-off
        rounding = (purchase.amount_krw + purchase.payload["duty_krw"]) - landed_unit * 10
        assert m.realized_profit == 20_000 - landed_unit - 3_000 - 1_800 - rounding == m.operating_profit
        assert "SIMULATED" in m.label
        live = compute(tx, core.ledger, "live")
        assert live.orders_placed == 0 and live.realized_profit == 0 and live.settled_cash == 0
        assert all(r["mode"] == SIM for r in tx.fetchall("SELECT mode FROM external_confirmations"))
        # every money/goods state has its confirmation record
        kinds = {c["kind"] for c in core.gateway.confirmations(tx, purchase.id)}
        assert kinds == {"supplier_order", "payment_receipt", "shipment", "receiving"}
        kinds = {c["kind"] for c in core.gateway.confirmations(tx, payment.id)}
        assert kinds == {"authorization", "capture", "settlement"}
    assert core.audit.verify()[0]


def test_duplicate_events_do_not_duplicate_postings_or_charges(core):
    purchase, order, payment, f = run_happy_path(core)
    processor = core.adapters["simulated:naverpay"]
    with core.db.transaction() as tx:
        before = compute(tx, core.ledger, SIM)
        entries = tx.scalar("SELECT COUNT(*) FROM journal_entries")
    with core.db.transaction() as tx:
        cap = tx.fetchone("SELECT external_reference FROM external_confirmations WHERE action_id = ? AND kind = 'capture'", (payment.id,))
    core.payments.apply_event(event(order.id, "capture", cap["external_reference"], amount=22_000))          # webhook redelivered
    core.payments.apply_event(event(order.id, "settlement", "SET-N-1001", payout=20_200, marketplace_fee=1_600, payment_fee=200))
    assert core.purchasing.place(purchase.id).state == "received"                                          # retried step
    assert core.purchasing.receive(purchase.id, {"source": "simulated:warehouse", "kind": "receiving", "reference": "RCV-po-1", "mode": SIM}).state == "received"
    with core.db.transaction() as tx:
        after = compute(tx, core.ledger, SIM)
        assert after.as_dict() == before.as_dict()
        assert tx.scalar("SELECT COUNT(*) FROM journal_entries") == entries
        assert tx.scalar("SELECT COUNT(*) FROM inventory_lots") == 1
    assert sum(1 for k, _ in core.adapters["simulated:aliexpress"].calls if k in ("supplier_order", "payment_receipt")) == 2


def test_refund_and_return_after_settlement(core):
    purchase, order, payment, f = run_happy_path(core)
    carrier = core.adapters["simulated:cj"]
    with core.db.transaction() as tx:
        cash_before = core.ledger.balance(tx, L.CASH, SIM)
    core.pause("purchasing", "owner review", "owner")           # refunds are obligations: still allowed
    core.payments.refund(order.id, 22_000, "customer changed mind")
    with core.db.transaction() as tx:
        row = tx.fetchone("SELECT status FROM orders WHERE id = ?", (order.id,))
        assert row["status"] == "refunded"
        assert core.gateway.get(tx, payment.id).state == "refunded"
        assert core.ledger.balance(tx, L.CASH, SIM) == cash_before - 22_000
        assert core.ledger.balance(tx, L.REFUNDS, SIM) == 20_000 and core.ledger.balance(tx, L.TAX_PAYABLE, SIM) == 0
    with pytest.raises(OpsError, match="exceeds what the customer paid"):
        core.payments.refund(order.id, 1, "again")
    core.fulfillment.request_return(f.id, "changed mind")
    core.fulfillment.receive_return(f.id, carrier.receive_return(f.id, "TRK"), restock=True, handling_krw=2_500)
    with core.db.transaction() as tx:
        m = compute(tx, core.ledger, SIM)
        assert m.trial_balance_ok
        assert tx.scalar("SELECT COALESCE(SUM(remaining), 0) FROM inventory_lots WHERE sku = 'tongs'") == 10
        assert m.realized_profit == m.operating_profit  # refunded orders are final
        assert m.realized_profit < 0
    core.pause("all", "stop", "owner")
    with pytest.raises(PolicyRefused, match="paused"):
        core.payments.refund(order.id, 1, "blocked by the full pause")


def test_dispute_flow(core):
    purchase, order, payment, f = run_happy_path(core)
    core.payments.apply_event(event(order.id, "dispute_opened", "DSP-1", amount=22_000))
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT status FROM orders WHERE id = ?", (order.id,))["status"] == "disputed"
        assert core.ledger.balance(tx, L.DISPUTE_PROVISION, SIM) == 22_000
        m = compute(tx, core.ledger, SIM)
        assert m.realized_profit == 0 or m.provisional_profit != 0  # a disputed order is not realized
    core.payments.apply_event(event(order.id, "dispute_closed", "DSP-1-closed", amount=22_000, outcome="lost", fee=1_000))
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT status FROM orders WHERE id = ?", (order.id,))["status"] == "chargeback"
        assert core.ledger.balance(tx, L.DISPUTE_PROVISION, SIM) == 0
        assert core.ledger.balance(tx, L.PAYMENT_FEES, SIM) == 200 + 1_000
        assert core.ledger.trial_balance(tx, SIM)[0] == core.ledger.trial_balance(tx, SIM)[1]
    with pytest.raises(InvalidTransition):
        core.payments.apply_event(event(order.id, "settlement", "SET-again", payout=20_200, marketplace_fee=1_600, payment_fee=200))


def test_fulfillment_waits_for_captured_payment_and_stock(core):
    order, payment = core.payments.create_order(SIM, "simulated:naver", "N-2", "tongs", 1, 22_000, 0, 2_000, 1_500, "simulated:naverpay", "commercial_resale")
    with pytest.raises(OpsError, match="nothing ships before capture"):
        core.fulfillment.create(order.id, "simulated:cj")
    processor = core.adapters["simulated:naverpay"]
    auth = processor.authorize(payment.id, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "authorization", auth.reference, amount=22_000))
    cap = processor.capture(payment.id, auth.reference, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "capture", cap.reference, amount=22_000))
    f = core.fulfillment.create(order.id, "simulated:cj")
    with pytest.raises(OpsError, match="purchase first"):
        core.fulfillment.allocate(f.id)
    with pytest.raises(InvalidTransition, match="pack it first"):
        core.fulfillment.ship(f.id, 3_000)
    with pytest.raises(ConfirmationRequired):
        with core.db.transaction() as tx:
            core.gateway.transition(tx, f.id, "shipped")
