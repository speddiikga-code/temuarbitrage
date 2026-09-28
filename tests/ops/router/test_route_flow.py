"""Owner acceptance checks on the router: nothing routes without settled money or a permitted key, every provider
call goes through policy, reservation and confirmation, a failed judge escalates rather than delivers, an unknown
result reconciles rather than retries, profit is realized only after settlement and the dispute window, and
simulated results never count toward the goal."""

import pytest

from arbitrage.ops import ledger as L
from arbitrage.ops.adapters import AMBIGUOUS, FAILED
from arbitrage.ops.common import LIVE
from arbitrage.ops.core import build
from arbitrage.ops.errors import BudgetExceeded, NotConfigured, OpsError, PolicyRefused, ReconciliationRequired
from arbitrage.ops.mandate import pending_mandate
from arbitrage.ops.metrics import compute
from arbitrage.ops.router.adapters import SimulatedJudge, simulated_router_adapters
from arbitrage.ops.router.intent import RouteRequest
from arbitrage.ops.router.jobs import install_router_schedules, register_router
from arbitrage.ops.router.judge import QualityJudge
from arbitrage.ops.router.reporting import router_report
from arbitrage.ops.router.service import build_router
from arbitrage.ops.workflows import WorkflowEngine

from .conftest import CATALOG, FX, SIM, credits_customer, keys_customer, router_mandate_with, settle_topup

PROMPT = "Classify the sentiment of this review: the product arrived late but works well and support answered quickly"
LONG_PROMPT = "Classify the sentiment of each review. " + " ".join(
    f"Review {i}: the {'lamp' if i % 2 else 'kettle'} number {i} arrived {'late' if i % 3 else 'early'} but works {'well' if i % 5 else 'badly'}."
    for i in range(300))


def request(key, customer, prompt=PROMPT, **kw):
    d = dict(quality_min=0.7, cost_cap_krw=500, task_type="classification", language="en")
    d.update(kw)
    return RouteRequest(key, customer, prompt, **d)


def metrics(core):
    with core.db.transaction() as tx:
        return compute(tx, core.ledger, SIM)


# -- platform credits ----------------------------------------------------------------------------------------

