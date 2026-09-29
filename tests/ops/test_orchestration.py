"""Charters, orchestrator limits, durable workflows and the evidence store."""

from datetime import timedelta

import pytest

from arbitrage.ops.audit import AuditTrail
from arbitrage.ops.charters import REQUIRED_ROLES, load_charters, parse_charters, store_charters
from arbitrage.ops.common import utcnow
from arbitrage.ops.core import build
from arbitrage.ops.errors import OpsError, OrchestrationError
from arbitrage.ops.evidence import EvidenceStore
from arbitrage.ops.jobs import install_schedules, register_standard
from arbitrage.ops.orchestrator import Orchestrator
from arbitrage.ops.workflows import WorkflowEngine, done, fail, proceed, wait

from .conftest import mandate_with


# -- charters -------------------------------------------------------------------------------------------

def test_bundled_charters_cover_every_role_with_every_field():
    charters = load_charters()
    assert set(charters) == set(REQUIRED_ROLES) and len(charters) == 13
    for c in charters.values():
        assert c.task and c.inputs and c.outputs and c.tools and c.permissions and c.success_metric and c.termination_condition
        assert c.deadline_minutes > 0 and c.credit_allowance > 0 and c.max_concurrency > 0
        assert not any(p.startswith("execute:") for p in c.permissions)
    assert not any(p.startswith("propose:") for p in charters["quality_evaluation"].permissions)
    assert "propose:purchase" in charters["procurement"].permissions


def test_charter_validation():
    good = {"defaults": {"max_concurrency": 1, "max_retries": 1, "max_delegation_depth": 1, "deadline_minutes": 10, "credit_allowance": 5},
            "charters": [{"role": r, "task": "t", "inputs": ["i"], "outputs": ["o"], "tools": ["x"], "permissions": ["read:ledger"],
                          "success_metric": "s", "termination_condition": "e"} for r in REQUIRED_ROLES]}
    assert len(parse_charters(good)) == 13
    bad = dict(good, charters=good["charters"][:-1])
    with pytest.raises(OrchestrationError, match="missing for: quality_evaluation"):
        parse_charters(bad)
    evil = dict(good, charters=[dict(c, permissions=["execute:payment"]) if c["role"] == "procurement" else c for c in good["charters"]])
    with pytest.raises(OrchestrationError, match="never hold execute"):
        parse_charters(evil)
    judge = dict(good, charters=[dict(c, permissions=["propose:code_change"]) if c["role"] == "quality_evaluation" else c for c in good["charters"]])
    with pytest.raises(OrchestrationError, match="evaluator may not propose"):
        parse_charters(judge)


# -- orchestrator ----------------------------------------------------------------------------------------

def charters_of(o, role):
    return o.charters[role].permissions


@pytest.fixture
def orch(db, simulated_mandate):
    core = build(db, simulated_mandate)
    charters = load_charters()
    with db.transaction() as tx:
        store_charters(tx, charters)
    return core, Orchestrator(db, charters, simulated_mandate, core.audit, core.pauses)


def test_tasks_dedupe_depend_and_run_within_concurrency(orch):
    core, o = orch
    t1 = o.submit("market_research", "demand for tongs", {"keyword": "집게"})
    assert o.submit("market_research", "again", {"keyword": "집게"}).id == t1.id  # same work once
    t2 = o.submit("unit_economics", "price tongs", {"sku": "tongs"}, depends_on=(t1.id,))
    with pytest.raises(OrchestrationError, match="no charter"):
        o.submit("ceo", "x", {})
    runs = o.claim("w1", limit=5)
    assert [r.task_id for r in runs] == [t1.id]  # t2 waits for t1
    assert runs[0].credits_allowed == 60 and runs[0].deadline_at > runs[0].started_at
    o.submit("market_research", "second", {"keyword": "거치대"})
    o.submit("market_research", "third", {"keyword": "케이블"})
    more = o.claim("w2", limit=5)
    assert len(more) == 1  # max_concurrency 2 for market_research
    o.complete(runs[0].id, {"memo": "ok"}, credits_used=12)
    nxt = o.claim("w3", limit=5)
    assert {r.role for r in nxt} == {"market_research", "unit_economics"}
    with core.db.transaction() as tx:
        s = o.summary(tx)
        assert s["credits_used"] == 12 and s["runs_active"] == 3 and s["tasks"]["done"] == 1


