"""The dashboard document and the arbitrage-ops command: numbers come from the ledger, modes stay apart, live counts alone."""

import json
from pathlib import Path

import pytest

from arbitrage.ops import cli
from arbitrage.ops.charters import load_charters
from arbitrage.ops.common import LIVE, SIMULATED
from arbitrage.ops.core import build
from arbitrage.ops.dashboard import dashboard, readiness
from arbitrage.ops.orchestrator import Orchestrator
from arbitrage.ops.workflows import WorkflowEngine

from .test_gateway_flows import adapters, run_happy_path


@pytest.fixture
def core(db, simulated_mandate):
    c = build(db, simulated_mandate, adapters())
    with c.db.transaction() as tx:
        c.books.contribute_capital(tx, SIMULATED, 1_000_000, "simulated:bank", "cap:1")
    return c


def test_dashboard_reports_simulated_results_without_counting_them_toward_the_goal(core):
    run_happy_path(core)
    orch = Orchestrator(core.db, load_charters(), core.mandate, core.audit, core.pauses)
    engine = WorkflowEngine(core.db, core.audit)
    sim = dashboard(core, SIMULATED, orch, engine)
    assert "SIMULATED" in sim["label"] and sim["counts_toward_goal"] is False
    assert sim["sales"]["orders_placed"] == 1 and sim["sales"]["gross_sales"] == 20_000
    assert sim["profit"]["realized"] > 0
    assert sim["goal"]["reconciled_net_profit_krw"] == 0 and sim["goal"]["progress"] == 0
    assert sim["trial_balance_ok"] is True
    assert sim["inventory"]["age_by_sku"][0]["sku"] == "tongs" and sim["inventory"]["age_by_sku"][0]["units"] == 9
    assert sim["limits"]["max_daily_spend_krw"] == 400_000 and sim["limits"]["spent_today"] >= 0
    live = dashboard(core, LIVE, orch, engine)
    assert live["counts_toward_goal"] is True and live["sales"]["orders_placed"] == 0
    assert live["goal"]["reconciled_net_profit_krw"] == 0 and live["goal"]["target_realized_profit_krw"] == 1_000_000
    json.dumps(sim, default=str)  # serialisable for the API


def test_readiness_says_live_actions_are_impossible_with_a_pending_mandate(db, pending):
    core = build(db, pending)
    r = readiness(core)
    assert r["live_actions_possible"] is False
    assert r["mandate"]["complete"] is False and len(r["mandate"]["pending_fields"]) > 10
    assert r["integrations_production_ready"] == []


def test_cli_migrate_status_pause_and_demo_on_sqlite(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = f"sqlite:///{tmp_path / 'ops.db'}"
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("OPS_MANDATE", str(root / "mandate.simulated.toml"))
    assert cli.main(["--database", db, "--mode", "simulated", "migrate"]) == 0
    assert "schema ready" in capsys.readouterr().out
    assert cli.main(["--database", db, "--mode", "simulated", "demo"]) == 0
    out = capsys.readouterr().out
    assert "SIMULATED DEMO" in out and "nothing real happens" in out and "return window closed" in out
    assert cli.main(["--database", db, "--mode", "simulated", "status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["mode"] == "simulated" and doc["sales"]["orders_placed"] == 1 and doc["counts_toward_goal"] is False
    assert cli.main(["--database", db, "--mode", "simulated", "pause", "--reason", "owner test"]) == 0
    pid = capsys.readouterr().out.split()[-1]
    assert cli.main(["--database", db, "--mode", "simulated", "status"]) == 0
    assert "purchasing (owner" in capsys.readouterr().out
    assert cli.main(["--database", db, "--mode", "simulated", "resume", pid]) == 0
    assert cli.main(["--database", db, "--mode", "simulated", "worker", "--once"]) == 0
    assert "worker worker-1" in capsys.readouterr().out
    assert cli.main(["--database", db, "--mode", "simulated", "audit"]) == 0
    assert "intact" in capsys.readouterr().out
    # the live mandate in the repo is pending: `mandate` exits 1 and readiness says no live action is possible
    monkeypatch.setenv("OPS_MANDATE", str(root / "mandate.toml"))
    assert cli.main(["--database", db, "mandate"]) == 1
    assert json.loads(capsys.readouterr().out)["complete"] is False
    assert cli.main(["--database", db, "readiness"]) == 0
    assert json.loads(capsys.readouterr().out)["live_actions_possible"] is False
    assert cli.main(["--database", db, "demo"]) == 2  # demo refuses to run against live
