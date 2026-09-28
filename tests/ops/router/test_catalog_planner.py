"""Layer 5 keeps evidence on every price and learns quality; Layer 6 refuses non-compliant routes before it prices
anything, then picks by objective; Layer 8's decomposition only when it is cheaper and within the cap."""

import pytest

from arbitrage.ops.errors import OpsError
from arbitrage.ops.router.catalog import ModelCatalog, cost_krw
from arbitrage.ops.router.intent import RouteRequest, compile_intent
from arbitrage.ops.router.planner import Constraints, compliance_problems, plan

from .conftest import CATALOG, SIM


def entry(**kw):
    e = {"id": "simulated:provider-a:tiny:us", "provider": "simulated:provider-a", "model": "tiny", "region": "us", "task_types": ["chat"],
         "context_window": 8000, "input_micros_per_mtok": 100000, "output_micros_per_mtok": 400000, "currency": "USD", "latency_ms": 300,
         "quality": {"chat": 0.7}, "terms_permit": True,
         "evidence": {"source": "placeholder", "url": "https://example.invalid/x", "date": "2026-09-28", "verified": False}}
    e.update(kw)
    return e


def constraints(**kw):
    d = dict(task_type="extraction", quality_min=0.8, cost_cap_krw=5_000, optimization="economy", fx_rate=1365.0, fx_origin="test",
             max_output_tokens=512, providers_allowed=("simulated:provider-a", "simulated:provider-b"), regions_allowed=("us", "kr"),
             task_types_allowed=("extraction", "chat", "summarization", "translation"), quality_floor=0.6)
    d.update(kw)
    return Constraints(**d)


def test_catalog_validation_and_evidence_rules(rcore):
    cat = ModelCatalog(rcore.db, rcore.audit)
    with rcore.db.transaction() as tx:
        with pytest.raises(OpsError, match="evidence needs"):
            cat.load(tx, [entry(evidence={"source": "x"})], SIM)
        with pytest.raises(OpsError, match="never verified"):
            cat.load(tx, [entry(evidence={"source": "x", "url": "u", "date": "2026-09-28", "verified": True})], SIM)
        with pytest.raises(OpsError, match="provider:model:region"):
            cat.load(tx, [entry(id="wrong")], SIM)
        with pytest.raises(OpsError, match="simulated"):
            cat.load(tx, [entry(id="anthropic:x:us", provider="anthropic", model="x")], SIM)
        with pytest.raises(OpsError, match="task_types"):
            cat.load(tx, [entry(task_types=["mining"])], SIM)
        with pytest.raises(OpsError, match="quality"):
            cat.load(tx, [entry(quality={"chat": 1.5})], SIM)
        assert cat.load(tx, [entry()], SIM) == ["simulated:provider-a:tiny:us"]
        row = cat.get(tx, "simulated:provider-a:tiny:us")
        assert row["price_verified"] is False and row["quality"] == {"chat": 0.7}
        # a live catalog cannot carry a simulated provider, and a live price can be verified
        with pytest.raises(OpsError, match="live catalog"):
            cat.load(tx, [entry()], "live")


def test_quality_is_learned_from_verdicts_and_survives_a_reload(rcore):
    cat = ModelCatalog(rcore.db, rcore.audit)
    with rcore.db.transaction() as tx:
        cat.load(tx, [entry()], SIM)
        first = cat.record_quality(tx, "simulated:provider-a:tiny:us", "chat", 0.5)
        assert first == 0.5          # first verdict replaces the unlearned seed
        second = cat.record_quality(tx, "simulated:provider-a:tiny:us", "chat", 0.9)
        assert 0.5 < second < 0.9    # then a moving average
        cat.load(tx, [entry(quality={"chat": 0.99})], SIM)   # a refresh keeps what was learned
        assert cat.get(tx, "simulated:provider-a:tiny:us")["quality"]["chat"] == second
        with pytest.raises(OpsError, match="between 0 and 1"):
            cat.record_quality(tx, "simulated:provider-a:tiny:us", "chat", 2)
        stale = cat.stale(tx, SIM, 30)
        assert stale == []
        from datetime import date
        assert cat.stale(tx, SIM, 30, today=date(2027, 1, 1))[0]["id"] == "simulated:provider-a:tiny:us"


def test_cost_rounds_up_and_scales_with_tokens():
    row = entry()
    assert cost_krw(0, 0, row, 1365.0) == 0
    one = cost_krw(1, 0, row, 1365.0)
    assert one == 1                          # 100000 micros/MTok * 1 token * 1365 / 1e12 -> rounds up to 1 KRW
    assert cost_krw(1_000_000, 0, row, 1365.0) == 137   # 0.10 USD * 1365 = 136.5 -> 137
    assert cost_krw(1_000_000, 1_000_000, row, 1365.0) == 137 + 546