def test_failures_retry_with_backoff_then_escalate(orch):
    core, o = orch
    t = o.submit("procurement", "buy", {"sku": "tongs"})
    for attempt in (1, 2):
        (run,) = o.claim("w", limit=1)
        task = o.fail(run.id, "supplier timeout", credits_used=3)
        assert task.state == "queued" and task.not_before is not None and task.attempts == attempt
        assert o.claim("w", limit=1) == []  # backoff holds it
        with core.db.transaction() as tx:
            tx.update("tasks", "id", t.id, {"not_before": None})
    (run,) = o.claim("w", limit=1)
    task = o.fail(run.id, "supplier timeout", credits_used=3)
    assert task.state == "escalated" and task.attempts == 3
    assert o.claim("w", limit=1) == []


def test_delegation_inherits_narrower_permissions_and_credits(orch):
    core, o = orch
    parent_task = o.submit("engineering_improvement", "speed up matching", {"issue": 1})
    (parent,) = o.claim("w", limit=1)
    assert parent.credits_allowed == 80
    buyer_task = o.submit("procurement", "buy stuff", {"sku": "x"}, parent_run_id=parent.id)
    (buyer,) = o.claim("w", roles=("procurement",), limit=1)
    assert "propose:purchase" not in buyer.permissions  # narrowed to what the parent holds: never wider
    assert set(buyer.permissions) == set(charters_of(o, "procurement")) & set(parent.permissions)
    o.complete(buyer.id, {}, 1)
    with pytest.raises(OrchestrationError, match="no permission its parent"):
        o.submit("customer_support", "reply", {"case": 1}, parent_run_id=parent.id)  # nothing in common
    child_task = o.submit("performance_analytics", "measure", {"metric": "latency"}, parent_run_id=parent.id)
    assert child_task.depth == 1
    (child,) = o.claim("w", roles=("performance_analytics",), limit=1)
    assert child.credits_allowed == 30 and set(child.permissions) <= set(parent.permissions)
    grandchild = o.submit("performance_analytics", "measure more", {"metric": "throughput"}, parent_run_id=child.id)
    assert grandchild.depth == 2
    (gc_run,) = o.claim("w", roles=("performance_analytics",), limit=1)
    with pytest.raises(OrchestrationError, match="delegation depth"):
        o.submit("performance_analytics", "deeper", {"metric": "x"}, parent_run_id=gc_run.id)
    with core.db.transaction() as tx:
        o.check_permission(tx, child.id, "read:ledger")
        with pytest.raises(OrchestrationError, match="lacks permission"):
            o.check_permission(tx, child.id, "propose:purchase")
    # credits come out of the parent's allowance: 80 − buyer's 1 used − child's 30 held = 49, so a third child gets its
    # full 30; after it spends them only 19 are left for a fourth; a fifth gets nothing (the grandchild drew on the child)
    o.complete(gc_run.id, {}, credits_used=25)
    o.submit("performance_analytics", "third", {"metric": "y"}, parent_run_id=parent.id)
    (r3,) = o.claim("w", roles=("performance_analytics",), limit=1)
    assert r3.credits_allowed == 30
    o.complete(r3.id, {}, credits_used=30)
    o.submit("performance_analytics", "fourth", {"metric": "z"}, parent_run_id=parent.id)
    (r4,) = o.claim("w", roles=("performance_analytics",), limit=1)
    assert r4.credits_allowed == 19
    o.complete(r4.id, {}, credits_used=19)
    o.submit("performance_analytics", "fifth", {"metric": "w"}, parent_run_id=parent.id)
    assert o.claim("w", roles=("performance_analytics",), limit=1) == []  # the parent has nothing left to delegate


