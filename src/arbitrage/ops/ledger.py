"""Double-entry ledger: a fixed chart of accounts, balanced journal entries, balances by account and category.

Amounts are integer KRW.  Every entry names the business event it books and carries an `event_key`; posting the
same key twice returns the first entry instead of booking again, so a redelivered webhook, a retried workflow
step or a duplicate settlement file can never double-post.  Entries are never updated or deleted: corrections
are new entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .common import canonical_json, check_mode, new_id, now_iso
from .db import Database, Tx
from .errors import OpsError


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: str          # asset | liability | equity | revenue | expense
    normal_side: str   # debit | credit
    category: str
    fixed: bool = False


CHART: tuple[Account, ...] = (
    Account("1000", "Settled cash", "asset", "debit", "settled_cash"),
    Account("1100", "Payment receivables", "asset", "debit", "receivable"),
    Account("1200", "Inventory", "asset", "debit", "inventory"),
    Account("1300", "Prepaid supplier purchases", "asset", "debit", "prepaid"),
    Account("2000", "Supplier payables", "liability", "credit", "payable"),
    Account("2200", "Dispute provision", "liability", "credit", "dispute_provision"),
    Account("2300", "Returns provision", "liability", "credit", "returns_provision"),
    Account("2400", "Taxes collected, payable to authorities", "liability", "credit", "tax_payable"),
    Account("2500", "Accrued marketplace fees", "liability", "credit", "accrued_fees"),
    Account("3000", "Owner capital", "equity", "credit", "capital"),
    Account("4000", "Gross sales", "revenue", "credit", "gross_sales"),
    Account("4100", "Discounts", "revenue", "debit", "contra_revenue"),
    Account("4200", "Refunds", "revenue", "debit", "contra_revenue"),
    Account("5000", "Cost of goods sold", "expense", "debit", "cogs"),
    Account("5100", "Freight", "expense", "debit", "variable"),
    Account("5200", "Duties and non-recoverable taxes", "expense", "debit", "variable"),
    Account("5300", "Marketplace fees", "expense", "debit", "variable"),
    Account("5310", "Payment processing fees", "expense", "debit", "variable"),
    Account("5400", "Currency conversion", "expense", "debit", "variable"),
    Account("5500", "Advertising", "expense", "debit", "variable"),
    Account("5600", "Return handling", "expense", "debit", "variable"),
    Account("5610", "Defects and write-offs", "expense", "debit", "variable"),
    Account("5620", "Chargebacks", "expense", "debit", "variable"),
    Account("5700", "Variable operating costs", "expense", "debit", "variable"),
    Account("5800", "Returns provision expense", "expense", "debit", "provision"),
    Account("5810", "Dispute provision expense", "expense", "debit", "provision"),
    Account("6000", "Software", "expense", "debit", "fixed", fixed=True),
    Account("6100", "AI credits", "expense", "debit", "fixed", fixed=True),
    Account("6200", "Infrastructure", "expense", "debit", "fixed", fixed=True),
    Account("6300", "Other fixed costs", "expense", "debit", "fixed", fixed=True),
)
ACCOUNTS: dict[str, Account] = {a.code: a for a in CHART}

# Friendly names used by the services and the CLI.
CASH, RECEIVABLE, INVENTORY, PREPAID = "1000", "1100", "1200", "1300"
PAYABLE, DISPUTE_PROVISION, RETURNS_PROVISION, TAX_PAYABLE, ACCRUED_FEES = "2000", "2200", "2300", "2400", "2500"
CAPITAL = "3000"
GROSS_SALES, DISCOUNTS, REFUNDS = "4000", "4100", "4200"
COGS, FREIGHT, DUTIES, MARKETPLACE_FEES, PAYMENT_FEES, FX_COST = "5000", "5100", "5200", "5300", "5310", "5400"
ADVERTISING, RETURN_HANDLING, WRITE_OFFS, CHARGEBACKS, VARIABLE_OPS = "5500", "5600", "5610", "5620", "5700"
RETURNS_PROVISION_EXPENSE, DISPUTE_PROVISION_EXPENSE = "5800", "5810"
SOFTWARE, AI_CREDITS, INFRASTRUCTURE, OTHER_FIXED = "6000", "6100", "6200", "6300"


@dataclass(frozen=True)
class Line:
    account: str
    debit: int = 0
    credit: int = 0
    memo: str | None = None


def dr(account: str, amount: int, memo: str | None = None) -> Line:
    return Line(account, debit=int(amount), memo=memo)


def cr(account: str, amount: int, memo: str | None = None) -> Line:
    return Line(account, credit=int(amount), memo=memo)


@dataclass(frozen=True)
class Entry:
    event: str
    description: str
    lines: tuple[Line, ...]
    event_key: str
    mode: str
    reference_type: str | None = None
    reference_id: str | None = None
    provisional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def validate(entry: Entry) -> None:
    lines = [l for l in entry.lines if l.debit or l.credit]
    if not lines:
        raise OpsError(f"entry {entry.event!r} has no lines")
    debits = credits = 0
    for line in lines:
        if line.account not in ACCOUNTS:
            raise OpsError(f"unknown account {line.account!r}")
        if line.debit < 0 or line.credit < 0 or (line.debit and line.credit):
            raise OpsError(f"line on {line.account} must be a positive debit or a positive credit")
        debits += line.debit
        credits += line.credit
    if debits != credits:
        raise OpsError(f"entry {entry.event!r} does not balance: debits {debits} != credits {credits}")
    check_mode(entry.mode)


class Ledger:
    def __init__(self, db: Database):
        self.db = db

    def ensure_chart(self, tx: Tx) -> None:
        for a in CHART:
            tx.execute(
                "INSERT INTO accounts (code, name, type, normal_side, category, fixed) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (code) DO NOTHING",
                (a.code, a.name, a.type, a.normal_side, a.category, a.fixed),
            )

    def post(self, tx: Tx, entry: Entry) -> str:
        """Book `entry`; return its id. The same event_key returns the existing entry and books nothing."""
        validate(entry)
        existing = tx.fetchone("SELECT id FROM journal_entries WHERE event_key = ?", (entry.event_key,))
        if existing:
            return existing["id"]
        entry_id = new_id("je")
        tx.insert("journal_entries", {
            "id": entry_id, "posted_at": now_iso(), "event": entry.event, "description": entry.description,
            "reference_type": entry.reference_type, "reference_id": entry.reference_id, "event_key": entry.event_key,
            "mode": entry.mode, "provisional": entry.provisional, "metadata": canonical_json(entry.metadata),
        })
        for n, line in enumerate(l for l in entry.lines if l.debit or l.credit):
            tx.insert("journal_lines", {
                "id": new_id("jl"), "entry_id": entry_id, "line_no": n, "account_code": line.account,
                "debit": line.debit, "credit": line.credit, "memo": line.memo,
            })
        return entry_id

    def posted(self, tx: Tx, event_key: str) -> bool:
        return tx.fetchone("SELECT id FROM journal_entries WHERE event_key = ?", (event_key,)) is not None

    # -- balances ------------------------------------------------------------------------------------

    @staticmethod
    def _signed(code: str, debit: int, credit: int) -> int:
        return debit - credit if ACCOUNTS[code].normal_side == "debit" else credit - debit

    def balances(self, tx: Tx, mode: str) -> dict[str, int]:
        """Balance of every account on its normal side (assets positive when debit-heavy, and so on)."""
        rows = tx.fetchall(
            "SELECT l.account_code AS code, COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c "
            "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id WHERE e.mode = ? GROUP BY l.account_code",
            (mode,),
        )
        out = {a.code: 0 for a in CHART}
        for r in rows:
            out[r["code"]] = self._signed(r["code"], int(r["d"]), int(r["c"]))
        return out

    def balance(self, tx: Tx, code: str, mode: str) -> int:
        row = tx.fetchone(
            "SELECT COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c FROM journal_lines l "
            "JOIN journal_entries e ON e.id = l.entry_id WHERE e.mode = ? AND l.account_code = ?",
            (mode, code),
        )
        return self._signed(code, int(row["d"]), int(row["c"]))

    def total(self, tx: Tx, mode: str, *, type: str | None = None, category: str | None = None,
              fixed: bool | None = None) -> int:
        bal = self.balances(tx, mode)
        total = 0
        for a in CHART:
            if type and a.type != type:
                continue
            if category and a.category != category:
                continue
            if fixed is not None and a.fixed != fixed:
                continue
            total += bal[a.code]
        return total

    def reference_balance(self, tx: Tx, code: str, reference_type: str, reference_id: str, mode: str) -> int:
        row = tx.fetchone(
            "SELECT COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c FROM journal_lines l "
            "JOIN journal_entries e ON e.id = l.entry_id WHERE e.mode = ? AND l.account_code = ? "
            "AND e.reference_type = ? AND e.reference_id = ?",
            (mode, code, reference_type, reference_id),
        )
        return self._signed(code, int(row["d"]), int(row["c"]))

    def trial_balance(self, tx: Tx, mode: str) -> tuple[int, int]:
        row = tx.fetchone(
            "SELECT COALESCE(SUM(l.debit), 0) AS d, COALESCE(SUM(l.credit), 0) AS c FROM journal_lines l "
            "JOIN journal_entries e ON e.id = l.entry_id WHERE e.mode = ?",
            (mode,),
        )
        return int(row["d"]), int(row["c"])

    def entries(self, tx: Tx, mode: str, reference_type: str | None = None, reference_id: str | None = None,
                limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM journal_entries WHERE mode = ?"
        params: list[Any] = [mode]
        if reference_type:
            sql += " AND reference_type = ?"
            params.append(reference_type)
        if reference_id:
            sql += " AND reference_id = ?"
            params.append(reference_id)
        sql += " ORDER BY posted_at, id LIMIT ?"
        params.append(limit)
        return tx.fetchall(sql, params)

    def lines(self, tx: Tx, entry_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM journal_lines WHERE entry_id = ? ORDER BY line_no", (entry_id,))
