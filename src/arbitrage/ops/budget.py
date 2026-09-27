"""Budget governor: how much may be committed right now, and the only way to commit it.

    available cash headroom = unrestricted settled cash − unpaid commitments − required reserves
    reinvestment budget     = max(0, min(rate × eligible unallocated realized profit, headroom, remaining exposure))

Unpaid commitments are supplier payables, accrued fees and every reservation that is still `reserved`, so
money one workflow has claimed is invisible to the next.  Reserves are the mandate's minimum cash, one month of
authorized operating expenses, the returns and dispute provisions and VAT owed.

`reserve()` runs in one transaction holding the `budget` lock (PostgreSQL row lock; SQLite's BEGIN IMMEDIATE),
re-reads every figure under the lock and only then inserts the reservation.  Two concurrent reservations
therefore cannot both fit into the same headroom or limit.  Initial-capital allocations and profit-funded
reinvestment are separate sources with separate ceilings; a reinvestment allocation counts against realized
profit for good, so the same earnings can never fund two purchases.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from . import ledger as L
from .audit import AuditTrail
from .common import LIVE, check_mode, new_id, now_iso
from .db import Database, Tx
from .errors import BudgetExceeded
from .ledger import Ledger
from .mandate import Mandate
from .metrics import compute

SOURCES = ("initial_capital", "reinvestment")
INVENTORY_PURPOSES = ("inventory", "sample")
ACTIVE = ("reserved", "committed")


@dataclass
class Headroom:
    mode: str
    settled_cash: int
    supplier_payables: int
    accrued_fees: int
    reserved_by_workflows: int
    min_cash_reserve: int
    operating_reserve: int
    returns_provision: int
    dispute_provision: int
    tax_payable: int
    available: int

    @property
    def unpaid_commitments(self) -> int:
        return self.supplier_payables + self.accrued_fees + self.reserved_by_workflows

    @property
    def required_reserves(self) -> int:
        return self.min_cash_reserve + self.operating_reserve + self.returns_provision + self.dispute_provision + self.tax_payable

    def as_dict(self) -> dict:
        d = asdict(self)
        d["unpaid_commitments"] = self.unpaid_commitments
        d["required_reserves"] = self.required_reserves
        return d


@dataclass
class ReinvestmentBudget:
    mode: str
    realized_profit: int
    already_allocated: int
    eligible_unallocated: int
    reinvestment_rate: float
    headroom_available: int
    remaining_exposure: int
    budget: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Reservation:
    id: str
    mode: str
    source: str
    purpose: str
    amount: int
    state: str
    committed_amount: int | None = None
    action_id: str | None = None
    workflow_id: str | None = None
    sku: str | None = None
    created_at: str = ""
    updated_at: str = ""
    note: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Reservation":
        return cls(row["id"], row["mode"], row["source"], row["purpose"], int(row["amount"]), row["state"],
                   None if row["committed_amount"] is None else int(row["committed_amount"]), row["action_id"],
                   row["workflow_id"], row["sku"], row["created_at"], row["updated_at"], row["note"])


class BudgetGovernor:
    def __init__(self, db: Database, mandate: Mandate, ledger: Ledger, audit: AuditTrail):
        self.db = db
        self.mandate = mandate
        self.ledger = ledger
        self.audit = audit

    # -- figures ---------------------------------------------------------------------------------------

    def headroom(self, tx: Tx, mode: str) -> Headroom:
        bal = self.ledger.balances(tx, mode)
        reserved = int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM budget_reservations WHERE mode = ? AND state = 'reserved'", (mode,)))
        h = Headroom(mode, bal[L.CASH], bal[L.PAYABLE], bal[L.ACCRUED_FEES], reserved,
                     self.mandate.krw("reserves.min_cash_reserve_krw"),
                     self.mandate.krw("funding.authorized_operating_expenses_krw"),
                     bal[L.RETURNS_PROVISION], bal[L.DISPUTE_PROVISION], bal[L.TAX_PAYABLE], 0)
        h.available = max(0, h.settled_cash - h.unpaid_commitments - h.required_reserves)
        return h

    def exposure(self, tx: Tx, mode: str) -> int:
        """Capital at risk: inventory, prepaid purchases and money reserved but not yet spent."""
        bal = self.ledger.balances(tx, mode)
        reserved = int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM budget_reservations WHERE mode = ? AND state = 'reserved'", (mode,)))
        return bal[L.INVENTORY] + bal[L.PREPAID] + reserved

    def sku_exposure(self, tx: Tx, mode: str, sku: str) -> int:
        lots = int(tx.scalar("SELECT COALESCE(SUM(remaining * unit_cost), 0) FROM inventory_lots WHERE mode = ? AND sku = ?", (mode, sku)))
        reserved = int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM budget_reservations WHERE mode = ? AND sku = ? AND state = 'reserved'", (mode, sku)))
        prepaid = int(tx.scalar(
            "SELECT COALESCE(SUM(amount_krw), 0) FROM actions WHERE mode = ? AND sku = ? AND kind IN ('supplier_purchase', 'sample_purchase') "
            "AND state IN ('paid', 'shipped')", (mode, sku)))
        return lots + reserved + prepaid

    def daily_spend(self, tx: Tx, mode: str, day: str | None = None) -> int:
        day = day or date.today().isoformat()
        return int(tx.scalar(
            "SELECT COALESCE(SUM(COALESCE(committed_amount, amount)), 0) FROM budget_reservations "
            "WHERE mode = ? AND state IN ('reserved', 'committed') AND created_at >= ?", (mode, day)))

    def allocated(self, tx: Tx, mode: str, source: str) -> int:
        return int(tx.scalar(
            "SELECT COALESCE(SUM(COALESCE(committed_amount, amount)), 0) FROM budget_reservations "
            "WHERE mode = ? AND source = ? AND state IN ('reserved', 'committed')", (mode, source)))

    def initial_capital_remaining(self, tx: Tx, mode: str) -> int:
        return self.mandate.krw("funding.initial_capital_krw") - self.allocated(tx, mode, "initial_capital")

    def reinvestment_budget(self, tx: Tx, mode: str) -> ReinvestmentBudget:
        realized = compute(tx, self.ledger, mode).realized_profit
        allocated = self.allocated(tx, mode, "reinvestment")
        eligible = max(0, realized - allocated)
        rate = self.mandate.rate("reinvestment.reinvestment_rate")
        headroom = self.headroom(tx, mode).available
        remaining_exposure = max(0, self.mandate.krw("limits.max_total_exposure_krw") - self.exposure(tx, mode))
        budget = max(0, min(int(rate * eligible), headroom, remaining_exposure))
        return ReinvestmentBudget(mode, realized, allocated, eligible, rate, headroom, remaining_exposure, budget)

    def cumulative_loss(self, tx: Tx, mode: str) -> int:
        return max(0, self.ledger.total(tx, mode, type="expense") - self.ledger.total(tx, mode, type="revenue"))

    # -- the checks ----------------------------------------------------------------------------------

    def problems(self, tx: Tx, mode: str, amount: int, purpose: str, source: str, sku: str | None = None) -> list[str]:
        """Every reason this reservation must not happen. Empty means it may. Call under the budget lock."""
        m = self.mandate
        out: list[str] = []
        check_mode(mode)
        if source not in SOURCES:
            return [f"source must be one of {SOURCES}"]
        if mode == LIVE and m.environment != LIVE:
            out.append(f"{m.path} is a {m.environment} mandate; it cannot fund live spending")
        if mode == LIVE and not m.complete:
            out.append(f"mandate has pending fields: {', '.join(m.pending_fields()[:3])}...")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            return out + ["amount must be a positive integer number of KRW"]
        if amount > m.krw("limits.max_transaction_krw"):
            out.append(f"amount {amount:,} exceeds the transaction limit {m.krw('limits.max_transaction_krw'):,}")
        spent = self.daily_spend(tx, mode)
        if spent + amount > m.krw("limits.max_daily_spend_krw"):
            out.append(f"daily spend {spent:,} + {amount:,} exceeds the daily limit {m.krw('limits.max_daily_spend_krw'):,}")
        exposure = self.exposure(tx, mode)
        if exposure + amount > m.krw("limits.max_total_exposure_krw"):
            out.append(f"exposure {exposure:,} + {amount:,} exceeds the exposure limit {m.krw('limits.max_total_exposure_krw'):,}")
        if purpose in INVENTORY_PURPOSES:
            if exposure + amount > m.krw("limits.max_inventory_value_krw"):
                out.append(f"inventory {exposure:,} + {amount:,} exceeds the inventory limit {m.krw('limits.max_inventory_value_krw'):,}")
            if sku:
                sku_exp = self.sku_exposure(tx, mode, sku)
                if sku_exp + amount > m.krw("limits.max_sku_exposure_krw"):
                    out.append(f"{sku}: exposure {sku_exp:,} + {amount:,} exceeds the per-product limit {m.krw('limits.max_sku_exposure_krw'):,}")
        loss = self.cumulative_loss(tx, mode)
        if loss > m.krw("limits.max_cumulative_loss_krw"):
            out.append(f"cumulative loss {loss:,} exceeds the mandate's maximum {m.krw('limits.max_cumulative_loss_krw'):,}")
        headroom = self.headroom(tx, mode)
        if amount > headroom.available:
            out.append(f"amount {amount:,} exceeds available cash headroom {headroom.available:,} "
                       f"(settled {headroom.settled_cash:,} − commitments {headroom.unpaid_commitments:,} − reserves {headroom.required_reserves:,})")
        if source == "initial_capital":
            left = self.initial_capital_remaining(tx, mode)
            if amount > left:
                out.append(f"amount {amount:,} exceeds unallocated initial capital {left:,}")
        else:
            rb = self.reinvestment_budget(tx, mode)
            if amount > rb.budget:
                out.append(f"amount {amount:,} exceeds the reinvestment budget {rb.budget:,} "
                           f"(realized {rb.realized_profit:,} − allocated {rb.already_allocated:,} at {rb.reinvestment_rate:.0%}, "
                           f"headroom {rb.headroom_available:,}, exposure left {rb.remaining_exposure:,})")
        return out

    # -- the only way to commit money ----------------------------------------------------------------

    def reserve(self, mode: str, amount: int, purpose: str, source: str, *, action_id: str | None = None,
                workflow_id: str | None = None, sku: str | None = None, actor: str = "system",
                note: str | None = None, tx: Tx | None = None) -> Reservation:
        if tx is not None:
            return self._reserve(tx, mode, amount, purpose, source, action_id, workflow_id, sku, actor, note)
        with self.db.transaction() as tx2:
            return self._reserve(tx2, mode, amount, purpose, source, action_id, workflow_id, sku, actor, note)

    def _reserve(self, tx, mode, amount, purpose, source, action_id, workflow_id, sku, actor, note) -> Reservation:
        tx.lock("budget")
        problems = self.problems(tx, mode, amount, purpose, source, sku)
        if problems:
            self.audit.record(tx, actor, "reservation_refused", "budget_reservations", action_id,
                              after={"mode": mode, "amount": amount, "purpose": purpose, "source": source, "problems": problems})
            raise BudgetExceeded("; ".join(problems))
        now = now_iso()
        row = {"id": new_id("rsv"), "mode": mode, "source": source, "purpose": purpose, "amount": amount,
               "committed_amount": None, "state": "reserved", "action_id": action_id, "workflow_id": workflow_id,
               "sku": sku, "created_at": now, "updated_at": now, "note": note}
        tx.insert("budget_reservations", row)
        self.audit.record(tx, actor, "reserved", "budget_reservations", row["id"], after=row)
        return Reservation.from_row(row)

    def commit(self, tx: Tx, reservation_id: str, actual_amount: int | None = None, actor: str = "system") -> Reservation:
        """The money was really sent: fix the amount. Spending more than reserved is refused."""
        tx.lock("budget")
        row = tx.fetchone("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,))
        if not row:
            raise BudgetExceeded(f"unknown reservation {reservation_id}")
        if row["state"] == "committed":
            return Reservation.from_row(row)
        if row["state"] != "reserved":
            raise BudgetExceeded(f"reservation {reservation_id} is {row['state']}, not reserved")
        actual = int(row["amount"]) if actual_amount is None else int(actual_amount)
        if actual < 0 or actual > int(row["amount"]):
            raise BudgetExceeded(f"committed amount {actual:,} outside the reserved {int(row['amount']):,}")
        tx.update("budget_reservations", "id", reservation_id, {"state": "committed", "committed_amount": actual, "updated_at": now_iso()})
        self.audit.record(tx, actor, "committed", "budget_reservations", reservation_id, before=row, after={"committed_amount": actual})
        return Reservation.from_row(tx.fetchone("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,)))

    def release(self, tx: Tx, reservation_id: str, actor: str = "system", reason: str = "") -> Reservation:
        """Nothing was spent (refused, cancelled, failed): give the headroom back."""
        tx.lock("budget")
        row = tx.fetchone("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,))
        if not row:
            raise BudgetExceeded(f"unknown reservation {reservation_id}")
        if row["state"] == "committed":
            raise BudgetExceeded(f"reservation {reservation_id} was committed; book a supplier refund instead")
        if row["state"] == "reserved":
            tx.update("budget_reservations", "id", reservation_id, {"state": "released", "updated_at": now_iso(), "note": reason or row["note"]})
            self.audit.record(tx, actor, "released", "budget_reservations", reservation_id, before=row, after={"reason": reason})
        return Reservation.from_row(tx.fetchone("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,)))

    def get(self, tx: Tx, reservation_id: str) -> Reservation | None:
        row = tx.fetchone("SELECT * FROM budget_reservations WHERE id = ?", (reservation_id,))
        return Reservation.from_row(row) if row else None

    def active_reservations(self, tx: Tx, mode: str) -> list[Reservation]:
        rows = tx.fetchall("SELECT * FROM budget_reservations WHERE mode = ? AND state IN ('reserved', 'committed') ORDER BY created_at", (mode,))
        return [Reservation.from_row(r) for r in rows]