def test_compliance_gate_names_every_reason(router):
    with router.db.transaction() as tx:
        rows = {r["id"]: r for r in router.catalog.list(tx, SIM)}
    c = constraints()
    assert "provider terms do not permit routing customer work through this model" in compliance_problems(rows["simulated:provider-b:grey:us"], "extraction", 100, c)
    assert any("region eu" in p for p in compliance_problems(rows["simulated:provider-b:medium:eu"], "extraction", 100, c))
    assert any("not in the mandate's providers" in p for p in compliance_problems(rows["simulated:provider-a:small:us"], "extraction", 100,
                                                                                      constraints(providers_allowed=("simulated:provider-b",))))
    assert any("not permitted by the mandate" in p for p in compliance_problems(rows["simulated:provider-a:small:us"], "extraction", 100,
                                                                                    constraints(task_types_allowed=("chat",))))
    assert any("does not serve reasoning" in p for p in compliance_problems(rows["simulated:provider-a:small:us"], "reasoning", 100, c))
    assert any("context window" in p for p in compliance_problems(rows["simulated:provider-b:medium:kr"], "extraction", 200_000, c))
    assert compliance_problems(rows["simulated:provider-a:small:us"], "extraction", 100, c) == []


def test_objectives_pick_and_ladder_climbs_by_quality(router):
    intent = compile_intent(RouteRequest("k", "c", "Extract the invoice fields as JSON", cost_cap_krw=5_000))
    with router.db.transaction() as tx:
        rows = router.catalog.list(tx, SIM)
    economy = plan(intent, 1_000, rows, constraints(quality_min=0.7))
    assert economy.chosen.catalog_id == "simulated:provider-a:small:us"
    assert [r.catalog_id for r in economy.ladder] == ["simulated:provider-a:small:us", "simulated:provider-b:medium:kr", "simulated:provider-a:large:us"]
    assert set(economy.rejected) == {"simulated:provider-b:grey:us", "simulated:provider-b:medium:eu"}
    assert any("unverified" in n for n in economy.notes)
    stricter = plan(intent, 1_000, rows, constraints(quality_min=0.8))
    assert stricter.chosen.catalog_id == "simulated:provider-b:medium:kr"
    assert "quality 0.72 below threshold 0.80" in stricter.rejected["simulated:provider-a:small:us"]
    maximum = plan(intent, 1_000, rows, constraints(quality_min=0.7, optimization="maximum"))
    assert maximum.chosen.catalog_id == "simulated:provider-a:large:us" and len(maximum.ladder) == 1
    balanced = plan(intent, 1_000, rows, constraints(quality_min=0.7, optimization="balanced"))
    assert balanced.chosen.catalog_id in ("simulated:provider-a:small:us", "simulated:provider-b:medium:kr")
    capped = plan(intent, 1_000, rows, constraints(quality_min=0.7, cost_cap_krw=1))
    assert not capped.feasible and all(any("cost cap" in p for p in v) for k, v in capped.rejected.items() if k not in ("simulated:provider-b:grey:us", "simulated:provider-b:medium:eu"))
    platform = plan(intent, 1_000, rows, constraints(quality_min=0.7, platform_request_cap_krw=1))
    assert not platform.feasible and any("mandate's per-request cap" in p for p in platform.rejected["simulated:provider-a:small:us"])
    latency = plan(intent, 1_000, rows, constraints(quality_min=0.7, latency_max_ms=500))
    assert latency.chosen.catalog_id == "simulated:provider-a:small:us" and len(latency.ladder) == 1
    floor = plan(intent, 1_000, rows, constraints(quality_min=0.1, quality_floor=0.9))
    assert floor.chosen.catalog_id == "simulated:provider-a:large:us"   # the mandate floor applies whatever the customer asks
    with pytest.raises(OpsError, match="positive cost cap"):
        plan(intent, 1_000, rows, constraints(cost_cap_krw=0))


def test_decomposition_only_when_a_cheaper_route_exists_and_it_pays(router):
    ctx = "\n\n".join(("Invoice %d total %d won. " % (i, i)) * 40 for i in range(400))
    intent = compile_intent(RouteRequest("k", "c", "Extract every invoice total as JSON", ctx, cost_cap_krw=50_000))
    assert intent.decomposable and intent.context_tokens > 8_000
    with router.db.transaction() as tx:
        rows = router.catalog.list(tx, SIM)
    strong = plan(intent, intent.input_tokens, rows, constraints(quality_min=0.9, cost_cap_krw=50_000, max_output_tokens=2048))
    assert strong.chosen.catalog_id == "simulated:provider-a:large:us"
    assert strong.decomposition is not None
    assert strong.decomposition.preprocess.catalog_id == "simulated:provider-a:small:us"
    assert strong.decomposition.expected_cost_krw < strong.chosen.expected_cost_krw
    assert strong.decomposition.chunks >= 2
    cheap = plan(intent, intent.input_tokens, rows, constraints(quality_min=0.7, cost_cap_krw=50_000, max_output_tokens=2048))
    assert cheap.chosen.catalog_id == "simulated:provider-a:small:us" and cheap.decomposition is None   # nothing cheaper to preprocess on
