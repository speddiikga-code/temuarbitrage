"""Gates from the platform-eligibility report: import mode on every order, price evidence and a freight quote before
a purchase, samples as expenses, certification evidence before listing, the customs code used once and never stored,
and Temu refused as a supplier."""

import pytest

from arbitrage.ops import ledger as L
from arbitrage.ops.adapters import SimulatedChannel
from arbitrage.ops.core import build
from arbitrage.ops.errors import MandateError, OpsError, PolicyRefused
from arbitrage.ops.metrics import compute

from .conftest import mandate_with
from .test_gateway_flows import SIM, adapters, event, proposal, quote, run_happy_path


@pytest.fixture
def core(db, simulated_mandate):
    ad = adapters()
    ad["simulated:smartstore"] = SimulatedChannel("simulated:smartstore")
    c = build(db, simulated_mandate, ad)
    with c.db.transaction() as tx:
        c.books.contribute_capital(tx, SIM, 1_000_000, "simulated:bank", "cap:1")
    return c


def test_orders_need_an_import_mode(core):
    with pytest.raises(OpsError, match="import_mode"):
        core.payments.create_order(SIM, "simulated:naver", "N-9", "tongs", 1, 22_000, 0, 2_000, 1_500, "simulated:naverpay", None)
    with pytest.raises(OpsError, match="import_mode"):
        core.payments.create_order(SIM, "simulated:naver", "N-9", "tongs", 1, 22_000, 0, 2_000, 1_500, "simulated:naverpay", "duty_free")
    order, _ = core.payments.create_order(SIM, "simulated:naver", "N-9", "tongs", 1, 22_000, 0, 2_000, 1_500, "simulated:naverpay", "personal_use")
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT import_mode FROM orders WHERE id = ?", (order.id,))["import_mode"] == "personal_use"


def test_purchase_needs_price_evidence_and_a_freight_quote(core):
    a = core.purchasing.propose(proposal("po-noev", price_evidence=None), SIM)
    with pytest.raises(OpsError, match="not executable profit"):
        core.purchasing.verify(a.id, quote())
    b = core.purchasing.propose(proposal("po-naver", price_evidence={"source": "naver shopping search api", "url": "https://openapi.naver.com/v1/search/shop.json", "date": "2026-09-27"}), SIM)
    with pytest.raises(OpsError, match="unlicensed"):
        core.purchasing.verify(b.id, quote())
    c = core.purchasing.propose(proposal("po-freight"), SIM)
    q = quote()
    del q["shipping"]
    with pytest.raises(OpsError, match="never a zero default"):
        core.purchasing.verify(c.id, q)
    d = core.purchasing.propose(proposal("po-ok"), SIM)
    assert core.purchasing.verify(d.id, quote()).state == "verified"


def test_samples_are_expensed_not_stocked(core):
    supplier = core.adapters["simulated:aliexpress"]
    a = core.purchasing.propose(proposal("po-sample", qty=1, purpose="sample", price_evidence=None), SIM)
    core.purchasing.verify(a.id, quote(quantity=1))  # samples need no resale price evidence
    core.purchasing.reserve(a.id)
    a = core.purchasing.place(a.id)
    a = core.purchasing.mark_shipped(a.id, supplier.shipment(a.id, "PO"))
    a = core.purchasing.receive(a.id, {"source": "simulated:warehouse", "kind": "receiving", "reference": "RCV-s", "mode": SIM}, duties_krw=900)
    assert a.kind == "sample_purchase" and a.state == "received"
    with core.db.transaction() as tx:
        assert core.ledger.balance(tx, L.INVENTORY, SIM) == 0
        assert core.ledger.balance(tx, L.SAMPLES, SIM) == a.amount_krw + 900
        assert tx.scalar("SELECT COUNT(*) FROM inventory_lots") == 0
        assert compute(tx, core.ledger, SIM).trial_balance_ok


def test_personal_use_order_needs_a_customs_code_at_shipment_and_never_stores_it(core):
    # stock first
    purchase, order, payment, f = run_happy_path(core, key="po-stock", order_no="N-stock")
    processor, carrier = core.adapters["simulated:naverpay"], core.adapters["simulated:cj"]
    order, payment = core.payments.create_order(SIM, "simulated:naver", "N-pu", "tongs", 1, 22_000, 0, 2_000, 1_500,
                                                "simulated:naverpay", "personal_use")
    auth = processor.authorize(payment.id, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "authorization", auth.reference, amount=22_000))
    cap = processor.capture(payment.id, auth.reference, 22_000, "KRW")
    core.payments.apply_event(event(order.id, "capture", cap.reference, amount=22_000))
    ful = core.fulfillment.create(order.id, "simulated:cj")
    core.fulfillment.allocate(ful.id)
    core.fulfillment.pack(ful.id)
    with pytest.raises(OpsError, match="개인통관고유부호"):
        core.fulfillment.ship(ful.id, 3_000)
    code = "P123456789012"
    ful = core.fulfillment.ship(ful.id, 3_000, customs_code=code)
    assert ful.state == "shipped" and ful.payload["customs_code_provided"] is True
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT customs_code_provided FROM orders WHERE id = ?", (order.id,))["customs_code_provided"] == 1
        for table in ("actions", "external_confirmations", "action_transitions", "audit_log", "orders", "workflows"):
            cols = "payload" if table in ("actions", "external_confirmations") else ("after" if table == "audit_log" else "*")
            rows = tx.fetchall(f"SELECT * FROM {table}")
            assert not any(code in str(r) for r in rows), table
    assert not any(code in str(c) for c in carrier.calls)


def test_listing_needs_certification_evidence(core):
    lst = core.listings.propose(SIM, "simulated:smartstore", "tongs", "실리콘 집게", 14_900, "kitchen",
                                {"required": True, "kind": "kc_safety_confirmation"}, "commercial_resale")
    with pytest.raises(OpsError, match="needs its number and an evidence reference"):
        core.listings.verify(lst.id)
    lst2 = core.listings.propose(SIM, "simulated:smartstore", "mount", "차량용 거치대", 12_900, "car-accessories",
                                 {"required": False}, "commercial_resale")
    with pytest.raises(OpsError, match="rule it relies on"):
        core.listings.verify(lst2.id)
    with pytest.raises(PolicyRefused, match="category"):
        core.listings.propose(SIM, "simulated:smartstore", "cream", "크림", 9_900, "cosmetics", {"required": False}, "commercial_resale")
    lst3 = core.listings.propose(SIM, "simulated:smartstore", "cable", "USB 케이블", 5_900, "car-accessories",
                                 {"required": True, "kind": "kc_safety_confirmation", "number": "XU12345-26001", "evidence": "https://safetykorea.kr/..."},
                                 "commercial_resale")
    with pytest.raises(OpsError, match="verify certification first"):
        core.listings.publish(lst3.id)
    core.listings.verify(lst3.id)
    core.pause("purchasing", "review", "owner")
    with pytest.raises(PolicyRefused, match="paused"):
        core.listings.publish(lst3.id)  # a listing is a new commitment
    with core.db.transaction() as tx:
        pid = core.pauses.active(tx)[0]["id"]
    core.resume(pid, "owner")
    assert core.listings.publish(lst3.id).state == "listed"


def test_mandate_refuses_temu_as_a_supplier():
    with pytest.raises(MandateError, match="Temu is not an approved supplier"):
        mandate_with(**{"connections.suppliers": ["temu", "aliexpress"]})
