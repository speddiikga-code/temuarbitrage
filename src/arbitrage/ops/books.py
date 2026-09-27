"""Bookkeeping: business events turned into balanced ledger entries.

Money is recognized when it moves and goods when they arrive; nothing here is called without an external
confirmation record (the gateway enforces that).  Inventory is bought once (cash out, inventory up) and expensed
once (COGS when the unit ships).  Every sale books conservative provisions for returns and disputes, released
when the return window closes or the case is decided.  Every method is idempotent through the entry's event_key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import ledger as L
from .common import new_id, now_iso, parse_iso, utcnow
from .db import Tx
from .errors import OpsError
from .ledger import Entry, Ledger, cr, dr
from .mandate import Mandate


@dataclass(frozen=True)
class Order:
    id: str
    channel: str
    external_order_id: str
    sku: str
    quantity: int
    gross_amount: int       # customer price before discount, VAT included
    discount: int
    tax_collected: int      # VAT remitted to the authorities, never revenue
    expected_fee: int       # marketplace fee accrued at capture
    mode: str
    currency: str = "KRW"

    @property
    def receivable(self) -> int:
        return self.gross_amount - self.discount

    @property
    def net_revenue(self) -> int:
        return self.gross_amount - self.discount - self.tax_collected


def order_from_row(row: dict) -> Order:
    return Order(row["id"], row["channel"], row["external_order_id"], row["sku"], int(row["quantity"]),
                 int(row["gross_amount"]), int(row["discount"]), int(row["tax_collected"]), int(row["expected_fee"]),
                 row["mode"], row["currency"])


class Books:
    def __init__(self, ledger: Ledger, mandate: Mandate):
        self.ledger = ledger
        self.mandate = mandate

    def _post(self, tx: Tx, event: str, description: str, lines, key: str, mode: str, ref_type=None, ref_id=None,
              provisional=False, metadata=None) -> str:
        entry = Entry(event, description, tuple(lines), key, mode, ref_type, ref_id, provisional, metadata or {})
        return self.ledger.post(tx, entry)

    # -- capital and purchases ------------------------------------------------------------------------

    def contribute_capital(self, tx: Tx, mode: str, amount: int, source: str, event_key: str) -> str:
        return self._post(tx, "capital_contribution", f"capital from {source}",
                          [dr(L.CASH, amount), cr(L.CAPITAL, amount)], event_key, mode, "funding", source)

    def pay_supplier(self, tx: Tx, mode: str, purchase_id: str, amount_krw: int, fx_cost_krw: int, event_key: str) -> str:
        """Cash leaves for a supplier order; the goods are not ours yet, so it is a prepayment, not inventory."""
        lines = [dr(L.PREPAID, amount_krw, "supplier payment"), cr(L.CASH, amount_krw)]
        if fx_cost_krw:
            lines += [dr(L.FX_COST, fx_cost_krw, "conversion cost"), cr(L.CASH, fx_cost_krw)]
        return self._post(tx, "supplier_payment", f"paid supplier for {purchase_id}", lines, event_key, mode,
                          "purchase", purchase_id)

    def receive_inventory(self, tx: Tx, mode: str, purchase_id: str, sku: str, quantity: int, prepaid_krw: int,
                          freight_krw: int, duties_krw: int, event_key: str) -> str | None:
        """Goods arrived: the prepayment (plus freight and duties paid on arrival) becomes an inventory lot.

        Returns the lot id, or None when this receipt was already booked.
        """
        if quantity <= 0:
            raise OpsError("received quantity must be positive")
        if self.ledger.posted(tx, event_key):
            return None
        total = prepaid_krw + freight_krw + duties_krw
        unit_cost = total // quantity
        remainder = total - unit_cost * quantity
        lines = [dr(L.INVENTORY, unit_cost * quantity, f"{quantity} x {sku} landed"), cr(L.PREPAID, prepaid_krw)]
        if remainder:
            lines.append(dr(L.WRITE_OFFS, remainder, "rounding"))
        if freight_krw + duties_krw:
            lines.append(cr(L.CASH, freight_krw + duties_krw, "freight and duties paid on arrival"))
        self._post(tx, "inventory_received", f"received {quantity} x {sku}", lines, event_key, mode, "purchase",
                   purchase_id, metadata={"freight_krw": freight_krw, "duties_krw": duties_krw})
        lot_id = new_id("lot")
        tx.insert("inventory_lots", {"id": lot_id, "sku": sku, "purchase_id": purchase_id, "quantity": quantity,
                                     "remaining": quantity, "unit_cost": unit_cost, "received_at": now_iso(), "mode": mode})
        return lot_id

    def expense_sample(self, tx: Tx, mode: str, purchase_id: str, sku: str, quantity: int, prepaid_krw: int,
                       freight_krw: int, duties_krw: int, event_key: str) -> str:
        """A sample arrived: it is an expense, never inventory (eligibility report, item 8)."""
        total = prepaid_krw + freight_krw + duties_krw
        lines = [dr(L.SAMPLES, total, f"{quantity} x {sku} sample"), cr(L.PREPAID, prepaid_krw)]
        if freight_krw + duties_krw:
            lines.append(cr(L.CASH, freight_krw + duties_krw, "freight and duties paid on arrival"))
        return self._post(tx, "sample_received", f"sample {quantity} x {sku}", lines, event_key, mode, "purchase", purchase_id)

    # -- sales ---------------------------------------------------------------------------------------

    def record_sale(self, tx: Tx, order: Order) -> str:
        """Payment captured: revenue, VAT owed, the expected marketplace fee and the two provisions."""
        net = order.net_revenue
        if net < 0 or order.receivable <= 0:
            raise OpsError(f"order {order.id}: amounts do not make sense")
        returns_provision = round(net * self.mandate.rate("reserves.refund_reserve_rate"))
        dispute_provision = round(net * self.mandate.rate("reserves.dispute_reserve_rate"))
        lines = [dr(L.RECEIVABLE, order.receivable), cr(L.GROSS_SALES, order.gross_amount - order.tax_collected)]
        if order.discount:
            lines.append(dr(L.DISCOUNTS, order.discount))
        if order.tax_collected:
            lines.append(cr(L.TAX_PAYABLE, order.tax_collected))
        if order.expected_fee:
            lines += [dr(L.MARKETPLACE_FEES, order.expected_fee, "expected"), cr(L.ACCRUED_FEES, order.expected_fee)]
        if returns_provision:
            lines += [dr(L.RETURNS_PROVISION_EXPENSE, returns_provision), cr(L.RETURNS_PROVISION, returns_provision)]
        if dispute_provision:
            lines += [dr(L.DISPUTE_PROVISION_EXPENSE, dispute_provision), cr(L.DISPUTE_PROVISION, dispute_provision)]
        return self._post(tx, "sale", f"order {order.external_order_id} on {order.channel}", lines,
                          f"order:{order.id}:sale", order.mode, "order", order.id, provisional=True,
                          metadata={"returns_provision": returns_provision, "dispute_provision": dispute_provision})

    def record_fulfillment(self, tx: Tx, order: Order, shipping_krw: int) -> int:
        """Units shipped: COGS from the FIFO lots of the sku, outbound shipping as freight. Returns the COGS."""
        key = f"order:{order.id}:fulfillment"
        existing = tx.fetchone("SELECT metadata FROM journal_entries WHERE event_key = ?", (key,))
        if existing:
            from .common import loads
            return int(loads(existing["metadata"]).get("cogs", 0))
        cogs = self._consume_inventory(tx, order.mode, order.sku, order.quantity)
        lines = [dr(L.COGS, cogs, f"{order.quantity} x {order.sku}"), cr(L.INVENTORY, cogs)]
        if shipping_krw:
            lines += [dr(L.FREIGHT, shipping_krw, "outbound shipping"), cr(L.CASH, shipping_krw)]
        self._post(tx, "fulfillment", f"shipped order {order.external_order_id}", lines, key, order.mode, "order",
                   order.id, metadata={"cogs": cogs, "shipping_krw": shipping_krw})
        return cogs

    def _consume_inventory(self, tx: Tx, mode: str, sku: str, quantity: int) -> int:
        lots = tx.fetchall("SELECT * FROM inventory_lots WHERE sku = ? AND mode = ? AND remaining > 0 ORDER BY received_at, id",
                           (sku, mode))
        available = sum(int(l["remaining"]) for l in lots)
        if available < quantity:
            raise OpsError(f"insufficient inventory for {sku}: need {quantity}, have {available}")
        cost = 0
        left = quantity
        for lot in lots:
            take = min(left, int(lot["remaining"]))
            cost += take * int(lot["unit_cost"])
            tx.update("inventory_lots", "id", lot["id"], {"remaining": int(lot["remaining"]) - take})
            left -= take
            if left == 0:
                break
        return cost

    def record_settlement(self, tx: Tx, order: Order, payout_krw: int, marketplace_fee_krw: int,
                          payment_fee_krw: int, event_key: str) -> str:
        """The processor paid out: receivable becomes settled cash, the fee estimate is trued up."""
        if payout_krw + marketplace_fee_krw + payment_fee_krw != order.receivable:
            raise OpsError(
                f"order {order.id}: payout {payout_krw} + fees {marketplace_fee_krw + payment_fee_krw} != receivable {order.receivable}"
            )
        lines = [dr(L.CASH, payout_krw, "payout"), cr(L.RECEIVABLE, order.receivable)]
        if order.expected_fee:
            lines.append(dr(L.ACCRUED_FEES, order.expected_fee))
        diff = marketplace_fee_krw - order.expected_fee
        if diff > 0:
            lines.append(dr(L.MARKETPLACE_FEES, diff, "fee above estimate"))
        elif diff < 0:
            lines.append(cr(L.MARKETPLACE_FEES, -diff, "fee below estimate"))
        if payment_fee_krw:
            lines.append(dr(L.PAYMENT_FEES, payment_fee_krw))
        return self._post(tx, "settlement", f"settled order {order.external_order_id}", lines, event_key, order.mode,
                          "order", order.id, metadata={"payout_krw": payout_krw, "marketplace_fee_krw": marketplace_fee_krw})

    def record_refund(self, tx: Tx, order: Order, amount: int, settled: bool, event_key: str) -> str:
        """Customer refunded `amount`. Revenue and VAT owed go down; cash (or the receivable) goes down."""
        if amount <= 0 or amount > order.receivable:
            raise OpsError(f"order {order.id}: refund {amount} outside 0..{order.receivable}")
        tax_share = round(amount * order.tax_collected / order.receivable) if order.receivable else 0
        lines = [dr(L.REFUNDS, amount - tax_share), cr(L.CASH if settled else L.RECEIVABLE, amount)]
        if tax_share:
            lines.append(dr(L.TAX_PAYABLE, tax_share))
        return self._post(tx, "refund", f"refund {amount} on order {order.external_order_id}", lines, event_key,
                          order.mode, "order", order.id)

    def restock_return(self, tx: Tx, order: Order, quantity: int, handling_krw: int, event_key: str) -> str | None:
        """Returned units back in stock at their COGS; handling paid in cash. None if already booked."""
        if self.ledger.posted(tx, event_key):
            return None
        cogs_lines = tx.fetchone(
            "SELECT COALESCE(SUM(l.debit), 0) AS d FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
            "WHERE e.event_key = ? AND l.account_code = ?", (f"order:{order.id}:fulfillment", L.COGS))
        cogs = int(cogs_lines["d"]) if cogs_lines else 0
        unit_cost = cogs // order.quantity if order.quantity else 0
        back = unit_cost * quantity
        lines = []
        if back:
            lines += [dr(L.INVENTORY, back, "restocked"), cr(L.COGS, back)]
            tx.insert("inventory_lots", {"id": new_id("lot"), "sku": order.sku, "purchase_id": None, "quantity": quantity,
                                         "remaining": quantity, "unit_cost": unit_cost, "received_at": now_iso(), "mode": order.mode})
        if handling_krw:
            lines += [dr(L.RETURN_HANDLING, handling_krw), cr(L.CASH, handling_krw)]
        if not lines:
            return None
        return self._post(tx, "return_restocked", f"restocked {quantity} from order {order.external_order_id}", lines,
                          event_key, order.mode, "order", order.id)

    def release_provisions(self, tx: Tx, order: Order, which: tuple[str, ...] = ("returns", "dispute")) -> list[str]:
        """Return window closed (or case decided): reverse what is left of the order's provisions."""
        ids = []
        pairs = {"returns": (L.RETURNS_PROVISION, L.RETURNS_PROVISION_EXPENSE),
                 "dispute": (L.DISPUTE_PROVISION, L.DISPUTE_PROVISION_EXPENSE)}
        for name in which:
            liability, expense = pairs[name]
            left = self.ledger.reference_balance(tx, liability, "order", order.id, order.mode)
            key = f"order:{order.id}:{name}_provision_release"
            if left > 0 and not self.ledger.posted(tx, key):
                ids.append(self._post(tx, f"{name}_provision_release", f"released {name} provision on order {order.external_order_id}",
                                      [dr(liability, left), cr(expense, left)], key, order.mode, "order", order.id))
        return ids

    def open_dispute(self, tx: Tx, order: Order, amount: int, event_key: str) -> str | None:
        """Top the dispute provision up to the disputed amount."""
        held = self.ledger.reference_balance(tx, L.DISPUTE_PROVISION, "order", order.id, order.mode)
        top_up = max(0, amount - held)
        if not top_up:
            return None
        return self._post(tx, "dispute_opened", f"dispute on order {order.external_order_id}",
                          [dr(L.DISPUTE_PROVISION_EXPENSE, top_up), cr(L.DISPUTE_PROVISION, top_up)], event_key,
                          order.mode, "order", order.id, provisional=True)

    def lose_dispute(self, tx: Tx, order: Order, amount: int, fee_krw: int, event_key: str) -> str:
        """Chargeback: the provision absorbs what it can, the rest is chargeback expense; cash leaves."""
        held = self.ledger.reference_balance(tx, L.DISPUTE_PROVISION, "order", order.id, order.mode)
        use = min(held, amount)
        lines = [cr(L.CASH, amount + fee_krw)]
        if use:
            lines.append(dr(L.DISPUTE_PROVISION, use))
        if amount - use:
            lines.append(dr(L.CHARGEBACKS, amount - use))
        if fee_krw:
            lines.append(dr(L.PAYMENT_FEES, fee_krw, "dispute fee"))
        return self._post(tx, "dispute_lost", f"chargeback on order {order.external_order_id}", lines, event_key,
                          order.mode, "order", order.id)

    # -- expenses ------------------------------------------------------------------------------------

    def record_expense(self, tx: Tx, mode: str, account: str, amount: int, description: str, event_key: str,
                       reference_type: str | None = None, reference_id: str | None = None) -> str:
        if L.ACCOUNTS[account].type != "expense":
            raise OpsError(f"{account} is not an expense account")
        return self._post(tx, "expense", description, [dr(account, amount), cr(L.CASH, amount)], event_key, mode,
                          reference_type, reference_id)

    def write_off_inventory(self, tx: Tx, mode: str, lot_id: str, quantity: int, reason: str, event_key: str) -> str | None:
        lot = tx.fetchone("SELECT * FROM inventory_lots WHERE id = ? AND mode = ?", (lot_id, mode))
        if not lot or int(lot["remaining"]) < quantity:
            raise OpsError(f"lot {lot_id}: cannot write off {quantity}")
        if self.ledger.posted(tx, event_key):
            return None
        amount = quantity * int(lot["unit_cost"])
        tx.update("inventory_lots", "id", lot_id, {"remaining": int(lot["remaining"]) - quantity})
        return self._post(tx, "inventory_write_off", f"wrote off {quantity} x {lot['sku']}: {reason}",
                          [dr(L.WRITE_OFFS, amount), cr(L.INVENTORY, amount)], event_key, mode, "lot", lot_id)

    # -- helpers -------------------------------------------------------------------------------------

    def return_window_end(self, placed_at: str):
        return parse_iso(placed_at) + timedelta(days=self.mandate.days("reserves.refund_reserve_days"))
