"""Router tests run on SQLite and, with OPSCORE_TEST_DATABASE_URL, on PostgreSQL too (the `db` fixture is the core's)."""

from importlib import resources

import pytest

from arbitrage.ops.core import build
from arbitrage.ops.mandate import load_mandate
from arbitrage.ops.router.adapters import SimulatedJudge, simulated_router_adapters
from arbitrage.ops.router.judge import QualityJudge
from arbitrage.ops.router.service import build_router

from ..conftest import ROOT

SIM = "simulated"
FX = {"USD": 1365.0}
CATALOG = resources.files("arbitrage.ops").joinpath("router/catalog.simulated.toml")


@pytest.fixture
def router_mandate():
    return load_mandate(ROOT / "mandate.router.simulated.toml")


def router_mandate_with(**overrides):
    """The simulated router mandate with some values replaced (dotted names like router.max_request_cost_krw)."""
    import tomllib
    import uuid

    from arbitrage.ops.mandate import parse_mandate

    data = tomllib.loads((ROOT / "mandate.router.simulated.toml").read_text("utf-8"))
    for name, value in overrides.items():
        section, key = name.split(".")
        data.setdefault(section, {})[key] = value
    return parse_mandate(data, f"<router override {uuid.uuid4().hex[:6]}>")


@pytest.fixture
def rcore(db, router_mandate):
    core = build(db, router_mandate, simulated_router_adapters())
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, SIM, 1_000_000, "simulated:bank", "cap:1")
    return core


@pytest.fixture
def router(rcore):
    r = build_router(rcore, QualityJudge(SimulatedJudge()), FX, "test placeholder")
    with rcore.db.transaction() as tx:
        r.catalog.load_file(tx, CATALOG, SIM)
    return r


def settle_topup(router, customer_id: str, amount: int, key: str = "topup:1", fee: int = 0):
    """Authorize, capture and settle a top-up through the simulated processor; returns the payment action."""
    proc = router.core.adapters["simulated:billing"]
    top = router.billing.topup(SIM, customer_id, amount, f"{customer_id}:{key}")
    auth = proc.authorize(top.id, amount, "KRW")
    router.billing.apply_event({"source": auth.source, "kind": "authorization", "reference": auth.reference, "mode": SIM, "action_id": top.id, "amount": amount})
    cap = proc.capture(top.id, auth.reference, amount, "KRW")
    router.billing.apply_event({"source": cap.source, "kind": "capture", "reference": cap.reference, "mode": SIM, "action_id": top.id, "amount": amount})
    router.billing.apply_event({"source": "simulated:billing", "kind": "settlement", "reference": f"SET-{customer_id}-{key}", "mode": SIM,
                                "action_id": top.id, "amount": amount, "processor_fee": fee})
    return top


ACCEPTED = dict(terms_accepted_at="2026-09-28T00:00:00+00:00", ai_disclosure_confirmed=True)


def credits_customer(router, customer_id="acme", amount=50_000, vat=0.10, region="kr", **kw):
    router.billing.register_customer(SIM, customer_id, "Acme", "platform_credits", "simulated:billing", vat, region, **{**ACCEPTED, **kw})
    if amount:
        settle_topup(router, customer_id, amount)
    return customer_id


def keys_customer(router, customer_id="byok", providers=("simulated:provider-a", "simulated:provider-b")):
    router.billing.register_customer(SIM, customer_id, "BYOK Ltd", "own_keys", "simulated:billing", 0.10, "kr",
                                     [{"provider": p, "credential_ref": "CUSTOMER_KEY_" + p.split("-")[-1].upper()} for p in providers], **ACCEPTED)
    return customer_id