def test_credits_customer_routes_only_from_settled_balance_and_profit_realizes_after_the_window(router):
    core = router.core
    router.billing.register_customer(SIM, "acme", "Acme", "platform_credits", "simulated:billing", 0.10, "kr")
    proc = core.adapters["simulated:billing"]
    top = router.billing.topup(SIM, "acme", 20_000, "acme:topup")
    auth = proc.authorize(top.id, 20_000, "KRW")
    router.billing.apply_event({"source": auth.source, "kind": "authorization", "reference": auth.reference, "mode": SIM, "action_id": top.id, "amount": 20_000})
    cap = proc.capture(top.id, auth.reference, 20_000, "KRW")
    router.billing.apply_event({"source": cap.source, "kind": "capture", "reference": cap.reference, "mode": SIM, "action_id": top.id, "amount": 20_000})
    with core.db.transaction() as tx:
        assert router.billing.balance(tx, SIM, "acme") == 0        # captured, not settled: not spendable
    r = router.submit(request("r1", "acme"), SIM)
    with pytest.raises(PolicyRefused, match="prepaid balance 0 KRW does not cover"):
        router.route(r["id"])
    assert router.request(r["id"])["status"] == "failed"
    router.billing.apply_event({"source": "simulated:billing", "kind": "settlement", "reference": "SET-1", "mode": SIM, "action_id": top.id,
                                "amount": 20_000, "processor_fee": 600})
    with core.db.transaction() as tx:
        assert router.billing.balance(tx, SIM, "acme") == 20_000
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.CUSTOMER_BALANCES] == 20_000 and bal[L.PAYMENT_FEES] == 600 and bal[L.CASH] == 1_000_000 + 19_400
    r2 = router.submit(request("r2", "acme"), SIM)
    out = router.route(r2["id"])
    assert out["step"] == "delivered" and out["status"] == "settled" and out["task_type"] == "classification"
    assert out["plan"]["ladder"][0]["catalog_id"] == "simulated:provider-a:small:us"
    assert out["provider_cost_krw"] >= 1 and out["charge_krw"] >= out["provider_cost_krw"] and out["quality_score"] == 0.9
    assert out["dispute_window_ends"] and out["result"].startswith("[small]")
    with core.db.transaction() as tx:
        actions = core.gateway.list(tx, mode=SIM, kind="inference_call")
        assert [a.state for a in actions] == ["completed"]
        assert actions[0].reservation_id and core.governor.get(tx, actions[0].reservation_id).state == "committed"
        confs = core.gateway.confirmations(tx, actions[0].id)
        assert confs[0]["kind"] == "provider_usage" and confs[0]["source"] == "simulated:provider-a"
        assert router.billing.balance(tx, SIM, "acme") == 20_000 - out["charge_krw"]
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.INFERENCE_COST] == out["provider_cost_krw"] and bal[L.PAYABLE] == out["provider_cost_krw"]   # no prepaid credits: on invoice
        assert bal[L.GROSS_SALES] == out["charge_krw"] - out["tax_krw"] and bal[L.TAX_PAYABLE] == out["tax_krw"]
    m = metrics(core)
    assert m.trial_balance_ok and m.requests_routed == 2
    assert m.provisional_profit == out["charge_krw"] - out["tax_krw"] - out["provider_cost_krw"] - (out["judge"] and 0)
    assert m.realized_profit == -600                                   # only the processor fee is final so far
    assert router.close_dispute_windows(SIM, now="2027-01-01T00:00:00+00:00") == [r2["id"]]
    m = metrics(core)
    assert m.provisional_profit == 0 and m.realized_profit == -600 + out["charge_krw"] - out["tax_krw"] - out["provider_cost_krw"]
    assert core.audit.verify()[0]


def test_same_request_again_is_served_from_cache_for_free_and_a_refund_credits_the_balance(router):
    credits_customer(router, "acme", 20_000)
    first = router.route(router.submit(request("r1", "acme"), SIM)["id"])
    again = router.route(router.submit(request("r2", "acme"), SIM)["id"])
    assert again["cache_hit"] and again["cached_from"] == first["id"] and again["charge_krw"] == 0 and again["status"] == "closed"
    assert again["result"] == first["result"] and again["judge"]["method"] == "cache"
    assert router.submit(request("r1", "acme"), SIM)["id"] == first["id"]          # idempotent submit
    with router.db.transaction() as tx:
        assert len(router.gateway.list(tx, mode=SIM, kind="inference_call")) == 1
        before = router.billing.balance(tx, SIM, "acme")
    result = router.billing.refund_request(first["id"], first["charge_krw"], "goodwill")
    assert result["to"] == "balance"
    with router.db.transaction() as tx:
        assert router.billing.balance(tx, SIM, "acme") == before + first["charge_krw"]
        assert router.get(tx, first["id"])["status"] == "refunded"
    m = metrics(router.core)
    assert m.trial_balance_ok


# -- own keys --------------------------------------------------------------------------------------------------