def test_credit_budget_and_pause_stop_new_runs(db):
    m = mandate_with(**{"budgets.ai_credit_budget": 70})
    core = build(db, m)
    charters = load_charters()
    o = Orchestrator(db, charters, m, core.audit, core.pauses)
    o.submit("market_research", "a", {"k": 1})
    o.submit("market_research", "b", {"k": 2})
    runs = o.claim("w", limit=5)
    assert len(runs) == 1  # 60 + 60 > 70
    o.complete(runs[0].id, {}, credits_used=61)  # over its allowance: recorded as a failure, not silently accepted
    with core.db.transaction() as tx:
        assert tx.fetchone("SELECT state FROM agent_runs WHERE id = ?", (runs[0].id,))["state"] == "failed"
    assert o.claim("w", limit=5) == []  # 61 used + 60 allowance > 70
    core.pause("all", "stop", "owner")
    assert o.claim("w", limit=5) == []


def test_expired_runs_fail(orch):
    core, o = orch
    o.submit("customer_support", "inbox", {"day": 1})
    (run,) = o.claim("w", limit=1)
    assert o.expire(utcnow()) == []
    expired = o.expire(utcnow() + timedelta(minutes=121))
    assert expired == [run.id]
    with core.db.transaction() as tx:
        assert o.task(tx, run.task_id).state == "queued"


# -- workflows -------------------------------------------------------------------------------------------

def test_workflow_steps_checkpoint_retry_and_recover_lost_leases(db):
    engine = WorkflowEngine(db, AuditTrail(db))
    seen = []

    def handler(wf):
        seen.append((wf.step, wf.attempts))
        if wf.step == "start":
            return proceed("charge", {"charged": 1})
        if wf.step == "charge":
            if wf.attempts < 2:
                raise RuntimeError("supplier timeout")
            return wait(0, {"waited": True}, step="finish")
        return done({"finished": True})

    engine.register("purchase_flow", handler)
    wid = engine.start("purchase_flow", {"sku": "tongs"}, dedupe_key="po:1")
    assert engine.start("purchase_flow", {"sku": "tongs"}, dedupe_key="po:1") == wid
    assert engine.run_due("w1") == 1
    with db.transaction() as tx:
        wf = engine.get(tx, wid)
        assert wf.step == "charge" and wf.payload == {"sku": "tongs", "charged": 1} and wf.state == "pending"
    engine.run_due("w1")  # attempt 1 fails -> retry scheduled with backoff
    with db.transaction() as tx:
        wf = engine.get(tx, wid)
        assert wf.state == "pending" and wf.attempts == 1 and "supplier timeout" in wf.last_error
        tx.update("workflows", "id", wid, {"next_run_at": "2000-01-01T00:00:00+00:00"})  # skip the backoff
    engine.run_due("w1")  # attempt 2 fails
    with db.transaction() as tx:
        tx.update("workflows", "id", wid, {"next_run_at": "2000-01-01T00:00:00+00:00"})
    engine.run_due("w1")  # attempt 3 waits
    with db.transaction() as tx:
        wf = engine.get(tx, wid)
        assert wf.state == "waiting" and wf.payload["waited"] is True
    # a worker that claimed the step and died: its lease expires and another worker finishes
    (claimed,) = engine.claim_due("w2", lease_seconds=60)
    assert engine.claim_due("w3") == []  # leased
    with db.transaction() as tx:
        tx.update("workflows", "id", wid, {"locked_until": "2000-01-01T00:00:00+00:00"})
    (again,) = engine.claim_due("w3")
    assert again.id == wid
    with pytest.raises(OpsError, match="lease lost"):
        engine.run(claimed, "w2")
    final = engine.run(again, "w3")
    assert final.state == "done" and final.payload["finished"] is True
    with db.transaction() as tx:
        kinds = [e["event"] for e in engine.events(tx, wid)]
    assert kinds == ["started", "continue", "retry", "retry", "wait", "done"]
    assert seen[0] == ("start", 0) and ("charge", 2) in seen


