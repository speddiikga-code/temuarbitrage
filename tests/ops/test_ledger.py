import pytest

from arbitrage.ops import ledger as L
from arbitrage.ops.audit import AuditTrail
from arbitrage.ops.books import Books, Order
from arbitrage.ops.errors import OpsError
from arbitrage.ops.ledger import Entry, Ledger, cr, dr
from arbitrage.ops.metrics import compute

SIM = "simulated"


def order(oid="ord_1", gross=22_000, discount=0, tax=2_000, fee=1_500, qty=1, sku="tongs"):
    return Order(oid, "simulated:naver", f"N-{oid}", sku, qty, gross, discount, tax, fee, SIM)


@pytest.fixture
def books(db, simulated_mandate):
    ledger = Ledger(db)
    with db.transaction() as tx:
        ledger.ensure_chart(tx)
    return Books(ledger, simulated_mandate)


def test_unbalanced_or_unknown_entries_are_refused(db):
    ledger = Ledger(db)
    with db.transaction() as tx:
        ledger.ensure_chart(tx)
        with pytest.raises(OpsError, match="does not balance"):
            ledger.post(tx, Entry("x", "x", (dr(L.CASH, 100), cr(L.CAPITAL, 90)), "k1", SIM))
        with pytest.raises(OpsError, match="unknown account"):
            ledger.post(tx, Entry("x", "x", (dr("9999", 100), cr(L.CAPITAL, 100)), "k2", SIM))
        with pytest.raises(OpsError, match="positive"):
            ledger.post(tx, Entry("x", "x", (dr(L.CASH, -5), cr(L.CAPITAL, -5)), "k3", SIM))
        with pytest.raises(ValueError):
            ledger.post(tx, Entry("x", "x", (dr(L.CASH, 5), cr(L.CAPITAL, 5)), "k4", "demo"))


def test_same_event_key_posts_once(db):
    ledger = Ledger(db)
    with db.transaction() as tx:
        ledger.ensure_chart(tx)
        first = ledger.post(tx, Entry("capital", "x", (dr(L.CASH, 100), cr(L.CAPITAL, 100)), "cap:1", SIM))
        again = ledger.post(tx, Entry("capital", "x", (dr(L.CASH, 100), cr(L.CAPITAL, 100)), "cap:1", SIM))
        assert first == again
        assert ledger.balance(tx, L.CASH, SIM) == 100
        assert ledger.trial_balance(tx, SIM) == (100, 100)


def test_modes_never_mix(db):
    ledger = Ledger(db)
    with db.transaction() as tx:
        ledger.ensure_chart(tx)
        ledger.post(tx, Entry("capital", "x", (dr(L.CASH, 100), cr(L.CAPITAL, 100)), "cap:sim", SIM))
        assert ledger.balance(tx, L.CASH, "live") == 0
        assert compute(tx, ledger, "live").settled_cash == 0
        assert "SIMULATED" in compute(tx, ledger, SIM).label


def test_purchase_sale_settlement_cycle_books_cogs_once_and_realizes_after_the_window(db, books):
    ledger = books.ledger
    with db.transaction() as tx:
        books.contribute_capital(tx, SIM, 500_000, "simulated:bank", "cap:1")
        books.pay_supplier(tx, SIM, "pur_1", 30_000, 500, "pur_1:paid")
        lot = books.receive_inventory(tx, SIM, "pur_1", "tongs", 3, 30_000, 2_400, 600, "pur_1:received")
        assert lot is not None
        assert books.receive_inventory(tx, SIM, "pur_1", "tongs", 3, 30_000, 2_400, 600, "pur_1:received") is None
        bal = ledger.balances(tx, SIM)
        assert bal[L.CASH] == 500_000 - 30_000 - 500 - 3_000
        assert bal[L.PREPAID] == 0
        assert bal[L.INVENTORY] == 33_000  # 11,000 landed per unit, booked once
        assert tx.scalar("SELECT COUNT(*) FROM inventory_lots") == 1

        o = order()
        tx.insert("orders", {"id": o.id, "channel": o.channel, "external_order_id": o.external_order_id, "sku": o.sku,
                             "quantity": 1, "gross_amount": 22_000, "discount": 0, "tax_collected": 2_000, "expected_fee": 1_500,
                             "currency": "KRW", "placed_at": "2026-09-27T00:00:00+00:00", "status": "paid", "mode": SIM})
        books.record_sale(tx, o)
        books.record_sale(tx, o)  # redelivered capture webhook: no second posting
        bal = ledger.balances(tx, SIM)
        assert bal[L.RECEIVABLE] == 22_000
        assert bal[L.GROSS_SALES] == 20_000
        assert bal[L.TAX_PAYABLE] == 2_000
        assert bal[L.ACCRUED_FEES] == 1_500 and bal[L.MARKETPLACE_FEES] == 1_500
        assert bal[L.RETURNS_PROVISION] == 1_000 and bal[L.DISPUTE_PROVISION] == 200  # 5% and 1% of 20,000 net

        cogs = books.record_fulfillment(tx, o, shipping_krw=3_000)
        assert cogs == 11_000
        assert books.record_fulfillment(tx, o, shipping_krw=3_000) == 11_000  # duplicate shipment event
        bal = ledger.balances(tx, SIM)
        assert bal[L.INVENTORY] == 22_000 and bal[L.COGS] == 11_000 and bal[L.FREIGHT] == 3_000

        books.record_settlement(tx, o, payout_krw=20_200, marketplace_fee_krw=1_600, payment_fee_krw=200, event_key="settle:1")
        bal = ledger.balances(tx, SIM)
        assert bal[L.RECEIVABLE] == 0 and bal[L.ACCRUED_FEES] == 0
        assert bal[L.MARKETPLACE_FEES] == 1_600 and bal[L.PAYMENT_FEES] == 200
        with pytest.raises(OpsError, match="!= receivable"):
            books.record_settlement(tx, o, 20_000, 1_600, 200, "settle:bad")

        m = compute(tx, ledger, SIM)
        assert m.trial_balance_ok
        assert m.orders_placed == 1
        assert m.gross_sales == 20_000 and m.net_revenue == 20_000
        # 20,000 - cogs 11,000 - freight 3,000 - fees 1,800 - provisions 1,200 - fx 500 = 2,500
        assert m.contribution_profit == 2_500 == m.operating_profit
        assert m.realized_profit == -500 and m.provisional_profit == 3_000  # only the fx cost is final so far

        tx.update("orders", "id", o.id, {"status": "closed"})
        books.release_provisions(tx, o)
        books.release_provisions(tx, o)  # idempotent
        m = compute(tx, ledger, SIM)
        assert m.provisions == 0
        assert m.operating_profit == 3_700 == m.realized_profit
        assert m.provisional_profit == 0
        assert m.trial_balance_ok