def test_own_keys_customer_spends_no_platform_money_and_is_invoiced_through_the_processor(router):
    core = router.core
    keys_customer(router, "byok")
    r = router.submit(request("k1", "byok", LONG_PROMPT, cost_cap_krw=5_000, baseline_catalog_id="simulated:provider-a:large:us", max_output_tokens=4000), SIM)
    out = router.route(r["id"])
    assert out["step"] == "delivered" and out["billing_mode"] == "own_keys"
    with core.db.transaction() as tx:
        call = core.gateway.list(tx, mode=SIM, kind="inference_call")[0]
        assert call.state == "completed" and call.reservation_id is None and call.amount_krw == 0   # customer-funded
        assert core.governor.active_reservations(tx, SIM) == []
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.INFERENCE_COST] == 0 and bal[L.PAYABLE] == 0
        execs = router.executions(tx, r["id"])
        assert execs[0]["funding"] == "customer_key" and execs[0]["cost_krw"] == out["attempts_cost_krw"] > 0
    assert out["baseline_cost_krw"] > out["attempts_cost_krw"] and out["savings_krw"] > 0 and out["savings_verified"] is False
    assert "savings not verified" in out["judge"]["billing_basis"]
    if out["charge_krw"] > 0:
        assert out["payment_id"] and out["status"] == "open"
        proc = core.adapters["simulated:billing"]
        with core.db.transaction() as tx:
            pay = core.gateway.get(tx, out["payment_id"])
        auth = proc.authorize(pay.id, out["charge_krw"], "KRW")
        router.billing.apply_event({"source": auth.source, "kind": "authorization", "reference": auth.reference, "mode": SIM, "action_id": pay.id})
        cap = proc.capture(pay.id, auth.reference, out["charge_krw"], "KRW")
        router.billing.apply_event({"source": cap.source, "kind": "capture", "reference": cap.reference, "mode": SIM, "action_id": pay.id})
        assert router.request(r["id"])["status"] == "invoiced"
        router.billing.apply_event({"source": "simulated:billing", "kind": "settlement", "reference": "SET-K1", "mode": SIM, "action_id": pay.id,
                                    "amount": out["charge_krw"], "processor_fee": 0})
        assert router.request(r["id"])["status"] == "settled"
        with core.db.transaction() as tx:
            bal = core.ledger.balances(tx, SIM)
            assert bal[L.RECEIVABLE] == 0 and bal[L.GROSS_SALES] == out["charge_krw"] - out["tax_krw"]
    else:
        assert out["status"] == "closed"
    assert metrics(core).trial_balance_ok


# -- quality, escalation and failures ----------------------------------------------------------------------------

def test_failed_judge_escalates_up_the_ladder_and_the_catalog_learns(router):
    core = router.core
    credits_customer(router, "acme", 50_000)
    core.adapters["simulated:provider-a"].script_output("Sure! Here is a poem instead.", 12)
    router.judge.scorer.script(0.3, 0.95)
    out = router.route(router.submit(request("e1", "acme", cost_cap_krw=3_000), SIM)["id"])
    assert out["step"] == "delivered" and out["quality_score"] == 0.95
    with core.db.transaction() as tx:
        execs = router.executions(tx, out["id"])
        assert [(x["stage"], x["catalog_id"], x["passed"]) for x in execs] == [
            ("full", "simulated:provider-a:small:us", 0), ("escalation", "simulated:provider-b:medium:kr", 1)]
        assert out["provider_cost_krw"] == execs[1]["cost_krw"] and out["attempts_cost_krw"] == execs[0]["cost_krw"] + execs[1]["cost_krw"]
        small = router.catalog.get(tx, "simulated:provider-a:small:us")["quality"]["classification"]
        assert small == 0.3                    # first verdict replaces the seed
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.INFERENCE_COST] == out["attempts_cost_krw"]   # the platform paid for the failed attempt too
    assert out["charge_krw"] >= out["provider_cost_krw"]            # the customer pays only for the delivered result


def test_structural_failure_and_no_route_left_fail_the_request(router):
    core = router.core
    credits_customer(router, "acme", 50_000)
    core.adapters["simulated:provider-a"].script_output("not json at all", 10)
    core.adapters["simulated:provider-b"].script_output("still not json", 10)
    core.adapters["simulated:provider-a"].script_output("nope", 10)
    out = router.route(router.submit(request("x1", "acme", "Extract the invoice fields as JSON", task_type="extraction", cost_cap_krw=3_000), SIM)["id"])
    assert out["status"] == "failed" and "no route met the quality threshold" in out["last_error"]
    with core.db.transaction() as tx:
        execs = router.executions(tx, out["id"])
        assert len(execs) == 3 and all(x["passed"] == 0 for x in execs)
    m = metrics(core)
    assert m.realized_profit == -out["attempts_cost_krw"] and m.trial_balance_ok   # a failed request is a realized loss


