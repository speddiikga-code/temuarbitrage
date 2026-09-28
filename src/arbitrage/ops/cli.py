"""`arbitrage-ops`: migrate the database, show the numbers, pause and resume, run the worker, run the simulated demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from arbitrage.config import load_dotenv
from arbitrage.errors import ArbitrageError

from .adapters import SimulatedCarrier, SimulatedChannel, SimulatedProcessor, SimulatedSupplier
from .charters import load_charters, store_charters
from .common import LIVE, SIMULATED
from .core import build
from .dashboard import dashboard, readiness
from .jobs import install_schedules, register_standard
from .mandate import COMPUTE_ROUTER
from .orchestrator import Orchestrator
from .router.adapters import SimulatedJudge, simulated_router_adapters
from .router.jobs import install_router_schedules, register_router
from .router.judge import QualityJudge
from .router.service import build_router
from .workflows import WorkflowEngine

DEFAULT_DB = "sqlite:///data/ops.db"
# KRW per USD for the simulated demo: a static placeholder, not a quoted rate (open.er-api.com is what the scanner uses live).
DEMO_FX = {"USD": 1365.0}
DEMO_FX_ORIGIN = "static placeholder 2026-09-28, unverified"


def simulated_adapters() -> dict:
    return {"simulated:aliexpress": SimulatedSupplier("simulated:aliexpress"), "simulated:naverpay": SimulatedProcessor("simulated:naverpay"),
            "simulated:cj": SimulatedCarrier("simulated:cj"), "simulated:smartstore": SimulatedChannel("simulated:smartstore")}


def _default_mandate(args) -> str:
    if args.mandate:
        return args.mandate
    if "OPS_MANDATE" in os.environ:
        return os.environ["OPS_MANDATE"]
    if args.mode != SIMULATED:
        return "mandate.toml"
    return "mandate.router.simulated.toml" if getattr(args, "router", False) else "mandate.simulated.toml"


def _core(args):
    url = args.database or os.environ.get("OPS_DATABASE_URL", DEFAULT_DB)
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    adapters = {**simulated_adapters(), **simulated_router_adapters()} if args.mode == SIMULATED else {}
    core = build(url, _default_mandate(args), adapters)
    charters = load_charters()
    with core.db.transaction() as tx:
        store_charters(tx, charters)
        registry_file = Path(os.environ.get("OPS_REGISTRY", "integrations/registry.toml"))
        if registry_file.exists():
            core.registry.load_file(tx, registry_file)
    orchestrator = Orchestrator(core.db, charters, core.mandate, core.audit, core.pauses)
    engine = WorkflowEngine(core.db, core.audit)
    register_standard(engine, core, orchestrator)
    return core, orchestrator, engine


def _router(args, core, engine):
    """The router on top of the core. Simulated: the simulated judge and a placeholder FX rate; live: no judge, no FX yet."""
    from importlib import resources

    judge = QualityJudge(SimulatedJudge()) if args.mode == SIMULATED else None
    fx = DEMO_FX if args.mode == SIMULATED else _live_fx()
    router = build_router(core, judge, fx, DEMO_FX_ORIGIN if args.mode == SIMULATED else "OPS_FX_KRW_PER_USD environment variable")
    register_router(engine, router)
    with core.db.transaction() as tx:
        if args.mode == SIMULATED:
            router.catalog.load_file(tx, resources.files("arbitrage.ops").joinpath("router/catalog.simulated.toml"), SIMULATED)
        catalog_file = Path(os.environ.get("OPS_MODEL_CATALOG", "integrations/model_catalog.toml"))
        if args.mode == LIVE and catalog_file.exists():
            router.catalog.load_file(tx, catalog_file, LIVE)
    return router


def _live_fx() -> dict:
    raw = os.environ.get("OPS_FX_KRW_PER_USD")
    return {"USD": float(raw)} if raw else {}


def cmd_migrate(args):
    core, _, engine = _core(args)
    install_schedules(engine, args.mode)
    if core.mandate.domain == COMPUTE_ROUTER or args.mode == SIMULATED:
        _router(args, core, engine)
        install_router_schedules(engine, args.mode)
    print(f"schema ready on {core.db.url} ({core.db.dialect}); mandate {core.mandate.path}: "
          f"{'complete' if core.mandate.complete else str(len(core.mandate.pending_fields())) + ' pending fields'}")
    return 0


def cmd_status(args):
    core, orchestrator, engine = _core(args)
    router = _router(args, core, engine) if core.mandate.domain == COMPUTE_ROUTER else None
    doc = dashboard(core, args.mode, orchestrator, engine, router)
    if getattr(args, "json", False):
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
        return 0
    g, s, p, c = doc["goal"], doc["sales"], doc["profit"], doc["cash"]
    print(f"[{doc['label']}]")
    print(f"goal: reconciled net profit ₩{g['reconciled_net_profit_krw']:,} of ₩{g['target_realized_profit_krw']:,} ({g['progress']:.1%})")
    print(f"orders {s['orders_placed']}  gross ₩{s['gross_sales']:,}  net revenue ₩{s['net_revenue']:,}  settled cash ₩{s['settled_cash']:,}  receivables ₩{s['payment_receivables']:,}")
    print(f"profit: realized ₩{p['realized']:,}  provisional ₩{p['provisional']:,}  (contribution ₩{p['contribution']:,}, operating ₩{p['operating']:,})")
    print(f"cash: headroom ₩{c['available_headroom']:,}  reserves ₩{c['required_reserves']:,}  commitments ₩{c['unpaid_commitments']:,}  reinvestable ₩{c['available_reinvestment']:,}")
    print(f"inventory ₩{doc['inventory']['value']:,}  prepaid purchases ₩{doc['inventory']['outstanding_purchases_prepaid']:,}")
    md = doc["mandate"]
    print(f"mandate: {md['environment']}, {'complete' if md['complete'] else str(len(md['pending_fields'])) + ' pending: ' + ', '.join(md['pending_fields'][:5]) + ('...' if len(md['pending_fields']) > 5 else '')}")
    print(f"pauses: {', '.join(p['scope'] + ' (' + p['kind'] + ': ' + p['reason'][:60] + ')' for p in doc['pauses']) or 'none'}")
    ex = doc["exceptions"]
    print(f"exceptions: {len(ex['failed_or_unknown_actions'])} failed/unknown actions, {len(ex['escalated_tasks'])} escalated tasks")
    print(f"trial balance: {'ok' if doc['trial_balance_ok'] else 'OUT OF BALANCE'}")
    r = doc.get("router")
    if r:
        rq, mo, q = r["requests"], r["money_krw"], r["quality"]
        print(f"router: {r['customers']} customer(s), {rq['total']} request(s) {rq['by_status']}, cache hits {rq['cache_hits']}, escalations {rq['escalations']}")
        print(f"router money: provider cost ₩{mo['provider_cost_delivered']:,} (all attempts ₩{mo['provider_cost_all_attempts']:,}), charged ₩{mo['charged']:,}, "
              f"fees ₩{mo['platform_fees']:,}, verified savings ₩{mo['verified_savings']:,}, estimated savings ₩{mo['estimated_savings']:,}")
        print(f"router quality: {q['passed']}/{q['judged']} judged outputs passed; catalog {r['catalog']['entries']} entries, "
              f"{r['catalog']['verified_prices']} verified prices, {r['catalog']['calls_on_unverified_prices']} calls on unverified prices")
    return 0


def cmd_readiness(args):
    core, orchestrator, _ = _core(args)
    print(json.dumps(readiness(core, orchestrator), ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_mandate(args):
    core, _, _ = _core(args)
    print(json.dumps(core.mandate.summary(), ensure_ascii=False, indent=2))
    return 0 if core.mandate.complete else 1


def cmd_pause(args):
    core, _, _ = _core(args)
    pid = core.pause(args.scope, args.reason, args.by)
    print(f"paused {args.scope}: {pid}")
    return 0


def cmd_resume(args):
    core, _, _ = _core(args)
    print("resumed" if core.resume(args.pause_id, args.by) else "no such active pause")
    return 0


def cmd_worker(args):
    core, orchestrator, engine = _core(args)
    install_schedules(engine, args.mode)
    if core.mandate.domain == COMPUTE_ROUTER or args.mode == SIMULATED:
        _router(args, core, engine)
        install_router_schedules(engine, args.mode)
    started = engine.tick()
    ran = engine.run_due(args.name, limit=50)
    expired = orchestrator.expire()
    print(f"worker {args.name}: started {len(started)} scheduled workflow(s), ran {ran} step(s), expired {len(expired)} agent run(s)")
    if not args.once:
        print("continuous mode is not enabled: no persistent infrastructure is deployed yet (see docs/readiness.md); run with --once from a scheduler")
        return 2
    return 0


def cmd_audit(args):
    core, _, _ = _core(args)
    ok, count, broken = core.audit.verify()
    print(f"audit chain {'intact' if ok else 'BROKEN at seq ' + str(broken)}: {count} records")
    return 0 if ok else 1


def cmd_demo(args):
    """The whole path with simulated adapters: nothing real is bought, sold or paid."""
    if args.mode != SIMULATED:
        print("demo runs only with --mode simulated", file=sys.stderr)
        return 2
    from .purchases import PurchaseProposal

    core, orchestrator, engine = _core(args)
    print("=== SIMULATED DEMO: simulated adapters, simulated mandate, nothing real happens ===")
    supplier, processor, carrier = (core.adapters[k] for k in ("simulated:aliexpress", "simulated:naverpay", "simulated:cj"))
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, SIMULATED, 1_000_000, "simulated:bank", "demo:capital")
    fx = 1365.0
    amount_krw = round((3.2 * 10 + 1.5) * fx)
    proposal = PurchaseProposal(idempotency_key="demo:po-1", supplier="simulated:aliexpress", sku="tongs", quantity=10, unit_price=3.2,
                                currency="USD", shipping=1.5, fx_rate=fx, amount_krw=amount_krw, duty_krw=round(amount_krw * 0.188),
                                category="kitchen", import_basis="commercial_resale",
                                price_evidence={"source": "smartstore listing", "url": "https://smartstore.naver.com/x/1", "date": "2026-09-27"})
    a = core.purchasing.propose(proposal, SIMULATED, "demo")
    core.purchasing.verify(a.id, supplier.quote("tongs", 10))
    core.purchasing.reserve(a.id)
    a = core.purchasing.place(a.id)
    a = core.purchasing.mark_shipped(a.id, supplier.shipment(a.id, "PO"))
    a = core.purchasing.receive(a.id, {"source": "simulated:warehouse", "kind": "receiving", "reference": "RCV-demo", "mode": SIMULATED}, duties_krw=a.payload["duty_krw"])
    print(f"purchase {a.id}: {a.state}, ₩{a.amount_krw:,} + duty ₩{a.payload['duty_krw']:,}, 10 units in stock")
    order, payment = core.payments.create_order(SIMULATED, "simulated:naver", "DEMO-1", "tongs", 1, 22_000, 0, 2_000, 1_500, "simulated:naverpay",
                                                "commercial_resale", placed_at="2026-09-01T00:00:00+00:00")
    auth = processor.authorize(payment.id, 22_000, "KRW")
    core.payments.apply_event({"source": auth.source, "kind": "authorization", "reference": auth.reference, "mode": SIMULATED, "order_id": order.id, "amount": 22_000})
    cap = processor.capture(payment.id, auth.reference, 22_000, "KRW")
    core.payments.apply_event({"source": cap.source, "kind": "capture", "reference": cap.reference, "mode": SIMULATED, "order_id": order.id, "amount": 22_000})
    f = core.fulfillment.create(order.id, "simulated:cj")
    core.fulfillment.allocate(f.id)
    core.fulfillment.pack(f.id)
    f = core.fulfillment.ship(f.id, 3_000)
    core.fulfillment.deliver(f.id, carrier.confirm_delivery(f.id, f.payload["tracking"]))
    core.payments.apply_event({"source": "simulated:naverpay", "kind": "settlement", "reference": "SET-DEMO-1", "mode": SIMULATED, "order_id": order.id,
                               "payout": 20_200, "marketplace_fee": 1_600, "payment_fee": 200})
    core.fulfillment.close_return_windows(SIMULATED, now="2026-10-01T00:00:00+00:00")
    print(f"order {order.external_order_id}: paid, shipped, delivered, settled, return window closed")
    return cmd_status(args)


# -- router commands -----------------------------------------------------------------------------------------

def cmd_router_catalog(args):
    core, _, engine = _core(args)
    router = _router(args, core, engine)
    with core.db.transaction() as tx:
        rows = router.catalog.list(tx, args.mode)
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0
    for r in rows:
        ev = r["evidence"]
        print(f"{r['id']}: tier {r['tier']}, {r['currency']} {r['input_micros_per_mtok'] / 1e6:.2f}/{r['output_micros_per_mtok'] / 1e6:.2f} per MTok, "
              f"{r['latency_ms']} ms, terms {'ok' if r['terms_permit'] else 'NOT permitted'}, "
              f"price {'verified' if r['price_verified'] else 'UNVERIFIED'} ({ev.get('source')}, {ev.get('date')}), quality {r['quality']}")
    return 0


def cmd_router_requests(args):
    core, _, engine = _core(args)
    router = _router(args, core, engine)
    with core.db.transaction() as tx:
        rows = router.list(tx, args.mode, args.status, args.limit)
    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return 0
    for r in rows:
        chosen = (r["plan"].get("ladder") or [{}])[0].get("catalog_id") if r["plan"].get("ladder") else r["plan"].get("cache", "-")
        print(f"{r['id']} {r['customer_id']} {r['task_type']} {r['step']}/{r['status']} route {chosen} cost ₩{r['provider_cost_krw']:,} "
              f"charge ₩{r['charge_krw']:,} quality {r['quality_score']} cache {'hit' if r['cache_hit'] else 'miss'}"
              + (f" error: {r['last_error']}" if r["last_error"] else ""))
    return 0


def cmd_router_demo(args):
    """The routing path with simulated providers, judge and billing: nothing real is called, charged or earned."""
    if args.mode != SIMULATED:
        print("router demo runs only with --mode simulated", file=sys.stderr)
        return 2
    from .router.intent import RouteRequest

    core, _, engine = _core(args)
    router = _router(args, core, engine)
    print("=== SIMULATED ROUTER DEMO: simulated providers, judge and billing processor; no model is called, no money moves ===")
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, SIMULATED, 1_000_000, "simulated:bank", "router-demo:capital")
    billing = core.adapters["simulated:billing"]
    # a prepaid customer tops up; the balance is spendable only once the processor settles it
    router.billing.register_customer(SIMULATED, "demo-credits", "Demo (platform credits)", "platform_credits", "simulated:billing", 0.10, "kr")
    top = router.billing.topup(SIMULATED, "demo-credits", 100_000, "router-demo:topup")
    auth = billing.authorize(top.id, 100_000, "KRW")
    router.billing.apply_event({"source": auth.source, "kind": "authorization", "reference": auth.reference, "mode": SIMULATED, "action_id": top.id, "amount": 100_000})
    cap = billing.capture(top.id, auth.reference, 100_000, "KRW")
    router.billing.apply_event({"source": cap.source, "kind": "capture", "reference": cap.reference, "mode": SIMULATED, "action_id": top.id, "amount": 100_000})
    router.billing.apply_event({"source": "simulated:billing", "kind": "settlement", "reference": "SET-ROUTER-DEMO", "mode": SIMULATED,
                                "action_id": top.id, "amount": 100_000, "processor_fee": 3_000})
    # an own-keys customer pays the provider directly and is billed a share of verified savings, or a fee on metered cost
    router.billing.register_customer(SIMULATED, "demo-keys", "Demo (own keys)", "own_keys", "simulated:billing", 0.10, "kr",
                                     [{"provider": "simulated:provider-a", "credential_ref": "DEMO_PROVIDER_A_KEY"}])
    long_context = "\n\n".join(f"Section {i}: invoice {1000 + i} from supplier {i % 7} totals {i * 137} won, due in {i % 30} days. " * 6 for i in range(60))
    prompt = "Extract every invoice number and total as a JSON list"
    adapters = core.adapters
    adapters["simulated:provider-a"].script_output('[{"invoice": 1000, "total": 0}]', 40)
    adapters["simulated:provider-b"].script_output('[{"invoice": 1000, "total": 0}, {"invoice": 1001, "total": 137}]', 60)
    r1 = router.submit(RouteRequest("router-demo:1", "demo-credits", prompt, long_context, task_type="extraction", quality_min=0.8, cost_cap_krw=4_000,
                                    baseline_catalog_id="simulated:provider-a:large:us", language="en"), SIMULATED, "demo")
    out = router.route(r1["id"])
    print(f"request 1 (platform credits): {out['step']}/{out['status']}, route {out['plan']['ladder'][0]['catalog_id']}, "
          f"tokens {out['input_tokens_raw']} -> {out['input_tokens_sent']} sent, provider cost ₩{out['provider_cost_krw']:,}, charged ₩{out['charge_krw']:,} "
          f"(fee ₩{out['fee_krw']:,}, VAT ₩{out['tax_krw']:,}), quality {out['quality_score']}, estimated savings ₩{out['savings_krw']:,} (unverified prices)")
    r2 = router.submit(RouteRequest("router-demo:2", "demo-credits", prompt, long_context, task_type="extraction", quality_min=0.8, cost_cap_krw=4_000,
                                    language="en"), SIMULATED, "demo")
    out2 = router.route(r2["id"])
    print(f"request 2 (same task again): {out2['step']}/{out2['status']}, cache {'hit' if out2['cache_hit'] else 'miss'}, charged ₩{out2['charge_krw']:,}")
    adapters["simulated:provider-a"].script_output("Sure, here is a haiku instead.", 12)   # the cheap route fails the judge
    router.judge.scorer.script(0.4)
    r3 = router.submit(RouteRequest("router-demo:3", "demo-keys", "Translate into Korean: The shipment leaves Busan on Monday and reaches Incheon by Wednesday.",
                                    task_type="translation", quality_min=0.85, cost_cap_krw=2_000, baseline_catalog_id="simulated:provider-a:large:us",
                                    language="ko"), SIMULATED, "demo")
    adapters["simulated:provider-b"].script_output("화물은 월요일에 부산을 출발하여 수요일까지 인천에 도착합니다.", 30)
    out3 = router.route(r3["id"])
    with core.db.transaction() as tx:
        execs = router.executions(tx, r3["id"])
    print(f"request 3 (own keys, escalation): {out3['step']}/{out3['status']}, {len(execs)} call(s): "
          + " -> ".join(f"{x['catalog_id']} ({'passed' if x['passed'] else 'failed'})" for x in execs)
          + f", customer's provider cost ₩{out3['attempts_cost_krw']:,}, fee invoiced ₩{out3['charge_krw']:,} ({out3['judge'].get('billing_basis')})")
    router.close_dispute_windows(SIMULATED, now="2027-01-01T00:00:00+00:00")
    return cmd_status(args)


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="arbitrage-ops", description="Operating core: ledger, budget, gateway, workflows.")
    parser.add_argument("--database", help="sqlite:///PATH or postgresql://... (default: OPS_DATABASE_URL or sqlite:///data/ops.db)")
    parser.add_argument("--mandate", help="mandate file (default: mandate.toml, or mandate.simulated.toml for --mode simulated)")
    parser.add_argument("--mode", choices=(LIVE, SIMULATED), default=LIVE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="create tables, load charters and the registry, install schedules").set_defaults(func=cmd_migrate)
    p = sub.add_parser("status", help="the owner's numbers for one mode")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)
    sub.add_parser("readiness", help="built, tested, live, pending, blocked").set_defaults(func=cmd_readiness)
    sub.add_parser("mandate", help="show the mandate and its pending fields (exit 1 if incomplete)").set_defaults(func=cmd_mandate)
    p = sub.add_parser("pause", help="owner pause")
    p.add_argument("--scope", choices=("purchasing", "all"), default="purchasing")
    p.add_argument("--reason", required=True)
    p.add_argument("--by", default="owner")
    p.set_defaults(func=cmd_pause)
    p = sub.add_parser("resume", help="lift a pause")
    p.add_argument("pause_id")
    p.add_argument("--by", default="owner")
    p.set_defaults(func=cmd_resume)
    p = sub.add_parser("worker", help="run due schedules and workflow steps once")
    p.add_argument("--name", default="worker-1")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_worker)
    sub.add_parser("audit", help="verify the audit hash chain").set_defaults(func=cmd_audit)
    sub.add_parser("demo", help="run the whole path with simulated adapters (--mode simulated)").set_defaults(func=cmd_demo)
    r = sub.add_parser("router", help="GlobalCompute Router: catalog, requests, simulated demo")
    r.set_defaults(router=True)
    rs = r.add_subparsers(dest="router_command", required=True)
    p = rs.add_parser("catalog", help="list the model catalog with prices, evidence and learned quality")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_router_catalog)
    p = rs.add_parser("requests", help="list routed requests")
    p.add_argument("--status")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_router_requests)
    p = rs.add_parser("demo", help="route three simulated requests: credits, cache hit, own keys with escalation (--mode simulated)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_router_demo)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ArbitrageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