def test_refund_dispute_and_restock(db, books):
    ledger = books.ledger
    with db.transaction() as tx:
        books.contribute_capital(tx, SIM, 100_000, "simulated:bank", "cap:1")
        books.pay_supplier(tx, SIM, "pur_1", 10_000, 0, "pur_1:paid")
        books.receive_inventory(tx, SIM, "pur_1", "tongs", 1, 10_000, 0, 0, "pur_1:received")
        o = order(gross=22_000, tax=2_000)
        tx.insert("orders", {"id": o.id, "channel": o.channel, "external_order_id": o.external_order_id, "sku": o.sku,
                             "quantity": 1, "gross_amount": 22_000, "discount": 0, "tax_collected": 2_000, "expected_fee": 1_500,
                             "currency": "KRW", "placed_at": "2026-09-27T00:00:00+00:00", "status": "paid", "mode": SIM})
        books.record_sale(tx, o)
        books.record_fulfillment(tx, o, 0)
        books.record_settlement(tx, o, 20_500, 1_500, 0, "settle:1")
        books.record_refund(tx, o, 22_000, settled=True, event_key="refund:1")
        books.record_refund(tx, o, 22_000, settled=True, event_key="refund:1")  # duplicate
        books.restock_return(tx, o, 1, handling_krw=2_500, event_key="restock:1")
        bal = ledger.balances(tx, SIM)
        assert bal[L.REFUNDS] == 20_000 and bal[L.TAX_PAYABLE] == 0
        assert bal[L.INVENTORY] == 10_000 and bal[L.COGS] == 0 and bal[L.RETURN_HANDLING] == 2_500
        with pytest.raises(OpsError, match="outside"):
            books.record_refund(tx, o, 30_000, True, "refund:2")

        books.open_dispute(tx, o, 22_000, "dispute:open")
        assert bal[L.DISPUTE_PROVISION] == 200
        assert ledger.balance(tx, L.DISPUTE_PROVISION, SIM) == 22_000
        books.lose_dispute(tx, o, 22_000, 1_000, "dispute:lost")
        bal = ledger.balances(tx, SIM)
        assert bal[L.DISPUTE_PROVISION] == 0 and bal[L.CHARGEBACKS] == 0 and bal[L.PAYMENT_FEES] == 1_000
        debits, credits = ledger.trial_balance(tx, SIM)
        assert debits == credits


def test_insufficient_inventory_is_refused(db, books):
    with db.transaction() as tx:
        with pytest.raises(OpsError, match="insufficient inventory"):
            books.record_fulfillment(tx, order(qty=2), 0)


def test_audit_chain_detects_tampering(db):
    audit = AuditTrail(db)
    with db.transaction() as tx:
        audit.record(tx, "owner", "pause", "pauses", "p1", after={"scope": "purchasing"})
        audit.record(tx, "system", "resume", "pauses", "p1")
    assert audit.verify() == (True, 2, None)
    with db.transaction() as tx:
        tx.execute("UPDATE audit_log SET action = 'nothing' WHERE entity_id = 'p1' AND action = 'pause'")
    ok, count, broken = audit.verify()
    assert not ok and count == 2 and broken is not None