def test_workflow_gives_up_after_max_attempts_and_unretryable_failures(db):
    engine = WorkflowEngine(db, AuditTrail(db))
    engine.register("boom", lambda wf: fail("no", retry=False))
    engine.register("flaky", lambda wf: fail("still no"))
    a = engine.start("boom", max_attempts=5)
    b = engine.start("flaky", max_attempts=2)
    engine.run_due("w")
    with db.transaction() as tx:
        assert engine.get(tx, a).state == "failed"
        assert engine.get(tx, b).state == "pending" and engine.get(tx, b).attempts == 1
        tx.update("workflows", "id", b, {"next_run_at": "2000-01-01T00:00:00+00:00"})
    engine.run_due("w")
    with db.transaction() as tx:
        assert engine.get(tx, b).state == "failed"
    with pytest.raises(OpsError, match="no handler"):
        engine.start("unknown_type")


def test_schedules_start_once_per_slot(db):
    engine = WorkflowEngine(db)
    engine.register("guardrails", lambda wf: done())
    engine.add_schedule("guardrails:live", "guardrails", 900, {"mode": "live"}, first_run_at=utcnow() - timedelta(hours=1))
    now = utcnow()
    first = engine.tick(now)
    assert len(first) == 1
    assert engine.tick(now) == []  # same slot from a second worker: nothing new
    with db.transaction() as tx:
        s = tx.fetchone("SELECT * FROM schedules WHERE name = 'guardrails:live'")
        assert s["next_run_at"] > now.isoformat(timespec="seconds")
    assert engine.tick(now + timedelta(minutes=16)) != []


def test_standard_jobs_run_against_the_core(db, simulated_mandate):
    core = build(db, simulated_mandate)
    engine = WorkflowEngine(db, core.audit)
    register_standard(engine, core)
    install_schedules(engine, "simulated")
    started = engine.tick(utcnow() + timedelta(seconds=1))
    assert len(started) == 5
    for _ in range(6):  # the daily cycle spawns children over several steps
        engine.run_due("worker", limit=20)
    with db.transaction() as tx:
        workflows = engine.list(tx)
        assert len(workflows) == 8  # 5 scheduled + 3 spawned by the daily cycle
        assert all(w.state == "done" for w in workflows), [(w.type, w.state, w.last_error) for w in workflows]
        # guardrails on an empty ledger: cash is below the reserve, so purchasing is paused automatically
        assert any(p["condition"] == "simulated:cash_below_reserve" for p in core.pauses.active(tx))
    assert core.audit.verify()[0]


# -- evidence ---------------------------------------------------------------------------------------------

def test_evidence_is_content_addressed_and_checked_on_read(db, tmp_path):
    store = EvidenceStore(db, tmp_path / "evidence")
    with db.transaction() as tx:
        row = store.put(tx, "receipt", b"PDF...", "receipt 1.pdf", "action", "txn_1", "simulated")
        assert row["size"] == 6 and row["uri"].startswith("file://") and "/simulated/" in row["uri"]
        assert store.read(row) == b"PDF..."
        assert store.for_record(tx, "action", "txn_1")[0]["id"] == row["id"]
        with pytest.raises(OpsError, match="empty"):
            store.put(tx, "receipt", b"", "x", "action", "txn_1", "simulated")
    from pathlib import Path
    Path(row["uri"].removeprefix("file://")).write_bytes(b"tampered")
    with pytest.raises(OpsError, match="does not match"):
        store.read(row)
