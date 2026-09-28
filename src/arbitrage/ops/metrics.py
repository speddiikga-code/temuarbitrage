"""The section-6 metrics, straight from the ledger and the orders table, always for one mode at a time.

Realized profit counts only orders whose cash has settled and whose return window has closed (or which ended
in a refund or chargeback); everything else is provisional and labelled so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import ledger as L
from .db import Tx
from .ledger import Ledger

FINAL_ORDER_STATES = ("closed", "refunded", "chargeback", "cancelled")
# A routed request is final once its charge settled and its dispute window closed, or it ended in a refund or chargeback.
FINAL_REQUEST_STATES = ("closed", "refunded", "chargeback", "cancelled", "failed")


@dataclass
class Metrics:
    mode: str
    orders_placed: int = 0
    requests_routed: int = 0          # GlobalCompute Router requests (any state)
    gross_sales: int = 0
    net_revenue: int = 0
    payment_receivables: int = 0
    settled_cash: int = 0
    contribution_profit: int = 0
    operating_profit: int = 0
    realized_profit: int = 0          # settled and past the return window; the only number that counts toward the goal
    provisional_profit: int = 0       # operating profit not yet realized
    inventory_value: int = 0
    outstanding_purchases: int = 0    # paid to suppliers, not received
    outstanding_liabilities: int = 0
    provisions: int = 0               # returns + disputes
    tax_payable: int = 0
    variable_costs: dict[str, int] = field(default_factory=dict)
    fixed_costs: dict[str, int] = field(default_factory=dict)
    trial_balance_ok: bool = True
    label: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def compute(tx: Tx, ledger: Ledger, mode: str) -> Metrics:
    bal = ledger.balances(tx, mode)
    m = Metrics(mode=mode)
    m.orders_placed = int(tx.scalar("SELECT COUNT(*) FROM orders WHERE mode = ?", (mode,)))
    m.requests_routed = int(tx.scalar("SELECT COUNT(*) FROM routed_requests WHERE mode = ?", (mode,)))
    m.gross_sales = bal[L.GROSS_SALES]
    m.net_revenue = bal[L.GROSS_SALES] - bal[L.DISCOUNTS] - bal[L.REFUNDS]
    m.payment_receivables = bal[L.RECEIVABLE]
    m.settled_cash = bal[L.CASH]
    variable = {a.name: bal[a.code] for a in L.CHART if a.type == "expense" and not a.fixed and bal[a.code]}
    fixed = {a.name: bal[a.code] for a in L.CHART if a.fixed and bal[a.code]}
    m.variable_costs = variable
    m.fixed_costs = fixed
    m.contribution_profit = m.net_revenue - sum(variable.values())
    m.operating_profit = m.contribution_profit - sum(fixed.values())
    m.inventory_value = bal[L.INVENTORY]
    m.outstanding_purchases = bal[L.PREPAID]
    m.outstanding_liabilities = ledger.total(tx, mode, type="liability")
    m.provisions = bal[L.RETURNS_PROVISION] + bal[L.DISPUTE_PROVISION]
    m.tax_payable = bal[L.TAX_PAYABLE]
    m.provisional_profit = _unrealized_order_contribution(tx, mode) + _unrealized_request_contribution(tx, mode)
    m.realized_profit = m.operating_profit - m.provisional_profit
    debits, credits = ledger.trial_balance(tx, mode)
    m.trial_balance_ok = debits == credits
    m.label = "SIMULATED: not real money" if mode == "simulated" else "live: reconciled figures only"
    return m


def _unrealized_order_contribution(tx: Tx, mode: str) -> int:
    """Revenue minus expenses booked against orders that are not final yet."""
    marks = ", ".join("?" for _ in FINAL_ORDER_STATES)
    rows = tx.fetchall(
        "SELECT a.type AS type, COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c "
        "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id JOIN accounts a ON a.code = l.account_code "
        "JOIN orders o ON o.id = e.reference_id "
        f"WHERE e.mode = ? AND e.reference_type = 'order' AND o.status NOT IN ({marks}) AND a.type IN ('revenue', 'expense') "
        "GROUP BY a.type",
        (mode, *FINAL_ORDER_STATES),
    )
    total = 0
    for r in rows:
        if r["type"] == "revenue":
            total += int(r["c"]) - int(r["d"])
        else:
            total -= int(r["d"]) - int(r["c"])
    return total


def _unrealized_request_contribution(tx: Tx, mode: str) -> int:
    """Revenue minus expenses booked against routed requests that are not final yet (settled and past the window)."""
    marks = ", ".join("?" for _ in FINAL_REQUEST_STATES)
    rows = tx.fetchall(
        "SELECT a.type AS type, COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c "
        "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id JOIN accounts a ON a.code = l.account_code "
        "JOIN routed_requests r ON r.id = e.reference_id "
        f"WHERE e.mode = ? AND e.reference_type = 'routed_request' AND r.status NOT IN ({marks}) AND a.type IN ('revenue', 'expense') "
        "GROUP BY a.type",
        (mode, *FINAL_REQUEST_STATES),
    )
    total = 0
    for r in rows:
        if r["type"] == "revenue":
            total += int(r["c"]) - int(r["d"])
        else:
            total -= int(r["d"]) - int(r["c"])
    return total


def inventory_age(tx: Tx, mode: str) -> list[dict]:
    return tx.fetchall(
        "SELECT sku, SUM(remaining) AS units, SUM(remaining * unit_cost) AS value, MIN(received_at) AS oldest "
        "FROM inventory_lots WHERE mode = ? AND remaining > 0 GROUP BY sku ORDER BY oldest", (mode,))
