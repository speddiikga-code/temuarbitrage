"""Adapters: the only code that talks to a supplier, processor or carrier.

Every adapter says its `mode`.  The simulated adapters here produce confirmations named `simulated:<name>` with
references like `SIM-PO-3`; they exist so the whole path can run and fail on purpose in tests.  There is no live
adapter yet: `LiveAdapterUnavailable` names the manual dependency and refuses, so nothing can pretend a real
supplier or processor confirmed anything.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from .common import LIVE, SIMULATED
from .errors import NotConfigured

CONFIRMED, FAILED, AMBIGUOUS = "confirmed", "failed", "ambiguous"


@dataclass(frozen=True)
class AdapterResult:
    status: str                     # confirmed | failed | ambiguous
    kind: str                       # confirmation kind, e.g. supplier_order, payment_receipt, shipment
    reference: str | None           # the external system's id for what happened
    source: str                     # adapter name
    mode: str
    amount: int | None = None
    currency: str = "KRW"
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == CONFIRMED


class SimulatedAdapter:
    """Base: scripted outcomes. `script(kind, status)` makes the next call of `kind` return that status."""

    role = "generic"

    def __init__(self, name: str):
        if not name.startswith("simulated:"):
            raise ValueError("simulated adapters are named 'simulated:<name>'")
        self.name = name
        self.mode = SIMULATED
        self._n = itertools.count(1)
        self._scripts: dict[str, list[str]] = {}
        self.calls: list[tuple[str, dict]] = []
        self.orders: dict[str, dict] = {}

    def script(self, kind: str, *statuses: str) -> None:
        self._scripts.setdefault(kind, []).extend(statuses)

    def _outcome(self, kind: str) -> str:
        queue = self._scripts.get(kind)
        return queue.pop(0) if queue else CONFIRMED

    def _ref(self, prefix: str) -> str:
        return f"SIM-{prefix}-{next(self._n)}"

    def _result(self, kind: str, prefix: str, amount=None, currency="KRW", **payload) -> AdapterResult:
        status = self._outcome(kind)
        self.calls.append((kind, payload))
        if status == FAILED:
            return AdapterResult(FAILED, kind, None, self.name, self.mode, amount, currency, payload, error="simulated failure")
        ref = self._ref(prefix)
        if status == AMBIGUOUS:
            # The request went out and (in this simulation) succeeded, but no answer came back.
            self.orders[ref] = {"kind": kind, "amount": amount, "currency": currency, **payload, "ambiguous": True}
            return AdapterResult(AMBIGUOUS, kind, None, self.name, self.mode, amount, currency,
                                 {"hidden_reference": ref, **payload}, error="simulated timeout: result unknown")
        self.orders[ref] = {"kind": kind, "amount": amount, "currency": currency, **payload}
        return AdapterResult(CONFIRMED, kind, ref, self.name, self.mode, amount, currency, payload)


class SimulatedSupplier(SimulatedAdapter):
    role = "supplier"

    def quote(self, sku: str, quantity: int) -> dict:
        self.calls.append(("quote", {"sku": sku, "quantity": quantity}))
        return {"sku": sku, "quantity": quantity, "in_stock": True, "unit_price": 3.2, "currency": "USD",
                "shipping": 1.5, "delivery_days": 12, "destination": "KR"}

    def place_order(self, action_id: str, sku: str, quantity: int, amount: int, currency: str, destination: str) -> AdapterResult:
        return self._result("supplier_order", "PO", amount, currency, action_id=action_id, sku=sku, quantity=quantity,
                            destination=destination)

    def payment_receipt(self, action_id: str, order_reference: str, amount: int, currency: str) -> AdapterResult:
        return self._result("payment_receipt", "PAY", amount, currency, action_id=action_id, order_reference=order_reference)

    def lookup(self, action_id: str) -> AdapterResult:
        """Reconciliation: what really happened to the order we sent with this transaction id?"""
        self.calls.append(("lookup", {"action_id": action_id}))
        for ref, rec in self.orders.items():
            if rec.get("action_id") == action_id and rec["kind"] == "supplier_order":
                return AdapterResult(CONFIRMED, "supplier_order", ref, self.name, self.mode, rec["amount"], rec["currency"],
                                     {"reconciled": True})
        return AdapterResult(FAILED, "supplier_order", None, self.name, self.mode, error="no such order at supplier")

    def shipment(self, action_id: str, order_reference: str) -> AdapterResult:
        return self._result("shipment", "SHP", action_id=action_id, order_reference=order_reference)


class SimulatedProcessor(SimulatedAdapter):
    role = "payment"

    def authorize(self, action_id: str, amount: int, currency: str) -> AdapterResult:
        return self._result("authorization", "AUTH", amount, currency, action_id=action_id)

    def capture(self, action_id: str, authorization: str, amount: int, currency: str) -> AdapterResult:
        return self._result("capture", "CAP", amount, currency, action_id=action_id, authorization=authorization)

    def settle(self, action_id: str, capture: str, payout: int, fee: int, currency: str) -> AdapterResult:
        return self._result("settlement", "SET", payout, currency, action_id=action_id, capture=capture, fee=fee)

    def refund(self, action_id: str, capture: str, amount: int, currency: str) -> AdapterResult:
        return self._result("refund", "REF", amount, currency, action_id=action_id, capture=capture)


class SimulatedCarrier(SimulatedAdapter):
    role = "logistics"

    def create_shipment(self, action_id: str, order_id: str, cost: int, customs_code: str | None = None) -> AdapterResult:
        # The customs code is used for this parcel only; it never appears in the result or in any stored payload.
        return self._result("shipment", "TRK", cost, "KRW", action_id=action_id, order_id=order_id,
                            customs_code_provided=bool(customs_code))

    def confirm_delivery(self, action_id: str, tracking: str) -> AdapterResult:
        return self._result("delivery", "DLV", action_id=action_id, tracking=tracking)

    def receive_return(self, action_id: str, tracking: str) -> AdapterResult:
        return self._result("return_receipt", "RET", action_id=action_id, tracking=tracking)


class SimulatedChannel(SimulatedAdapter):
    role = "sales_channel"

    def create_listing(self, action_id: str, sku: str, title: str, price_krw: int) -> AdapterResult:
        return self._result("listing", "LST", price_krw, "KRW", action_id=action_id, sku=sku, title=title)

    def delist(self, action_id: str, listing_reference: str) -> AdapterResult:
        return self._result("delisting", "DEL", action_id=action_id, listing_reference=listing_reference)


class LiveAdapterUnavailable:
    """Stands in for every live integration until a real one is built and verified."""

    def __init__(self, name: str, manual_dependency: str):
        self.name = name
        self.mode = LIVE
        self.manual_dependency = manual_dependency

    def __getattr__(self, item):
        def refuse(*args, **kwargs):
            raise NotConfigured(f"no live adapter for {self.name}: {self.manual_dependency}")
        return refuse
