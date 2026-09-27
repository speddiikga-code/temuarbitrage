"""Deterministic orchestrator: assigns tasks to agent runs and enforces every charter limit.

Dedupes tasks by fingerprint, holds them until their dependencies are done, caps concurrency per role, delegation
depth, retries and credits per run, per parent and against the mandate's AI-credit budget.  A child run never holds
more permissions or credits than its parent.  Failed tasks retry with backoff, then escalate.  Nothing here
executes an external action: runs propose to the services, which decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .audit import AuditTrail
from .charters import Charter
from .common import canonical_json, fingerprint, iso, loads, new_id, now_iso, parse_iso, utcnow
from .db import Database, Tx
from .errors import OrchestrationError
from .mandate import Mandate
from .policy import PauseControl

BACKOFF_SECONDS = (60, 300, 900)


@dataclass
class Task:
    id: str
    role: str
    title: str
    state: str
    payload: dict[str, Any]
    depends_on: list[str]
    priority: int
    attempts: int
    parent_run_id: str | None
    depth: int
    run_id: str | None = None
    result: dict | None = None
    error: str | None = None
    not_before: str | None = None

    @classmethod
    def from_row(cls, r: dict) -> "Task":
        return cls(r["id"], r["role"], r["title"], r["state"], loads(r["payload"]), loads(r["depends_on"], []), int(r["priority"]),
                   int(r["attempts"]), r["parent_run_id"], int(r["depth"]), r["run_id"], loads(r["result"]) if r["result"] else None,
                   r["error"], r["not_before"])


@dataclass
class Run:
    id: str
    task_id: str
    role: str
    parent_run_id: str | None
    depth: int
    permissions: list[str]
    credits_allowed: int
    credits_used: int
    state: str
    worker: str | None
    started_at: str
    deadline_at: str
    task: Task | None = None

    @classmethod
    def from_row(cls, r: dict) -> "Run":
        return cls(r["id"], r["task_id"], r["role"], r["parent_run_id"], int(r["depth"]), loads(r["permissions"], []),
                   int(r["credits_allowed"]), int(r["credits_used"]), r["state"], r["worker"], r["started_at"], r["deadline_at"])


class Orchestrator:
    def __init__(self, db: Database, charters: dict[str, Charter], mandate: Mandate, audit: AuditTrail, pauses: PauseControl):
        self.db = db
        self.charters = charters
        self.mandate = mandate
        self.audit = audit
        self.pauses = pauses

    # -- submit ----------------------------------------------------------------------------------------

    def submit(self, role: str, title: str, payload: dict | None = None, depends_on: tuple[str, ...] = (), priority: int = 0,
               parent_run_id: str | None = None, actor: str = "system", tx: Tx | None = None) -> Task:
        if tx is not None:
            return self._submit(tx, role, title, payload or {}, list(depends_on), priority, parent_run_id, actor)
        with self.db.transaction() as tx2:
            return self._submit(tx2, role, title, payload or {}, list(depends_on), priority, parent_run_id, actor)

    def _submit(self, tx, role, title, payload, depends_on, priority, parent_run_id, actor) -> Task:
        charter = self.charters.get(role)
        if charter is None:
            raise OrchestrationError(f"no charter for role {role!r}")
        fp = fingerprint({"role": role, "payload": payload})
        existing = tx.fetchone("SELECT * FROM tasks WHERE fingerprint = ?", (fp,))
        if existing:
            return Task.from_row(existing)  # deduplicated: the same work is not queued twice
        depth = 0
        if parent_run_id:
            parent = self._run(tx, parent_run_id)
            if parent.state != "running":
                raise OrchestrationError(f"parent run {parent_run_id} is {parent.state}; only a running agent may delegate")
            depth = parent.depth + 1
            if depth > charter.max_delegation_depth or depth > self.charters[parent.role].max_delegation_depth:
                raise OrchestrationError(f"delegation depth {depth} exceeds the charter limit")
            # A child holds the intersection of its charter and its parent's permissions (equal or narrower, never wider).
            if not set(charter.permissions) & set(parent.permissions):
                raise OrchestrationError(f"child role {role} would hold no permission its parent {parent.role} has")
        for dep in depends_on:
            if not tx.fetchone("SELECT id FROM tasks WHERE id = ?", (dep,)):
                raise OrchestrationError(f"unknown dependency {dep}")
        now = now_iso()
        row = {"id": new_id("task"), "fingerprint": fp, "role": role, "title": title, "payload": canonical_json(payload),
               "depends_on": canonical_json(depends_on), "state": "queued", "priority": priority, "attempts": 0,
               "parent_run_id": parent_run_id, "depth": depth, "run_id": None, "result": None, "error": None, "not_before": None,
               "created_at": now, "updated_at": now}
        tx.execute("INSERT INTO tasks (" + ", ".join(row) + ") VALUES (" + ", ".join("?" for _ in row) + ") ON CONFLICT (fingerprint) DO NOTHING",
                   tuple(row.values()))
        stored = tx.fetchone("SELECT * FROM tasks WHERE fingerprint = ?", (fp,))
        if stored["id"] == row["id"]:
            self.audit.record(tx, actor, "task_submitted", "tasks", row["id"], after={"role": role, "title": title, "depth": depth})
        return Task.from_row(stored)

    # -- claim -----------------------------------------------------------------------------------------

    def claim(self, worker: str, roles: tuple[str, ...] | None = None, limit: int = 1) -> list[Run]:
        runs: list[Run] = []
        with self.db.transaction() as tx:
            tx.lock("orchestrator")
            if any(p["scope"] == "all" for p in self.pauses.active(tx)):
                return []
            now = utcnow()
            candidates = tx.fetchall("SELECT * FROM tasks WHERE state = 'queued' ORDER BY priority DESC, created_at")
            for row in candidates:
                if len(runs) >= limit:
                    break
                task = Task.from_row(row)
                if roles and task.role not in roles:
                    continue
                if task.not_before and parse_iso(task.not_before) > now:
                    continue
                if not self._dependencies_done(tx, task):
                    continue
                charter = self.charters[task.role]
                running = int(tx.scalar("SELECT COUNT(*) FROM agent_runs WHERE role = ? AND state = 'running'", (task.role,)))
                if running >= charter.max_concurrency:
                    continue
                allowance, permissions = charter.credit_allowance, list(charter.permissions)
                if task.parent_run_id:
                    parent = self._run(tx, task.parent_run_id)
                    if parent.state != "running":
                        self._set(tx, task.id, {"state": "cancelled", "error": "parent run ended"})
                        continue
                    allowance = min(allowance, self._parent_remaining(tx, parent))
                    permissions = [p for p in permissions if p in parent.permissions]
                    if allowance <= 0:
                        continue
                if not self._within_credit_budget(tx, allowance):
                    self.audit.record(tx, worker, "credit_budget_exhausted", "tasks", task.id,
                                      after={"allowance": allowance, "budget": self.mandate.krw("budgets.ai_credit_budget")})
                    continue
                run = {"id": new_id("run"), "task_id": task.id, "role": task.role, "parent_run_id": task.parent_run_id,
                       "depth": task.depth, "permissions": canonical_json(permissions), "credits_allowed": allowance,
                       "credits_used": 0, "state": "running", "worker": worker, "started_at": iso(now),
                       "deadline_at": iso(now + timedelta(minutes=charter.deadline_minutes)), "ended_at": None, "outcome": None}
                tx.insert("agent_runs", run)
                self._set(tx, task.id, {"state": "running", "run_id": run["id"], "attempts": task.attempts + 1})
                self.audit.record(tx, worker, "run_started", "agent_runs", run["id"], after={"task": task.id, "role": task.role})
                r = Run.from_row(run)
                r.task = Task.from_row(tx.fetchone("SELECT * FROM tasks WHERE id = ?", (task.id,)))
                runs.append(r)
        return runs

    def _dependencies_done(self, tx, task: Task) -> bool:
        for dep in task.depends_on:
            row = tx.fetchone("SELECT state FROM tasks WHERE id = ?", (dep,))
            if not row or row["state"] != "done":
                return False
        return True

    def _parent_remaining(self, tx, parent: Run) -> int:
        children = int(tx.scalar("SELECT COALESCE(SUM(credits_allowed), 0) FROM agent_runs WHERE parent_run_id = ? AND state = 'running'", (parent.id,)))
        spent_children = int(tx.scalar("SELECT COALESCE(SUM(credits_used), 0) FROM agent_runs WHERE parent_run_id = ? AND state <> 'running'", (parent.id,)))
        return parent.credits_allowed - parent.credits_used - children - spent_children

    def _within_credit_budget(self, tx, allowance: int) -> bool:
        used = int(tx.scalar("SELECT COALESCE(SUM(credits_used), 0) FROM agent_runs WHERE state <> 'running'"))
        reserved = int(tx.scalar("SELECT COALESCE(SUM(credits_allowed), 0) FROM agent_runs WHERE state = 'running'"))
        return used + reserved + allowance <= self.mandate.krw("budgets.ai_credit_budget")

    # -- finish ----------------------------------------------------------------------------------------

    def complete(self, run_id: str, result: dict | None, credits_used: int, actor: str | None = None) -> Task:
        with self.db.transaction() as tx:
            run = self._run(tx, run_id)
            if run.state != "running":
                return self._task(tx, run.task_id)
            if credits_used > run.credits_allowed:
                return self._finish(tx, run, "failed", f"credit allowance exceeded: {credits_used} > {run.credits_allowed}", credits_used, actor)
            tx.update("agent_runs", "id", run.id, {"state": "done", "credits_used": credits_used, "ended_at": now_iso(), "outcome": "done"})
            self._set(tx, run.task_id, {"state": "done", "result": canonical_json(result or {}), "error": None})
            self.audit.record(tx, actor or run.worker or "worker", "run_done", "agent_runs", run.id, after={"credits_used": credits_used})
            return self._task(tx, run.task_id)

    def fail(self, run_id: str, error: str, credits_used: int = 0, actor: str | None = None) -> Task:
        with self.db.transaction() as tx:
            run = self._run(tx, run_id)
            if run.state != "running":
                return self._task(tx, run.task_id)
            return self._finish(tx, run, "failed", error, credits_used, actor)

    def _finish(self, tx, run: Run, state: str, error: str, credits_used: int, actor) -> Task:
        tx.update("agent_runs", "id", run.id, {"state": state, "credits_used": credits_used, "ended_at": now_iso(), "outcome": error})
        task = self._task(tx, run.task_id)
        charter = self.charters[task.role]
        if task.attempts <= charter.max_retries:
            delay = BACKOFF_SECONDS[min(task.attempts - 1, len(BACKOFF_SECONDS) - 1)]
            self._set(tx, task.id, {"state": "queued", "error": error, "run_id": None, "not_before": iso(utcnow() + timedelta(seconds=delay))})
            outcome = "retry"
        else:
            self._set(tx, task.id, {"state": "escalated", "error": error})
            outcome = "escalated"
        self.audit.record(tx, actor or run.worker or "worker", f"run_{state}", "agent_runs", run.id,
                          after={"error": error, "task_outcome": outcome, "attempts": task.attempts})
        return self._task(tx, task.id)

    def expire(self, now=None) -> list[str]:
        """Runs past their deadline fail (and retry or escalate like any failure)."""
        now = now or utcnow()
        expired = []
        with self.db.transaction() as tx:
            rows = tx.fetchall("SELECT * FROM agent_runs WHERE state = 'running' AND deadline_at <= ?", (iso(now),))
        for r in rows:
            self.fail(r["id"], "deadline exceeded", 0, "orchestrator")
            expired.append(r["id"])
        return expired

    # -- permissions -------------------------------------------------------------------------------------

    def check_permission(self, tx: Tx, run_id: str, permission: str) -> None:
        run = self._run(tx, run_id)
        if run.state != "running":
            raise OrchestrationError(f"run {run_id} is {run.state}")
        if permission not in run.permissions:
            raise OrchestrationError(f"run {run_id} ({run.role}) lacks permission {permission!r}")

    # -- reading -----------------------------------------------------------------------------------------

    def _run(self, tx, run_id: str) -> Run:
        row = tx.fetchone("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        if not row:
            raise OrchestrationError(f"unknown run {run_id}")
        return Run.from_row(row)

    def _task(self, tx, task_id: str) -> Task:
        return Task.from_row(tx.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,)))

    def _set(self, tx, task_id: str, changes: dict) -> None:
        tx.update("tasks", "id", task_id, {**changes, "updated_at": now_iso()})

    def task(self, tx: Tx, task_id: str) -> Task:
        return self._task(tx, task_id)

    def run(self, tx: Tx, run_id: str) -> Run:
        return self._run(tx, run_id)

    def summary(self, tx: Tx) -> dict:
        by_state = {r["state"]: int(r["n"]) for r in tx.fetchall("SELECT state, COUNT(*) AS n FROM tasks GROUP BY state")}
        by_role = {r["role"]: {"runs": int(r["n"]), "credits_used": int(r["c"])}
                   for r in tx.fetchall("SELECT role, COUNT(*) AS n, COALESCE(SUM(credits_used), 0) AS c FROM agent_runs GROUP BY role")}
        used = int(tx.scalar("SELECT COALESCE(SUM(credits_used), 0) FROM agent_runs"))
        running = int(tx.scalar("SELECT COUNT(*) FROM agent_runs WHERE state = 'running'"))
        return {"tasks": by_state, "roles": by_role, "credits_used": used, "credits_budget": self.mandate.krw("budgets.ai_credit_budget"),
                "runs_active": running, "escalated": by_state.get("escalated", 0)}
