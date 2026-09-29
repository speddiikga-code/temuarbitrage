"""Durable workflows and a scheduler on the database, in place of Temporal.

A workflow row holds its type, current step, payload (the checkpoint), attempts and lease.  Workers claim due rows
under a lease (`FOR UPDATE SKIP LOCKED` on PostgreSQL; SQLite serializes writers), run one step of the registered
handler, and record the outcome: continue to a step, wait until a time, done, or fail (retry with backoff up to
max_attempts, then failed).  A worker that dies mid-step leaves a lease that expires, and another worker picks the
step up; handlers are therefore idempotent (the books and the gateway already are, through event keys and
confirmation references).  Schedules start a workflow every interval with a dedupe key per slot, so two workers
ticking at once start it once.

Swapping Temporal in later: the handlers keep their (workflow, step) shape; `start`, `claim_due` and `run` become
Temporal client and activity calls, and the tables stay as the operational record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from .audit import AuditTrail
from .common import canonical_json, iso, loads, new_id, now_iso, parse_iso, utcnow
from .db import Database, Tx
from .errors import OpsError

BACKOFF_SECONDS = (5, 30, 120, 600, 1800)


@dataclass(frozen=True)
class Outcome:
    kind: str                           # continue | wait | done | fail
    step: str | None = None
    payload: dict[str, Any] | None = None
    delay_seconds: float = 0
    error: str | None = None
    retry: bool = True


def proceed(step: str, payload: dict | None = None, delay_seconds: float = 0) -> Outcome:
    return Outcome("continue", step, payload, delay_seconds)


def wait(seconds: float, payload: dict | None = None, step: str | None = None) -> Outcome:
    """Sleep, then run again: at the same step, or at `step` when given."""
    return Outcome("wait", step, payload, seconds)


def done(payload: dict | None = None) -> Outcome:
    return Outcome("done", None, payload)


def fail(error: str, retry: bool = True) -> Outcome:
    return Outcome("fail", None, None, 0, error, retry)


@dataclass
class Workflow:
    id: str
    type: str
    state: str
    step: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    next_run_at: str | None
    locked_by: str | None
    locked_until: str | None
    dedupe_key: str | None
    created_at: str
    updated_at: str
    last_error: str | None

    @classmethod
    def from_row(cls, r: dict) -> "Workflow":
        return cls(r["id"], r["type"], r["state"], r["step"], loads(r["payload"]), int(r["attempts"]), int(r["max_attempts"]),
                   r["next_run_at"], r["locked_by"], r["locked_until"], r["dedupe_key"], r["created_at"], r["updated_at"], r["last_error"])


Handler = Callable[[Workflow], Outcome]


class WorkflowEngine:
    def __init__(self, db: Database, audit: AuditTrail | None = None):
        self.db = db
        self.audit = audit
        self.handlers: dict[str, Handler] = {}

    def register(self, workflow_type: str, handler: Handler) -> None:
        self.handlers[workflow_type] = handler

    # -- start -----------------------------------------------------------------------------------------

    def start(self, workflow_type: str, payload: dict | None = None, dedupe_key: str | None = None, run_at=None,
              max_attempts: int = 5, step: str = "start", tx: Tx | None = None) -> str:
        if tx is not None:
            return self._start(tx, workflow_type, payload or {}, dedupe_key, run_at, max_attempts, step)
        with self.db.transaction() as tx2:
            return self._start(tx2, workflow_type, payload or {}, dedupe_key, run_at, max_attempts, step)

    def _start(self, tx, workflow_type, payload, dedupe_key, run_at, max_attempts, step) -> str:
        if workflow_type not in self.handlers:
            raise OpsError(f"no handler registered for workflow type {workflow_type!r}")
        if dedupe_key:
            existing = tx.fetchone("SELECT id FROM workflows WHERE dedupe_key = ?", (dedupe_key,))
            if existing:
                return existing["id"]
        now = now_iso()
        row = {"id": new_id("wf"), "type": workflow_type, "state": "pending", "step": step, "payload": canonical_json(payload),
               "attempts": 0, "max_attempts": max_attempts, "next_run_at": iso(run_at) if run_at else now, "locked_by": None,
               "locked_until": None, "dedupe_key": dedupe_key, "created_at": now, "updated_at": now, "last_error": None}
        tx.execute("INSERT INTO workflows (" + ", ".join(row) + ") VALUES (" + ", ".join("?" for _ in row) + ")"
                   + (" ON CONFLICT (dedupe_key) DO NOTHING" if dedupe_key else ""), tuple(row.values()))
        if dedupe_key:
            stored = tx.fetchone("SELECT id FROM workflows WHERE dedupe_key = ?", (dedupe_key,))["id"]
            if stored != row["id"]:
                return stored
        self._event(tx, row["id"], step, "started", {})
        return row["id"]

    # -- claim and run -----------------------------------------------------------------------------------

    def claim_due(self, worker: str, limit: int = 10, lease_seconds: int = 60) -> list[Workflow]:
        now = utcnow()
        claimed = []
        with self.db.transaction() as tx:
            rows = tx.fetchall(
                "SELECT * FROM workflows WHERE state IN ('pending', 'waiting', 'running') "
                "AND (next_run_at IS NULL OR next_run_at <= ?) AND (locked_until IS NULL OR locked_until < ?) "
                "ORDER BY next_run_at LIMIT ?" + tx.skip_locked, (iso(now), iso(now), limit))
            for r in rows:
                tx.update("workflows", "id", r["id"], {"state": "running", "locked_by": worker,
                                                        "locked_until": iso(now + timedelta(seconds=lease_seconds)), "updated_at": iso(now)})
                claimed.append(Workflow.from_row(tx.fetchone("SELECT * FROM workflows WHERE id = ?", (r["id"],))))
        return claimed

    def run(self, wf: Workflow, worker: str) -> Workflow:
        handler = self.handlers.get(wf.type)
        if handler is None:
            outcome = fail(f"no handler for {wf.type}", retry=False)
        else:
            try:
                outcome = handler(wf)
            except Exception as e:  # a crashed step is a failed attempt, never a lost workflow
                outcome = fail(f"{type(e).__name__}: {e}")
        with self.db.transaction() as tx:
            current = tx.fetchone("SELECT * FROM workflows WHERE id = ?", (wf.id,))
            if current["locked_by"] != worker:
                raise OpsError(f"workflow {wf.id}: lease lost to {current['locked_by']}")
            self._apply(tx, Workflow.from_row(current), outcome)
            return Workflow.from_row(tx.fetchone("SELECT * FROM workflows WHERE id = ?", (wf.id,)))

    def _apply(self, tx, wf: Workflow, o: Outcome) -> None:
        now = utcnow()
        payload = {**wf.payload, **(o.payload or {})}
        changes: dict[str, Any] = {"payload": canonical_json(payload), "locked_by": None, "locked_until": None, "updated_at": iso(now)}
        if o.kind == "continue":
            changes.update({"state": "pending", "step": o.step, "attempts": 0, "next_run_at": iso(now + timedelta(seconds=o.delay_seconds)), "last_error": None})
            self._event(tx, wf.id, wf.step, "continue", {"to": o.step})
        elif o.kind == "wait":
            changes.update({"state": "waiting", "next_run_at": iso(now + timedelta(seconds=o.delay_seconds)), "last_error": None})
            if o.step:
                changes.update({"step": o.step, "attempts": 0})
            self._event(tx, wf.id, wf.step, "wait", {"seconds": o.delay_seconds, "then": o.step or wf.step})
        elif o.kind == "done":
            changes.update({"state": "done", "next_run_at": None, "last_error": None})
            self._event(tx, wf.id, wf.step, "done", {})
        elif o.kind == "fail":
            attempts = wf.attempts + 1
            if o.retry and attempts < wf.max_attempts:
                delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
                changes.update({"state": "pending", "attempts": attempts, "next_run_at": iso(now + timedelta(seconds=delay)), "last_error": o.error})
                self._event(tx, wf.id, wf.step, "retry", {"attempt": attempts, "error": o.error, "in_seconds": delay})
            else:
                changes.update({"state": "failed", "attempts": attempts, "next_run_at": None, "last_error": o.error})
                self._event(tx, wf.id, wf.step, "failed", {"error": o.error})
                if self.audit:
                    self.audit.record(tx, "workflow_engine", "workflow_failed", "workflows", wf.id, after={"type": wf.type, "step": wf.step, "error": o.error})
        else:
            raise OpsError(f"unknown outcome {o.kind}")
        tx.update("workflows", "id", wf.id, changes)

    def run_due(self, worker: str, limit: int = 10) -> int:
        n = 0
        for wf in self.claim_due(worker, limit):
            self.run(wf, worker)
            n += 1
        return n

    # -- schedules ---------------------------------------------------------------------------------------

    def add_schedule(self, name: str, workflow_type: str, interval_seconds: int, payload: dict | None = None, first_run_at=None) -> None:
        if workflow_type not in self.handlers:
            raise OpsError(f"no handler registered for workflow type {workflow_type!r}")
        with self.db.transaction() as tx:
            first = iso(first_run_at) if first_run_at else now_iso()
            if tx.fetchone("SELECT name FROM schedules WHERE name = ?", (name,)):
                tx.update("schedules", "name", name, {"workflow_type": workflow_type, "interval_seconds": interval_seconds,
                                                      "payload": canonical_json(payload or {})})
            else:
                tx.insert("schedules", {"name": name, "workflow_type": workflow_type, "interval_seconds": interval_seconds,
                                        "payload": canonical_json(payload or {}), "next_run_at": first, "last_started_at": None, "enabled": 1})

    def tick(self, now=None) -> list[str]:
        """Start every schedule that is due, once per slot even with several workers ticking."""
        now = now or utcnow()
        started = []
        with self.db.transaction() as tx:
            tx.lock("schedules")
            for s in tx.fetchall("SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ? ORDER BY name", (iso(now),)):
                slot = s["next_run_at"]
                wf_id = self._start(tx, s["workflow_type"], loads(s["payload"]), f"schedule:{s['name']}@{slot}", None, 5, "start")
                started.append(wf_id)
                next_run = parse_iso(slot)
                while next_run <= now:
                    next_run += timedelta(seconds=int(s["interval_seconds"]))
                tx.update("schedules", "name", s["name"], {"next_run_at": iso(next_run), "last_started_at": iso(now)})
        return started

    # -- reading -----------------------------------------------------------------------------------------

    def get(self, tx: Tx, workflow_id: str) -> Workflow:
        row = tx.fetchone("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        if not row:
            raise OpsError(f"unknown workflow {workflow_id}")
        return Workflow.from_row(row)

    def list(self, tx: Tx, state: str | None = None, limit: int = 100) -> list[Workflow]:
        if state:
            rows = tx.fetchall("SELECT * FROM workflows WHERE state = ? ORDER BY updated_at DESC LIMIT ?", (state, limit))
        else:
            rows = tx.fetchall("SELECT * FROM workflows ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [Workflow.from_row(r) for r in rows]

    def events(self, tx: Tx, workflow_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY at, id", (workflow_id,))

    def _event(self, tx, workflow_id: str, step: str, event: str, detail: dict) -> None:
        # microsecond timestamps keep the event order readable when several happen within one second
        tx.insert("workflow_events", {"id": new_id("wfe"), "workflow_id": workflow_id, "step": step, "event": event,
                                      "at": utcnow().isoformat(), "detail": canonical_json(detail)})
