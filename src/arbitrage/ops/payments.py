"""Customer payments: authorize, capture, settle, refund, dispute, each a separate state fed by processor events.

`apply_event` turns one processor event (webhook, settlement file row, dispute notice) into at most one transition
and one ledger posting.  The same event delivered again is recognized by its reference and changes nothing.  Refunds
we initiate go through the policy controller first; refunds the processor reports are recorded as facts.
"""

from __future__ import annotations

from typing import Any

from arbitrage.pricing import IMPORT_BASES

from .adapters import CONFIRMED
from .audit import AuditTrail
from .books import Books, Order
from .common import iso, new_id, now_iso, parse_iso, utcnow
from .db import Database
from .errors import OpsError
from .gateway import Action, ActionGateway
from .mandate import Mandate
from .orders import has_confirmation, load_order, sync_status
from .policy import ActionRequest, PolicyController
from datetime import timedelta

EVENT_TO_STATE = {"authorization": "authorized", "capture": "captured", "settlement": "settled", "void": "voided",
                  "dispute_opened": "disputed"}


class Payments:
    def __init__(self, db: Database, gateway: ActionGateway, books: Books, mandate: Mandate, policy: PolicyController,
                 audit: AuditTrail):
        self.db = db
        self.gateway = gateway
        self.books = books
        self.mandate = mandate
        self.policy = policy
        self.audit = audit

    def create_order(self, mode: str, channel: str, external_order_id: str, sku: str, quantity: int, gross_amount: int,
                     discount: int, tax_collected: int, expected_fee: int, processor: str, import_mode: str,
                     actor: str = "channel", placed_at: str | None = None) -> tuple[Order, Action]:
        """Record a customer order and its payment action (idempotent on channel + external order id).

        `import_mode` says how the goods reach the customer through customs: commercial_resale (we imported stock),
        personal_use (구매대행: the customer is the importer) or genuine_sample. It is required and never defaulted.
        """
        if import_mode not in IMPORT_BASES:
            raise OpsError(f"order {external_order_id}: import_mode must be one of {IMPORT_BASES}, got {import_mode!r}")
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT * FROM orders WHERE channel = ? AND external_order_id = ? AND mode = ?",
                              (channel, external_order_id, mode))
            if row:
                _, order = load_order(tx, row["id"])
                return order, self.gateway.get(tx, row["payment_id"])
            if quantity <= 0 or gross_amount <= 0 or discount < 0 or tax_collected < 0 or gross_amount - discount <= 0:
                raise OpsError("order amounts do not make sense")
            order_id = new_id("ord")
            placed_at = placed_at or now_iso()
            request = ActionRequest("customer_payment", f"pay:{mode}:{channel}:{external_order_id}", mode,
                                    gross_amount - discount, gross_amount - discount, "KRW", processor, None, sku, "order", order_id,
                                    {"channel": channel, "external_order_id": external_order_id})
            action = self.gateway.submit(request, actor, tx)
            window_end = parse_iso(placed_at) + timedelta(days=self.mandate.days("reserves.refund_reserve_days"))
            row = {"id": order_id, "channel": channel, "external_order_id": external_order_id, "sku": sku, "quantity": quantity,
                   "gross_amount": gross_amount, "discount": discount, "tax_collected": tax_collected, "expected_fee": expected_fee,
                   "currency": "KRW", "import_mode": import_mode, "customs_code_provided": 0, "placed_at": placed_at,
                   "status": "placed", "return_window_ends": iso(window_end),
                   "payment_id": action.id, "fulfillment_id": None, "mode": mode}
            tx.insert("orders", row)
            self.audit.record(tx, actor, "order_created", "orders", order_id, after=row)
            _, order = load_order(tx, order_id)
            return order, action

    # -- events from the processor --------------------------------------------------------------------

    def apply_event(self, event: dict[str, Any], actor: str = "processor") -> Action:
        """One processor event: {source, kind, reference, mode, order_id, amount, currency, payout, marketplace_fee,
        payment_fee, outcome ('won'|'lost' for dispute_closed), fee}."""
        with self.db.transaction() as tx:
            return self._apply(tx, event, actor)

    def _apply(self, tx, event: dict[str, Any], actor: str) -> Action:
        row, order = load_order(tx, event["order_id"])
        action = self.gateway.get(tx, row["payment_id"])
        kind = event["kind"]
        amount = int(event.get("amount") or order.receivable)
        if kind == "refund":
            refunded = self._refunded_total(tx, action.id) + amount
            to_state = "refunded" if refunded >= order.receivable else "partially_refunded"
        elif kind == "dispute_closed":
            to_state = "dispute_won" if event.get("outcome") == "won" else "dispute_lost"
        else:
            try:
                to_state = EVENT_TO_STATE[kind]
            except KeyError:
                raise OpsError(f"unknown payment event kind {kind!r}") from None
        if kind == "authorization" and event.get("status", "confirmed") == "failed":
            return self.gateway.transition(tx, action.id, "failed", reason=event.get("error", "declined"), actor=actor)
        confirmation = {"source": event["source"], "kind": kind, "reference": event["reference"], "mode": event.get("mode", action.mode),
                        "amount": amount, "currency": event.get("currency", "KRW"), "payload": event.get("payload", {})}
        action = self.gateway.transition(tx, action.id, to_state, confirmation=confirmation, actor=actor)
        key = f"order:{order.id}:{kind}:{event['reference']}"
        if kind == "capture":
            self.books.record_sale(tx, order)
        elif kind == "settlement":
            payout = int(event.get("payout", order.receivable - int(event.get("marketplace_fee", order.expected_fee)) - int(event.get("payment_fee", 0))))
            self.books.record_settlement(tx, order, payout, int(event.get("marketplace_fee", order.expected_fee)),
                                         int(event.get("payment_fee", 0)), key)
        elif kind == "refund":
            self.books.record_refund(tx, order, amount, settled=has_confirmation(tx, action.id, "settlement"), event_key=key)
            if to_state == "refunded":
                self.books.release_provisions(tx, order, ("returns",))
        elif kind == "dispute_opened":
            self.books.open_dispute(tx, order, amount, key)
        elif kind == "dispute_closed":
            if to_state == "dispute_won":
                self.books.release_provisions(tx, order, ("dispute",))
            else:
                self.books.lose_dispute(tx, order, amount, int(event.get("fee", 0)), key)
        sync_status(tx, self.gateway, self.books, order.id)
        return action

    def _refunded_total(self, tx, action_id: str) -> int:
        return int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM external_confirmations WHERE action_id = ? AND kind = 'refund'", (action_id,)))

    # -- refunds we initiate ----------------------------------------------------------------------------

    def refund(self, order_id: str, amount: int, reason: str, actor: str = "support") -> Action:
        """A policy-compliant refund: checked by the policy controller, sent through the processor adapter, then recorded."""
        with self.db.transaction() as tx:
            row, order = load_order(tx, order_id)
            action = self.gateway.get(tx, row["payment_id"])
            request = ActionRequest("refund", f"refund:{order_id}:{self._refunded_total(tx, action.id)}:{amount}", action.mode,
                                    amount, amount, "KRW", action.integration, None, order.sku, "order", order_id, {"reason": reason})
            self.policy.evaluate(tx, request, actor).raise_if_refused()
            if amount <= 0 or self._refunded_total(tx, action.id) + amount > order.receivable:
                raise OpsError(f"refund {amount} exceeds what the customer paid")
            capture = tx.fetchone("SELECT external_reference FROM external_confirmations WHERE action_id = ? AND kind = 'capture'", (action.id,))
            if not capture:
                raise OpsError(f"order {order_id} has no captured payment to refund")
            adapter = self.gateway.adapter(tx, action)
            result = adapter.refund(action.id, capture["external_reference"], amount, "KRW")
            if result.status == CONFIRMED:
                return self._apply(tx, {"source": result.source, "kind": "refund", "reference": result.reference, "mode": result.mode,
                                        "order_id": order_id, "amount": amount, "currency": "KRW", "payload": {"reason": reason}}, actor)
            self.gateway.note_error(tx, action.id, result.error or "refund failed")
        raise OpsError(f"processor did not confirm the refund: {result.error}")