def test_no_compliant_route_names_the_reasons(router):
    credits_customer(router, "acme", 50_000)
    r = router.submit(request("n1", "acme", quality_min=0.99), SIM)
    with pytest.raises(PolicyRefused, match="no compliant route"):
        router.route(r["id"])
    out = router.request(r["id"])
    assert out["status"] == "failed" and out["plan"]["feasible"] is False
    assert "provider terms do not permit routing customer work through this model" in out["plan"]["rejected"]["simulated:provider-b:grey:us"]
    assert any("region eu" in p for p in out["plan"]["rejected"]["simulated:provider-b:medium:eu"])
    with pytest.raises(PolicyRefused, match="task type"):
        router.submit(request("n2", "acme", task_type="image_analysis"), SIM)


def test_provider_failure_falls_through_and_cost_cap_stops_the_ladder(router):
    core = router.core
    credits_customer(router, "acme", 50_000)
    core.adapters["simulated:provider-a"].script("provider_usage", FAILED)
    out = router.route(router.submit(request("f1", "acme", cost_cap_krw=3_000), SIM)["id"])
    assert out["step"] == "delivered" and out["plan"]["ladder"][0]["catalog_id"] == "simulated:provider-a:small:us"
    with core.db.transaction() as tx:
        execs = router.executions(tx, out["id"])
        assert execs[0]["error"] == "simulated failure" and execs[1]["catalog_id"] == "simulated:provider-b:medium:kr" and execs[1]["passed"] == 1
        failed = [a for a in core.gateway.list(tx, mode=SIM, kind="inference_call") if a.state == "failed"]
        assert len(failed) == 1 and core.governor.get(tx, failed[0].reservation_id).state == "released"
    router.judge.scorer.script(0.2, 0.2, 0.2)
    out2 = router.route(router.submit(request("f2", "acme", "Classify: the kettle number nine leaks from the lid", cost_cap_krw=6), SIM)["id"])
    assert out2["status"] == "failed" and "cost cap exhausted" in out2["last_error"]


def test_unknown_result_must_reconcile_before_the_request_continues(router):
    core = router.core
    credits_customer(router, "acme", 50_000)
    core.adapters["simulated:provider-a"].script("provider_usage", AMBIGUOUS)
    r = router.submit(request("u1", "acme"), SIM)
    with pytest.raises(ReconciliationRequired, match="reconcile"):
        router.route(r["id"])
    with pytest.raises(ReconciliationRequired):
        router.route(r["id"])                                           # never retried blind
    with core.db.transaction() as tx:
        call = core.gateway.list(tx, mode=SIM, kind="inference_call")[0]
        assert call.state == "result_unknown" and core.governor.get(tx, call.reservation_id).state == "reserved"
        assert core.ledger.balances(tx, SIM)[L.INFERENCE_COST] == 0
    action = router.reconcile(call.id)
    assert action.state == "completed"
    out = router.route(r["id"])
    assert out["step"] == "delivered" and out["provider_cost_krw"] > 0
    with core.db.transaction() as tx:
        assert core.governor.get(tx, call.reservation_id).state == "committed"
        assert core.ledger.balances(tx, SIM)[L.INFERENCE_COST] == out["provider_cost_krw"]
    # a call the provider never recorded fails and gives its reservation back
    core.adapters["simulated:provider-a"].script("provider_usage", AMBIGUOUS)
    r2 = router.submit(request("u2", "acme", "Classify: a completely different review about a lamp that flickers"), SIM)
    with pytest.raises(ReconciliationRequired):
        router.route(r2["id"])
    with core.db.transaction() as tx:
        call2 = [a for a in core.gateway.list(tx, mode=SIM, kind="inference_call") if a.state == "result_unknown"][0]
    core.adapters["simulated:provider-a"].orders.clear()
    assert router.reconcile(call2.id).state == "failed"
    assert metrics(core).trial_balance_ok


