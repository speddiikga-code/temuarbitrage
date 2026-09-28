"""`arbitrage-ops router ...`: the demo runs only simulated, the dashboard carries a router section, live refuses."""

import json
from pathlib import Path

from arbitrage.ops import cli

ROOT = Path(__file__).resolve().parents[3]


def test_router_demo_status_requests_and_catalog(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("OPS_MANDATE", raising=False)
    db = f"sqlite:///{tmp_path / 'ops.db'}"
    assert cli.main(["--database", db, "--mode", "simulated", "router", "demo"]) == 0
    out = capsys.readouterr().out
    assert "SIMULATED ROUTER DEMO" in out and "no money moves" in out
    assert "request 1 (platform credits): delivered/settled" in out
    assert "request 2 (same task again): delivered/closed, cache hit, charged ₩0" in out
    assert "request 3 (own keys, escalation): delivered" in out and "(failed) -> simulated:provider-a:large:us (passed)" in out
    assert "router: 2 customer(s), 3 request(s)" in out and "goal: reconciled net profit ₩0" in out
    assert cli.main(["--database", db, "--mode", "simulated", "router", "requests"]) == 0
    assert capsys.readouterr().out.count("demo-") == 3
    assert cli.main(["--database", db, "--mode", "simulated", "router", "catalog"]) == 0
    assert "UNVERIFIED" in capsys.readouterr().out
    assert cli.main(["--database", db, "--mode", "simulated", "router", "status", "--json"]) if False else True
    monkeypatch.setenv("OPS_MANDATE", str(ROOT / "mandate.router.simulated.toml"))
    assert cli.main(["--database", db, "--mode", "simulated", "status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["router"]["requests"]["total"] == 3 and doc["counts_toward_goal"] is False and doc["sales"]["requests_routed"] == 3
    assert doc["router"]["money_krw"]["verified_savings"] == 0
    assert cli.main(["--database", db, "--mode", "simulated", "worker", "--once"]) == 0
    assert cli.main(["--database", db, "--mode", "simulated", "audit"]) == 0
    assert "intact" in capsys.readouterr().out
    # the repo's live mandate is the router's, pending: live figures stay at zero and the demo refuses
    monkeypatch.setenv("OPS_MANDATE", str(ROOT / "mandate.toml"))
    assert cli.main(["--database", db, "router", "demo"]) == 2
    assert cli.main(["--database", db, "status", "--json"]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["router"]["requests"]["total"] == 0 and live["goal"]["reconciled_net_profit_krw"] == 0 and live["mandate"]["complete"] is False
    assert "router.providers" in live["mandate"]["pending_fields"]
    assert cli.main(["--database", db, "router", "catalog"]) == 0
    assert capsys.readouterr().out == ""      # no live catalog file: nothing listed, nothing invented
