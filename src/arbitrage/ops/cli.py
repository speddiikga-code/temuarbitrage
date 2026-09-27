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
from .orchestrator import Orchestrator
from .workflows import WorkflowEngine

DEFAULT_DB = "sqlite:///data/ops.db"


def simulated_adapters() -> dict:
    return {"simulated:aliexpress": SimulatedSupplier("simulated:aliexpress"), "simulated:naverpay": SimulatedProcessor("simulated:naverpay"),
            "simulated:cj": SimulatedCarrier("simulated:cj"), "simulated:smartstore": SimulatedChannel("simulated:smartstore")}


def _core(args):
    url = args.database or os.environ.get("OPS_DATABASE_URL", DEFAULT_DB)
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    mandate_path = args.mandate or os.environ.get("OPS_MANDATE", "mandate.simulated.toml" if args.mode == SIMULATED else "mandate.toml")
    core = build(url, mandate_path, simulated_adapters() if args.mode == SIMULATED else {})
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


def cmd_migrate(args):
    core, _, engine = _core(args)
    install_schedules(engine, args.mode)
    print(f"schema ready on {core.db.url} ({core.db.dialect}); mandate {core.mandate.path}: "
          f"{'complete' if core.mandate.complete else str(len(core.mandate.pending_fields())) + ' pending fields'}")
    return 0


def cmd_status(args):
    core, orchestrator, engine = _core(args)
    doc = dashboard(core, args.mode, orchestrator, engine)
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
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ArbitrageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