# -- policy, mandate and money limits --------------------------------------------------------------------------------

def test_pause_blocks_routing_and_a_pending_live_mandate_refuses_everything(router, db):
    core = router.core
    credits_customer(router, "acme", 50_000)
    pid = core.pause("purchasing", "owner review", "owner")
    r = router.submit(request("p1", "acme"), SIM)
    with pytest.raises(PolicyRefused, match="paused"):
        router.route(r["id"])
    core.resume(pid, "owner")
    assert router.route(r["id"])["step"] == "delivered"
    live = build(db, pending_mandate(), {})
    live_router = build_router(live, None, FX, "test")
    with pytest.raises(OpsError, match="does not permit billing mode|pending"):
        live_router.billing.register_customer(LIVE, "real", "Real Co", "platform_credits", "stripe", 0.10, "kr")
    with live.db.transaction() as tx:
        assert live_router.catalog.list(tx, LIVE) == []
    assert router_report(live_router, LIVE)["requests"]["total"] == 0


def test_router_limits_refuse_before_any_call(db):
    m = router_mandate_with(**{"router.max_request_cost_krw": 1})
    core = build(db, m, simulated_router_adapters())
    router = build_router(core, QualityJudge(SimulatedJudge()), FX, "test")
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, SIM, 1_000_000, "simulated:bank", "cap:1")
        router.catalog.load_file(tx, CATALOG, SIM)
    credits_customer(router, "acme", 50_000)
    r = router.submit(request("l1", "acme", max_output_tokens=4000), SIM)
    with pytest.raises(PolicyRefused, match="no compliant route"):
        router.route(r["id"])
    assert any("mandate's per-request cap" in p for p in router.request(r["id"])["plan"]["rejected"]["simulated:provider-a:small:us"])
    # a customer's own key is not capped by the platform's per-request cap
    keys_customer(router, "byok")
    assert router.route(router.submit(request("l2", "byok", max_output_tokens=4000), SIM)["id"])["step"] == "delivered"
    with core.db.transaction() as tx:
        assert core.gateway.list(tx, mode=SIM, kind="inference_call")[0].amount_krw == 0


def test_prepaid_provider_credits_are_bought_through_the_gateway_and_consumed_first(router):
    core = router.core
    with pytest.raises(OpsError, match="exceeds"):
        router.prepay_provider(SIM, "simulated:provider-a", 250_000, "prepay:too-much")
    with pytest.raises(OpsError, match="not in the mandate"):
        router.prepay_provider(SIM, "simulated:provider-z", 1_000, "prepay:unknown")
    action = router.prepay_provider(SIM, "simulated:provider-a", 10_000, "prepay:1")
    assert action.state == "paid" and router.prepay_provider(SIM, "simulated:provider-a", 10_000, "prepay:1").state == "paid"
    with core.db.transaction() as tx:
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.PROVIDER_PREPAID] == 10_000 and bal[L.CASH] == 990_000
        assert router.books.provider_prepaid_balance(tx, SIM, "simulated:provider-a") == 10_000
        assert core.governor.exposure(tx, SIM) == 10_000
    credits_customer(router, "acme", 50_000)
    out = router.route(router.submit(request("c1", "acme"), SIM)["id"])
    with core.db.transaction() as tx:
        assert router.executions(tx, out["id"])[0]["funding"] == "prepaid"
        bal = core.ledger.balances(tx, SIM)
        assert bal[L.PROVIDER_PREPAID] == 10_000 - out["provider_cost_krw"] and bal[L.PAYABLE] == 0
        assert router.books.provider_prepaid_balance(tx, SIM, "simulated:provider-a") == 10_000 - out["provider_cost_krw"]
    core.adapters["simulated:provider-a"].script("payment_receipt", FAILED)
    assert router.prepay_provider(SIM, "simulated:provider-a", 5_000, "prepay:2").state == "failed"
    core.adapters["simulated:provider-a"].script("payment_receipt", AMBIGUOUS)
    with pytest.raises(ReconciliationRequired):
        router.prepay_provider(SIM, "simulated:provider-a", 5_000, "prepay:3")
    with pytest.raises(ReconciliationRequired):
        router.prepay_provider(SIM, "simulated:provider-a", 5_000, "prepay:3")
    assert metrics(core).trial_balance_ok


