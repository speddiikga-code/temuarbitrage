"""Supplier purchases: propose, verify, reserve, place, reconcile, receive.

Before any supplier payment the purchase is verified against a fresh quote (product, quantity, price, stock,
delivery terms, destination, import basis and evidence) and against the budget governor, then the budget is
reserved atomically, and only then is the order sent with the action id as the supplier-side transaction id.  An
ambiguous payment result parks the purchase in `payment_unknown`; `place()` refuses to retry it until `reconcile()`
has asked the supplier what really happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arbitrage.pricing import IMPORT_BASES

from .adapters import AMBIGUOUS, CONFIRMED, FAILED
from .books import Books
from .budget import BudgetGovernor
from .db import Database
from .errors import InvalidTransition, OpsError, ReconciliationRequired
from .gateway import Action, ActionGateway
from .mandate import Mandate
from .policy import ActionRequest, PolicyController

MAX_DELIVERY_DAYS = 30
PRICE_TOLERANCE = 0.02
# The Naver Shopping search API ended 2026-07-31; its data is unlicensed from 2026-08-01 (eligibility report, item 5).
NAVER_SEARCH_API_END = "2026-08-01"


@dataclass(frozen=True)
class PurchaseProposal:
    idempotency_key: str
    supplier: str                 # integration name, e.g. simulated:aliexpress
    sku: str
    quantity: int
    unit_price: float
    currency: str
    shipping: float
    fx_rate: float                # KRW per unit of currency used for the estimate
    amount_krw: int               # goods + shipping in KRW, the most this purchase may cost
    duty_krw: int                 # estimated duty and VAT on arrival
    category: str
    import_basis: str             # commercial_resale | genuine_sample (personal_use is never valid for resale)
    import_evidence: str | None = None   # reference for any claimed exemption or classification
    price_evidence: dict[str, Any] | None = None   # {source, url, date}: where the resale price was seen, and when
    source: str = "initial_capital"
    purpose: str = "inventory"
    destination: str = "KR"
    expected_resale_krw: int = 0
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def amount(self) -> int:
        return round((self.unit_price * self.quantity + self.shipping) * 100)  # minor units of `currency`

    @property
    def kind(self) -> str:
        return "sample_purchase" if self.purpose == "sample" else "supplier_purchase"


class Purchasing:
    def __init__(self, db: Database, gateway: ActionGateway, governor: BudgetGovernor, books: Books,
                 mandate: Mandate, policy: PolicyController):
        self.db = db
        self.gateway = gateway
        self.governor = governor
        self.books = books
        self.mandate = mandate
        self.policy = policy

    # -- 1. propose -------------------------------------------------------------------------------------

    def propose(self, proposal: PurchaseProposal, mode: str, actor: str = "agent") -> Action:
        payload = {
            "sku": proposal.sku, "quantity": proposal.quantity, "unit_price": proposal.unit_price,
            "shipping": proposal.shipping, "fx_rate": proposal.fx_rate, "duty_krw": proposal.duty_krw,
            "category": proposal.category, "import_basis": proposal.import_basis, "import_evidence": proposal.import_evidence,
            "source": proposal.source, "purpose": proposal.purpose, "destination": proposal.destination,
            "expected_resale_krw": proposal.expected_resale_krw, "price_evidence": proposal.price_evidence,
            "notes": proposal.notes,
        }
        request = ActionRequest(proposal.kind, proposal.idempotency_key, mode, proposal.amount_krw, proposal.amount,
                                proposal.currency, proposal.supplier, proposal.category, proposal.sku, "sku", proposal.sku, payload)
        return self.gateway.submit(request, actor)

    # -- 2. verify (section 8 checks) ---------------------------------------------------------------------

    def verify(self, action_id: str, quote: dict[str, Any], actor: str = "system") -> Action:
        """Check the purchase against a fresh supplier quote and the mandate. Rejects with every reason found."""
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state == "verified":
                return action
            if action.state != "proposed":
                raise InvalidTransition(f"purchase {action_id} is {action.state}, not proposed")
            p = action.payload
            problems: list[str] = []
            if quote.get("sku") != p["sku"]:
                problems.append(f"quote is for {quote.get('sku')!r}, not {p['sku']!r}")
            if int(quote.get("quantity", 0)) != int(p["quantity"]):
                problems.append("quote quantity differs from the proposal")
            if not quote.get("in_stock"):
                problems.append("supplier reports no stock")
            if str(quote.get("currency", "")).upper() != action.currency.upper():
                problems.append(f"quote currency {quote.get('currency')} differs from {action.currency}")
            if quote.get("shipping") is None:
                problems.append("quote has no freight cost; landed cost needs a shipping quote, never a zero default")
            quoted = float(quote.get("unit_price", 0)) * int(p["quantity"]) + float(quote.get("shipping") or 0)
            proposed = float(p["unit_price"]) * int(p["quantity"]) + float(p["shipping"])
            if quoted > proposed * (1 + PRICE_TOLERANCE):
                problems.append(f"current price {quoted:.2f} {action.currency} is above the proposed {proposed:.2f}")
            quoted_krw = round(quoted * float(p["fx_rate"]))
            if quoted_krw > action.amount_krw:
                problems.append(f"current price {quoted_krw:,} KRW exceeds the proposed cap {action.amount_krw:,} KRW")
            days = quote.get("delivery_days")
            if days is None or int(days) > MAX_DELIVERY_DAYS:
                problems.append(f"delivery terms missing or longer than {MAX_DELIVERY_DAYS} days")
            country = self.mandate.get("business.operating_country", "KR")
            if quote.get("destination", p.get("destination")) != country or p.get("destination") != country:
                problems.append(f"destination must be {country}")
            basis = p.get("import_basis")
            if basis not in IMPORT_BASES:
                problems.append(f"import_basis must be one of {IMPORT_BASES}")
            elif basis == "personal_use":
                problems.append("goods bought for resale cannot be imported as personal use (Korea Customs Service)")
            if int(p.get("duty_krw", 0)) <= 0 and not p.get("import_evidence"):
                problems.append("zero duty needs import evidence (a classification or exemption reference); unknown is never zero")
            if not self.mandate.permits_category(p.get("category")):
                problems.append(f"category {p.get('category')!r} not permitted by the mandate")
            if p.get("purpose") != "sample":
                problems += self._price_evidence_problems(p.get("price_evidence"))
            problems += self.governor.problems(tx, action.mode, action.amount_krw, p["purpose"], p["source"], action.sku)
            if problems:
                self.gateway.transition(tx, action.id, "rejected", reason="; ".join(problems), actor=actor,
                                        payload={"verification": {"ok": False, "problems": problems, "quote": quote}})
            else:
                action = self.gateway.transition(tx, action.id, "verified", actor=actor,
                                                 payload={"verification": {"ok": True, "quote": quote, "quoted_krw": quoted_krw}})
        if problems:  # raised after the rejection is committed
            raise OpsError("purchase rejected: " + "; ".join(problems))
        return action

    @staticmethod
    def _price_evidence_problems(evidence) -> list[str]:
        """A resale price counts only with a source, a URL and a date, and not from the ended Naver search API."""
        if not isinstance(evidence, dict) or not all(evidence.get(k) for k in ("source", "url", "date")):
            return ["resale price needs evidence {source, url, date}; an unsourced price gap is not executable profit"]
        source = str(evidence["source"]).lower()
        if "naver" in source and "api" in source and str(evidence["date"]) >= NAVER_SEARCH_API_END:
            return [f"price evidence from the Naver search API dated {evidence['date']} is unlicensed (API ended 2026-07-31)"]
        return []

    # -- 3. reserve budget atomically --------------------------------------------------------------------

    def reserve(self, action_id: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state == "reserved":
                return action
            if action.state != "verified":
                raise InvalidTransition(f"purchase {action_id} is {action.state}, not verified")
            r = self.governor.reserve(action.mode, action.amount_krw, action.payload["purpose"], action.payload["source"],
                                      action_id=action.id, sku=action.sku, actor=actor, tx=tx)
            return self.gateway.transition(tx, action.id, "reserved", actor=actor, reservation_id=r.id)

    # -- 4. place the order and pay -----------------------------------------------------------------------

    def place(self, action_id: str, actor: str = "system") -> Action:
        pending_error: Exception | None = None
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state in ("ordered", "paid", "shipped", "received"):
                return action
            if action.state == "payment_unknown":
                raise ReconciliationRequired(f"purchase {action_id} has an ambiguous payment; reconcile it before retrying")
            if action.state != "reserved":
                raise InvalidTransition(f"purchase {action_id} is {action.state}; it must be verified and reserved first")
            self.policy.evaluate(tx, action.request(), actor).raise_if_refused()  # a pause may have started since
            adapter = self.gateway.adapter(tx, action)
            p = action.payload
            order = adapter.place_order(action.id, action.sku, int(p["quantity"]), action.amount, action.currency, p["destination"])
            if order.status == FAILED:
                self.governor.release(tx, action.reservation_id, actor, order.error or "order failed")
                return self.gateway.transition(tx, action.id, "failed", reason=order.error, actor=actor, error=order.error)
            if order.status == AMBIGUOUS:
                action = self.gateway.transition(tx, action.id, "payment_unknown", reason=order.error, actor=actor, error=order.error)
                pending_error = ReconciliationRequired(f"purchase {action_id}: {order.error}; reconcile before retrying")
            else:
                action = self.gateway.transition(tx, action.id, "ordered", confirmation=order, actor=actor)
                action, pending_error = self._settle_payment(tx, action, adapter, order.reference, actor)
        if pending_error:
            raise pending_error
        return action

    def _settle_payment(self, tx, action: Action, adapter, order_reference: str, actor: str):
        receipt = adapter.payment_receipt(action.id, order_reference, action.amount, action.currency)
        if receipt.status == AMBIGUOUS:
            action = self.gateway.transition(tx, action.id, "payment_unknown", reason=receipt.error, actor=actor, error=receipt.error)
            return action, ReconciliationRequired(f"purchase {action.id}: payment result unknown; reconcile before retrying")
        if receipt.status == FAILED:
            self.governor.release(tx, action.reservation_id, actor, receipt.error or "payment failed")
            return self.gateway.transition(tx, action.id, "cancelled", reason=receipt.error, actor=actor, error=receipt.error), None
        return self._mark_paid(tx, action, receipt, actor), None

    def _mark_paid(self, tx, action: Action, receipt, actor: str) -> Action:
        action = self.gateway.transition(tx, action.id, "paid", confirmation=receipt, actor=actor)
        self.governor.commit(tx, action.reservation_id, action.amount_krw, actor)
        fx_cost = int(action.payload.get("fx_cost_krw", 0))
        self.books.pay_supplier(tx, action.mode, action.id, action.amount_krw, fx_cost, f"purchase:{action.id}:paid")
        return action

    # -- 5. reconcile an ambiguous result -------------------------------------------------------------------

    def reconcile(self, action_id: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state != "payment_unknown":
                return action
            adapter = self.gateway.adapter(tx, action)
            found = adapter.lookup(action.id)
            if found.status != CONFIRMED:
                self.governor.release(tx, action.reservation_id, actor, "supplier has no such order")
                return self.gateway.transition(tx, action.id, "failed", reason="reconciled: supplier has no such order", actor=actor)
            action = self.gateway.transition(tx, action.id, "ordered", confirmation=found, actor=actor, reason="reconciled")
            receipt = adapter.payment_receipt(action.id, found.reference, action.amount, action.currency)
            if receipt.status == CONFIRMED:
                return self._mark_paid(tx, action, receipt, actor)
            self.gateway.transition(tx, action.id, "payment_unknown", reason="receipt still unknown", actor=actor)
        raise ReconciliationRequired(f"purchase {action_id}: order exists but payment is still unconfirmed")

    # -- 6. goods move ------------------------------------------------------------------------------------

    def mark_shipped(self, action_id: str, shipment, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            return self.gateway.transition(tx, action_id, "shipped", confirmation=shipment, actor=actor)

    def receive(self, action_id: str, receiving, freight_krw: int = 0, duties_krw: int = 0, actor: str = "system") -> Action:
        """Goods checked in: an inventory lot at landed cost, or an expense when the purchase was a sample."""
        with self.db.transaction() as tx:
            action = self.gateway.transition(tx, action_id, "received", confirmation=receiving, actor=actor,
                                             payload={"freight_krw": freight_krw, "duties_krw": duties_krw})
            args = (tx, action.mode, action.id, action.sku, int(action.payload["quantity"]), action.amount_krw, freight_krw,
                    duties_krw, f"purchase:{action.id}:received")
            if action.kind == "sample_purchase":
                self.books.expense_sample(*args)
            else:
                self.books.receive_inventory(*args)
            return action

    def cancel(self, action_id: str, reason: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state in ("proposed", "verified"):
                return self.gateway.transition(tx, action.id, "rejected", reason=reason, actor=actor)
            if action.reservation_id:
                self.governor.release(tx, action.reservation_id, actor, reason)
            return self.gateway.transition(tx, action.id, "cancelled", reason=reason, actor=actor)
