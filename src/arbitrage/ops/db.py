"""One small database layer for SQLite (stdlib; tests and local runs) and PostgreSQL (psycopg; the deployed stack).

SQL is written once, with `?` placeholders and a portable subset: TEXT / INTEGER / BIGINT columns, timestamps as
ISO-8601 UTC text, JSON as text, money as integer KRW.  Booleans are stored as 0/1.

`Database.transaction()` yields a `Tx`.  Writers that must not interleave (budget reservations, workflow claims)
lock a row with `tx.lock()`:  `SELECT ... FOR UPDATE` on PostgreSQL; on SQLite every transaction opens with
BEGIN IMMEDIATE, which already takes the single write lock, so the lock is a no-op there.

URLs: `sqlite:///relative/or/absolute/path.db`, `sqlite:///:memory:`, `postgresql://user:pw@host:port/db`.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from typing import Any, Iterator

from .errors import OpsError

SQLITE_PREFIX = "sqlite:///"
POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def _adapt(params: tuple | list) -> tuple:
    out = []
    for p in params:
        if isinstance(p, bool):
            out.append(int(p))
        elif isinstance(p, datetime):
            out.append(p.isoformat(timespec="seconds"))
        else:
            out.append(p)
    return tuple(out)


class Tx:
    """A transaction on one connection. Rows come back as dicts."""

    def __init__(self, conn, dialect: str):
        self._conn = conn
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgresql" else sql

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        cur = self._conn.execute(self._sql(sql), _adapt(params))
        return cur.rowcount

    def fetchone(self, sql: str, params: tuple | list = ()) -> dict | None:
        cur = self._conn.execute(self._sql(sql), _adapt(params))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cur = self._conn.execute(self._sql(sql), _adapt(params))
        return [dict(r) for r in cur.fetchall()]

    def scalar(self, sql: str, params: tuple | list = (), default=0):
        row = self.fetchone(sql, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))

    def update(self, table: str, key: str, key_value: Any, changes: dict[str, Any]) -> int:
        sets = ", ".join(f"{c} = ?" for c in changes)
        return self.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", (*changes.values(), key_value))

    def lock(self, name: str) -> None:
        """Serialize writers that share `name`. PostgreSQL: row lock; SQLite: BEGIN IMMEDIATE already did it."""
        if self.dialect == "postgresql":
            self.execute("INSERT INTO locks (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (name,))
            self.execute("SELECT name FROM locks WHERE name = ? FOR UPDATE", (name,))

    @property
    def skip_locked(self) -> str:
        return " FOR UPDATE SKIP LOCKED" if self.dialect == "postgresql" else ""


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith(SQLITE_PREFIX):
            self.dialect = "sqlite"
            self._path = url[len(SQLITE_PREFIX):]
            self._memory = self._path == ":memory:"
            self._memory_conn = self._sqlite_connect() if self._memory else None
            self._memory_lock = threading.RLock()
        elif url.startswith(POSTGRES_PREFIXES):
            self.dialect = "postgresql"
            try:
                import psycopg  # noqa: F401
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise OpsError("PostgreSQL needs the 'postgres' extra: pip install -e '.[postgres]'") from e
        else:
            raise OpsError(f"unsupported database url {url!r}: use sqlite:///PATH or postgresql://...")

    # -- connections -------------------------------------------------------------------------------

    def _sqlite_connect(self):
        conn = sqlite3.connect(self._path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        if not self._memory:
            conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _pg_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        # client_encoding: a SQL_ASCII server would otherwise hand text back as bytes.
        return psycopg.connect(self.url, row_factory=dict_row, client_encoding="utf8")

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        if self.dialect == "sqlite":
            if self._memory:
                with self._memory_lock:
                    yield from self._sqlite_tx(self._memory_conn)
            else:
                conn = self._sqlite_connect()
                try:
                    yield from self._sqlite_tx(conn)
                finally:
                    conn.close()
        else:
            conn = self._pg_connect()
            try:
                with conn.transaction():
                    yield Tx(conn, "postgresql")
            finally:
                conn.close()

    @staticmethod
    def _sqlite_tx(conn) -> Iterator[Tx]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield Tx(conn, "sqlite")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    # -- schema --------------------------------------------------------------------------------------

    @staticmethod
    def _statements() -> list[str]:
        ddl = resources.files("arbitrage.ops").joinpath("schema.sql").read_text("utf-8")
        stripped = "\n".join(line.split("--", 1)[0] for line in ddl.splitlines())
        return [s.strip() for s in stripped.split(";") if s.strip()]

    def migrate(self) -> None:
        """Create every table that does not exist yet. Safe to run at every start."""
        serial = "BIGSERIAL PRIMARY KEY" if self.dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        with self.transaction() as tx:
            for statement in self._statements():
                tx.execute(statement.replace("{{BIGSERIAL}}", serial))

    def reset(self) -> None:
        """Drop every table. Tests only."""
        names = []
        for statement in self._statements():
            words = statement.split()
            if len(words) > 5 and words[0] == "CREATE" and words[1] == "TABLE":
                names.append(words[5] if words[2] == "IF" else words[2])
        with self.transaction() as tx:
            for name in reversed(names):
                tx.execute(f"DROP TABLE IF EXISTS {name}" + (" CASCADE" if self.dialect == "postgresql" else ""))