def test_customer_registration_never_stores_a_key_value_and_checks_the_mandate(router):
    with pytest.raises(OpsError, match="never stored"):
        router.billing.register_customer(SIM, "bad", "Bad", "own_keys", "simulated:billing", 0.1, "kr", [{"provider": "simulated:provider-a", "credential_ref": "sk-live-abc"}])
    with pytest.raises(OpsError, match="at least one provider credential"):
        router.billing.register_customer(SIM, "bad", "Bad", "own_keys", "simulated:billing", 0.1, "kr")
    with pytest.raises(OpsError, match="zero VAT"):
        router.billing.register_customer(SIM, "bad", "Bad", "platform_credits", "simulated:billing", 0.0, "us")
    with pytest.raises(OpsError, match="simulated: processor"):
        router.billing.register_customer(SIM, "bad", "Bad", "platform_credits", "stripe", 0.1, "kr")
    c = router.billing.register_customer(SIM, "ok", "Ok", "platform_credits", "simulated:billing", 0.0, "us", vat_basis="export of services, unverified")
    assert c["vat_rate"] == 0.0 and c["provider_credentials"] == []
    with pytest.raises(OpsError, match="own keys"):
        router.billing.topup(SIM, keys_customer(router, "byok"), 1_000, "byok:topup")


def test_unjudged_output_is_never_delivered(rcore):
    router = build_router(rcore, None, FX, "test")
    with rcore.db.transaction() as tx:
        router.catalog.load_file(tx, CATALOG, SIM)
    credits_customer(router, "acme", 50_000)
    with pytest.raises(NotConfigured, match="no quality judge"):
        router.route(router.submit(request("j1", "acme"), SIM)["id"])


# -- reporting and workflows -----------------------------------------------------------------------------------------

def test_report_and_durable_workflow(router):
    core = router.core
    credits_customer(router, "acme", 50_000)
    engine = WorkflowEngine(core.db, core.audit)
    register_router(engine, router)
    install_router_schedules(engine, SIM)
    core.adapters["simulated:provider-a"].script("provider_usage", AMBIGUOUS)
    r = router.submit(request("w1", "acme"), SIM)
    wf = engine.start("route_request", {"request_id": r["id"]}, dedupe_key=f"route:{r['id']}")
    assert engine.run_due("worker-1") == 1
    with core.db.transaction() as tx:
        w = engine.get(tx, wf)
        assert w.state == "pending" and w.attempts == 1 and "reconcile" in w.last_error   # waits for the reconciliation job
    rec = engine.start("reconcile_unknown_calls", {"mode": SIM})
    assert engine.run_due("worker-1") >= 1
    with core.db.transaction() as tx:
        assert engine.get(tx, rec).state == "done"
        engine._apply(tx, engine.get(tx, wf), __import__("arbitrage.ops.workflows", fromlist=["proceed"]).proceed(w.step))  # due now
    assert engine.run_due("worker-1") >= 1
    with core.db.transaction() as tx:
        assert engine.get(tx, wf).state == "done"
    out = router.request(r["id"])
    assert out["step"] == "delivered"
    report = router_report(router, SIM)
    assert report["label"].startswith("SIMULATED") and report["requests"]["total"] == 1 and report["customers"] == 1
    assert report["money_krw"]["charged"] == out["charge_krw"] and report["quality"]["passed"] == 1
    assert report["catalog"]["verified_prices"] == 0 and report["catalog"]["calls_on_unverified_prices"] == 1
    assert report["exceptions"]["result_unknown_calls"] == []
    assert engine.tick() and engine.run_due("worker-1") >= 1
