"""Order fulfillment: allocate stock, pack, ship, deliver, close the return window, take returns.

Shipping and delivery need carrier confirmations; COGS and outbound freight are booked when the parcel ships.
A fulfillment is an obligation to a paying customer, so a purchasing pause never blocks it; only an owner
pause of everything does.
"""

from __future__ import annotations

from .adapters import CONFIRMED
from .audit import AuditTrail
from .books import Books
from .common import now_iso
from .db import Database
from .errors import InvalidTransition, OpsError
from .gateway import Action, ActionGateway
from .mandate import Mandate
from .orders import load_order, sync_status
from .policy import ActionRequest, PolicyController


class Fulfillment:
    def __init__(self, db: Database, gateway: ActionGateway, books: Books, mandate: Mandate, policy: PolicyController,
                 audit: AuditTrail):
        self.db = db
        self.gateway = gateway
        self.books = books
        self.mandate = mandate
        self.policy = policy
        self.audit = audit

    def create(self, order_id: str, carrier: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            row, order = load_order(tx, order_id)
            if row["fulfillment_id"]:
                return self.gateway.get(tx, row["fulfillment_id"])
            payment = self.gateway.get(tx, row["payment_id"])
            if payment.state not in ("captured", "settled", "partially_refunded", "dispute_won"):
                raise OpsError(f"order {order_id}: payment is {payment.state}; nothing ships before capture is confirmed")
            request = ActionRequest("fulfillment", f"ful:{order.mode}:{order_id}", order.mode, 0, 0, "KRW", carrier, None,
                                    order.sku, "order", order_id, {"quantity": order.quantity})
            action = self.gateway.submit(request, actor, tx)
            tx.update("orders", "id", order_id, {"fulfillment_id": action.id})
            return action

    def allocate(self, action_id: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state == "allocated":
                return action
            available = int(tx.scalar("SELECT COALESCE(SUM(remaining), 0) FROM inventory_lots WHERE sku = ? AND mode = ? AND remaining > 0",
                                      (action.sku, action.mode)))
            need = int(action.payload["quantity"])
            if available >= need:
                return self.gateway.transition(tx, action.id, "allocated", actor=actor, payload={"allocated": need})
            self.gateway.note_error(tx, action.id, f"awaiting supply: need {need}, have {available}")
        raise OpsError(f"order {action.reference_id}: {need} x {action.sku} needed, {available} in stock; purchase first")

    def pack(self, action_id: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            return self.gateway.transition(tx, action_id, "packed", actor=actor)

    def ship(self, action_id: str, shipping_cost_krw: int, actor: str = "system", customs_code: str | None = None) -> Action:
        """Ship the parcel. A personal-use (구매대행) order needs the customer's 개인통관고유부호 here: it goes to the
        carrier for this one parcel and is not stored, only the fact that it was supplied."""
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state in ("shipped", "delivered", "completed"):
                return action
            if action.state != "packed":
                raise InvalidTransition(f"fulfillment {action_id} is {action.state}; pack it first")
            self.policy.evaluate(tx, action.request(), actor).raise_if_refused()
            row, order = load_order(tx, action.reference_id)
            if row["import_mode"] == "personal_use" and not customs_code:
                raise OpsError(f"order {order.external_order_id}: a personal-use import needs the customer's 개인통관고유부호 to ship")
            adapter = self.gateway.adapter(tx, action)
            result = adapter.create_shipment(action.id, action.reference_id, shipping_cost_krw,
                                             **({"customs_code": customs_code} if customs_code else {}))
            if result.status == CONFIRMED:
                action = self.gateway.transition(tx, action.id, "shipped", confirmation=result, actor=actor,
                                                 payload={"tracking": result.reference, "shipping_cost_krw": shipping_cost_krw,
                                                          "customs_code_provided": bool(customs_code)})
                if customs_code:
                    tx.update("orders", "id", order.id, {"customs_code_provided": 1})
                self.books.record_fulfillment(tx, order, shipping_cost_krw)
                sync_status(tx, self.gateway, self.books, order.id)
                return action
            self.gateway.note_error(tx, action.id, result.error or "carrier refused")
        raise OpsError(f"carrier did not confirm the shipment: {result.error}")

    def deliver(self, action_id: str, delivery, actor: str = "carrier") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.transition(tx, action_id, "delivered", confirmation=delivery, actor=actor)
            sync_status(tx, self.gateway, self.books, action.reference_id)
            return action

    def request_return(self, action_id: str, reason: str, actor: str = "support") -> Action:
        with self.db.transaction() as tx:
            return self.gateway.transition(tx, action_id, "return_requested", reason=reason, actor=actor)

    def receive_return(self, action_id: str, receipt, restock: bool, handling_krw: int, actor: str = "warehouse") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.transition(tx, action_id, "returned", confirmation=receipt, actor=actor)
            _, order = load_order(tx, action.reference_id)
            if restock:
                self.books.restock_return(tx, order, order.quantity, handling_krw, f"order:{order.id}:restock")
            elif handling_krw:
                self.books.record_expense(tx, order.mode, "5600", handling_krw, f"return handling for {order.external_order_id}",
                                          f"order:{order.id}:return_handling", "order", order.id)
            sync_status(tx, self.gateway, self.books, order.id)
            return action

    def close_return_windows(self, mode: str, now: str | None = None, actor: str = "scheduler") -> list[str]:
        """Delivered orders whose return window has passed are complete; their provisions are released on close."""
        now = now or now_iso()
        closed = []
        with self.db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT o.id AS order_id, o.fulfillment_id FROM orders o JOIN actions a ON a.id = o.fulfillment_id "
                "WHERE o.mode = ? AND a.state = 'delivered' AND o.return_window_ends <= ?", (mode, now))
            for r in rows:
                self.gateway.transition(tx, r["fulfillment_id"], "completed", reason="return window closed", actor=actor)
                sync_status(tx, self.gateway, self.books, r["order_id"])
                closed.append(r["order_id"])
        return closed

    def cancel(self, action_id: str, reason: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.transition(tx, action_id, "cancelled", reason=reason, actor=actor)
            sync_status(tx, self.gateway, self.books, action.reference_id)
            return action
