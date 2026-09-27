"""Orders: the row that ties a customer payment and a fulfillment together, and its summary status."""

from __future__ import annotations

from .books import Books, Order, order_from_row
from .db import Tx
from .errors import OpsError
from .gateway import ActionGateway

SETTLED_STATES = ("settled", "partially_refunded", "dispute_won")


def load_order(tx: Tx, order_id: str) -> tuple[dict, Order]:
    row = tx.fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not row:
        raise OpsError(f"unknown order {order_id}")
    return row, order_from_row(row)


def has_confirmation(tx: Tx, action_id: str, kind: str) -> bool:
    return tx.fetchone("SELECT id FROM external_confirmations WHERE action_id = ? AND kind = ?", (action_id, kind)) is not None


def sync_status(tx: Tx, gateway: ActionGateway, books: Books, order_id: str) -> str:
    """Recompute the order's summary status from its payment and fulfillment actions; release provisions on close."""
    row, order = load_order(tx, order_id)
    payment = gateway.get(tx, row["payment_id"]) if row["payment_id"] else None
    fulfillment = gateway.get(tx, row["fulfillment_id"]) if row["fulfillment_id"] else None
    ps = payment.state if payment else "created"
    fs = fulfillment.state if fulfillment else None
    settled = payment is not None and (ps == "settled" or has_confirmation(tx, payment.id, "settlement"))
    if ps == "refunded":
        status = "refunded"
    elif ps == "dispute_lost":
        status = "chargeback"
    elif ps == "disputed":
        status = "disputed"
    elif settled and fs == "completed":
        status = "closed"
    elif settled:
        status = "settled"
    elif fs in ("shipped", "delivered", "completed"):
        status = "fulfilled"
    elif ps in ("captured", "partially_refunded", "dispute_won"):
        status = "paid"
    elif ps in ("voided", "failed"):
        status = "cancelled"
    else:
        status = "placed"
    if status != row["status"]:
        tx.update("orders", "id", order_id, {"status": status})
    if status == "closed":
        books.release_provisions(tx, order)
    return status
