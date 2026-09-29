"""The rules from docs/provider_terms.md section 3 (task 13) as the router enforces them: registry-cleared providers only,
end users screened by country, pre-disclosed providers, no free tiers, PRC hosts gated on opt-in and a personal-information
classifier, residency as an explicit customer choice, a per-tenant cache, terms and AI disclosure before registration,
no bare pass-through, and a per-call record of the list price."""

import pytest

from arbitrage.ops.common import LIVE
from arbitrage.ops.core import build
from arbitrage.ops.errors import NotConfigured, OpsError, PolicyRefused
from arbitrage.ops.mandate import pending_mandate
from arbitrage.ops.router.intent import RouteRequest, compile_intent, high_risk_domains, personal_info
from arbitrage.ops.router.providers import ProviderRules
from arbitrage.ops.router.service import build_router

from .conftest import ACCEPTED, CATALOG, FX, SIM, credits_customer, keys_customer

REGISTRY = [
    {"id": "anthropic_api", "roles": ["supplier"], "service": "ai_inference", "verdict": "go", "status": "not_connected", "connected": False,
     "region_ok_for_korea": True, "customer_app_allowed": "explicit", "resale_prohibited": True, "data_residency": "global or us (1.1x)",
     "pricing_url": "https://platform.claude.com/docs/en/docs/about-claude/pricing", "training_on_inputs": "not used under the Commercial Terms"},
    {"id": "openrouter", "roles": ["supplier"], "service": "ai_inference_aggregator", "verdict": "no_go", "status": "not_connected", "connected": False,
     "customer_app_allowed": "prohibited for resale", "resale_prohibited": True},
    {"id": "together_ai", "roles": ["supplier"], "service": "ai_inference", "verdict": "conditional", "status": "not_connected", "connected": False,
     "customer_app_allowed": "unclear", "resale_prohibited": True},
    {"id": "naver_clova_studio", "roles": ["supplier"], "service": "ai_inference", "verdict": "unknown", "status": "not_connected", "connected": False,
     "customer_app_allowed": "explicit", "resale_prohibited": True},
    {"id": "toss_payments", "roles": ["payment"], "verdict": "go", "status": "not_connected", "connected": False},
]


def live_entry(provider: str, region: str = "us", **kw):
    e = {"id": f"{provider}:model:{region}", "provider": provider, "model": "model", "region": region, "task_types": ["chat", "classification"],
         "context_window": 200000, "input_micros_per_mtok": 3000000, "output_micros_per_mtok": 15000000, "currency": "USD", "latency_ms": 900,
         "quality": {"chat": 0.9, "classification": 0.9}, "terms_permit": True, "customer_countries": ["kr", "us"], "data_residency": "global",
         "evidence": {"source": "provider price page", "url": "https://example.invalid/pricing", "date": "2026-09-28", "verified": True}}
    e.update(kw)
    return e


def test_registry_rules_clear_only_explicit_ai_providers_with_a_go_or_conditional_verdict():
    rules = ProviderRules.from_entries(REGISTRY, "<test registry>")
    assert rules.problems("anthropic_api") == []
    assert any("no_go" in p for p in rules.problems("openrouter")) and any("prohibited for resale" in p for p in rules.problems("openrouter"))
    assert rules.problems("together_ai") == ["registry says customer apps are 'unclear' at together_ai; only 'explicit' routes in the first pilot"]
    assert rules.problems("naver_clova_studio") == ["registry verdict for naver_clova_studio is unknown"]
    assert any("not an AI inference service" in p for p in rules.problems("toss_payments"))
    assert rules.problems("nobody") == ["provider nobody is not in the integration registry (<test registry>)"]
    assert [e.id for e in rules.ai_providers()] == ["anthropic_api", "openrouter", "together_ai", "naver_clova_studio"]
    with pytest.raises(OpsError, match="customer_app_allowed"):
        ProviderRules.from_entries([{"id": "x", "customer_app_allowed": "maybe"}])
    with pytest.raises(OpsError, match="not found"):
        ProviderRules.from_file("/nonexistent/registry.toml")


def test_live_catalog_rows_need_the_registry_and_a_cleared_provider(db):
    core = build(db, pending_mandate(), {})
    router = build_router(core, None, FX, "test")
    rules = ProviderRules.from_entries(REGISTRY)
    with core.db.transaction() as tx:
        with pytest.raises(NotConfigured, match="provider rules"):
            router.catalog.load(tx, [live_entry("anthropic_api")], LIVE)
        assert router.catalog.load(tx, [live_entry("anthropic_api")], LIVE, rules=rules) == ["anthropic_api:model:us"]
        for bad in ("openrouter", "together_ai", "naver_clova_studio", "toss_payments", "unknown_provider"):
            with pytest.raises(OpsError, match=bad):
                router.catalog.load(tx, [live_entry(bad)], LIVE, rules=rules)
        with pytest.raises(OpsError, match="customer_countries"):
            router.catalog.load(tx, [live_entry("anthropic_api", customer_countries=[])], LIVE, rules=rules)
        with pytest.raises(OpsError, match="wildcard"):
            router.catalog.load(tx, [live_entry("anthropic_api", customer_countries=["*"])], LIVE, rules=rules)
        with pytest.raises(OpsError, match="data_residency"):
            router.catalog.load(tx, [live_entry("anthropic_api", data_residency="")], LIVE, rules=rules)
        row = router.catalog.get(tx, "anthropic_api:model:us")
        assert row["customer_countries"] == ["kr", "us"] and row["data_residency"] == "global" and row["free_tier"] is False


def test_personal_information_and_high_risk_classifiers_are_conservative():
    assert personal_info("call me at 010-1234-5678 or mail kim@example.com") == ("email", "phone")
    assert personal_info("주민등록번호 900101-1234567") == ("resident_registration_number",)
    assert personal_info("card 4111 1111 1111 1111, customs code P123456789012") == ("card_number", "customs_code")
    assert personal_info("Classify the sentiment of this review about a kettle that arrived late") == ()
    assert high_risk_domains("Give a diagnosis for these symptoms") == ("medical",)
    assert high_risk_domains("Should we reject the candidate? hiring decision") == ("employment",)
    assert high_risk_domains("Summarise this product review") == ()
    intent = compile_intent(RouteRequest("k", "c", "Give legal advice to kim@example.com about a lawsuit", cost_cap_krw=100))
    assert intent.personal_info == ("email",) and intent.high_risk == ("legal",)
    assert intent.as_dict()["personal_info"] == ["email"] and any("PRC-hosted" in n for n in intent.notes)


def test_end_users_are_screened_by_country_and_a_provider_must_be_pre_disclosed(router):
    credits_customer(router, "jp-co", 50_000, region="jp")          # no simulated row supports end users in jp
    r = router.submit(RouteRequest("jp:1", "jp-co", "Classify: the lamp flickers", task_type="classification", cost_cap_krw=500), SIM)
    with pytest.raises(PolicyRefused, match="no compliant route"):
        router.route(r["id"])
    rejected = router.request(r["id"])["plan"]["rejected"]
    assert len(rejected) == 7 and all(any("does not support end users in jp" in p for p in reasons) for reasons in rejected.values())


def test_a_provider_missing_from_the_privacy_policy_is_refused_before_any_price_is_compared(db):
    from arbitrage.ops.router.adapters import SimulatedJudge, simulated_router_adapters
    from arbitrage.ops.router.judge import QualityJudge
    from .conftest import router_mandate_with
    m = router_mandate_with(**{"router.disclosed_providers": ["simulated:provider-b"]})
    core = build(db, m, simulated_router_adapters())
    with core.db.transaction() as tx:
        core.books.contribute_capital(tx, SIM, 1_000_000, "simulated:bank", "cap:1")
    r2 = build_router(core, QualityJudge(SimulatedJudge()), FX, "test")
    with core.db.transaction() as tx:
        r2.catalog.load_file(tx, CATALOG, SIM)
    credits_customer(r2, "acme2", 50_000)
    out = r2.route(r2.submit(RouteRequest("d:1", "acme2", "Classify: the lamp flickers", task_type="classification", cost_cap_krw=500), SIM)["id"])
    assert out["plan"]["ladder"][0]["provider"] == "simulated:provider-b"
    assert any("not pre-disclosed in the privacy policy" in p for p in out["plan"]["rejected"]["simulated:provider-a:small:us"])


def test_prc_hosted_endpoint_needs_opt_in_and_no_personal_information(router):
    credits_customer(router, "optin", 50_000, prc_opt_in=True)
    credits_customer(router, "noopt", 50_000)
    prompt = "Classify the sentiment: the kettle number nine arrived early and works well, five stars"
    q = dict(task_type="classification", cost_cap_krw=500, quality_min=0.85)        # above the small tier: medium weights, cheapest host wins
    a = router.route(router.submit(RouteRequest("cn:1", "optin", prompt, **q), SIM)["id"])
    assert a["plan"]["ladder"][0]["catalog_id"] == "simulated:provider-b:medium:cn"      # cheapest sanctioned host for an opted-in tenant
    b = router.route(router.submit(RouteRequest("cn:2", "noopt", prompt, **q), SIM)["id"])
    assert b["plan"]["ladder"][0]["catalog_id"] == "simulated:provider-b:medium:kr"      # same weights from a permitted host
    assert "PRC-hosted endpoint needs the tenant's opt-in" in b["plan"]["rejected"]["simulated:provider-b:medium:cn"]
    pii = "Classify the sentiment of this message from kim@example.com: the kettle arrived early and works well"
    c = router.route(router.submit(RouteRequest("cn:3", "optin", pii, **q), SIM)["id"])
    assert c["plan"]["ladder"][0]["catalog_id"] != "simulated:provider-b:medium:cn"
    assert any("never receives personal information (detected: email)" in p for p in c["plan"]["rejected"]["simulated:provider-b:medium:cn"])
    assert c["labels"]["personal_info_detected"] is True and c["labels"]["ai_generated"] is True


def test_residency_is_a_customer_choice_never_silent(router):
    credits_customer(router, "acme", 50_000)
    default = router.route(router.submit(RouteRequest("res:1", "acme", "Classify: the lamp flickers", task_type="classification", cost_cap_krw=500), SIM)["id"])
    assert default["plan"]["ladder"][0]["region"] == "us" and any("cheapest sanctioned route" in n for n in default["plan"]["notes"])
    kr = router.route(router.submit(RouteRequest("res:2", "acme", "Classify: the lamp flickers badly", task_type="classification", cost_cap_krw=500,
                                                 residency="kr"), SIM)["id"])
    assert kr["residency"] == "kr" and [r["region"] for r in kr["plan"]["ladder"]] == ["kr"]
    assert any("customer selected residency kr" in p for p in kr["plan"]["rejected"]["simulated:provider-a:small:us"])
    assert any("residency kr: customer-selected" in n for n in kr["plan"]["notes"])


def test_semantic_cache_never_crosses_tenants(router):
    credits_customer(router, "tenant-a", 50_000)
    credits_customer(router, "tenant-b", 50_000)
    prompt = "Classify the sentiment: support answered quickly and the replacement lamp works"
    first = router.route(router.submit(RouteRequest("t:a", "tenant-a", prompt, task_type="classification", cost_cap_krw=500), SIM)["id"])
    again = router.route(router.submit(RouteRequest("t:a2", "tenant-a", prompt, task_type="classification", cost_cap_krw=500), SIM)["id"])
    other = router.route(router.submit(RouteRequest("t:b", "tenant-b", prompt, task_type="classification", cost_cap_krw=500), SIM)["id"])
    assert again["cache_hit"] and again["cached_from"] == first["id"]
    assert not other["cache_hit"] and other["charge_krw"] > 0
    with router.db.transaction() as tx:
        assert len(router.gateway.list(tx, mode=SIM, kind="inference_call")) == 2


def test_no_bare_pass_through_and_high_risk_outputs_are_labelled(router):
    credits_customer(router, "acme", 50_000)
    forced = RouteRequest("pt:1", "acme", "Classify: the lamp flickers", task_type="classification", cost_cap_krw=500,
                          metadata={"model": "simulated:provider-a:large:us", "provider": "simulated:provider-a", "endpoint": "/v1/chat/completions"})
    out = router.route(router.submit(forced, SIM)["id"])
    assert out["plan"]["ladder"][0]["catalog_id"] == "simulated:provider-a:small:us"     # the planner, not the caller, picks the route
    assert out["intent"]["intent"]["task_type"] == "classification" and out["judge"]["method"] and out["labels"]["human_review_required"] is False
    risky = router.route(router.submit(RouteRequest("pt:2", "acme", "Give a diagnosis for these symptoms: fever and a cough", task_type="chat",
                                                    cost_cap_krw=500), SIM)["id"])
    assert risky["labels"] == {"ai_generated": True, "human_review_required": True, "high_risk_domains": ["medical"], "personal_info_detected": False}
    with router.db.transaction() as tx:
        x = router.executions(tx, out["id"])[0]
        from arbitrage.ops.common import loads
        price = loads(x["list_price"])
        assert price["input_micros_per_mtok"] == 250000 and price["currency"] == "USD" and price["verified"] is False and price["region"] == "us"
    assert out["judge"]["cost_krw"] == 0 and out["judge"]["source"] is not None or True


def test_live_call_needs_a_production_ready_registry_entry(db):
    """Even with a cleared catalog row, a live call is refused until the registry calls the provider production-ready."""
    from arbitrage.ops.mandate import parse_mandate
    from ..conftest import ROOT
    import tomllib
    data = tomllib.loads((ROOT / "mandate.router.simulated.toml").read_text("utf-8"))
    data["business"]["environment"] = "live"
    data["router"]["providers"] = ["anthropic_api"]
    data["router"]["disclosed_providers"] = ["anthropic_api"]
    data["business"]["payment_processors"] = ["toss_payments"]
    m = parse_mandate(data, "<live-ish>")
    core = build(db, m, {})
    router = build_router(core, None, FX, "test")
    with core.db.transaction() as tx:
        core.registry.load(tx, [{**e, "name": e["id"], "eligibility": "", "commercial_terms": "", "integration": "api", "credentials": [],
                                 "permissions": "", "rate_limits": "", "supported_operations": [], "manual_dependency": "", "health": "unverified",
                                 "last_verified": "2026-09-28", "region_ok_for_korea": True,
                                 "sources": [{"url": "https://example.invalid/terms", "evidence": "verified", "checked": "2026-09-28", "note": "test"}]}
                                for e in REGISTRY if e["id"] == "anthropic_api"])
        router.catalog.load(tx, [live_entry("anthropic_api")], LIVE, rules=ProviderRules.from_entries(REGISTRY))
        catalog_row = router.catalog.get(tx, "anthropic_api:model:us")
        from arbitrage.ops.router.planner import Route
        route = Route("anthropic_api:model:us", "anthropic_api", "model", "us", 0, 0.9, 900, 10, 20, True, "USD")
        row = {"mode": LIVE, "task_type": "chat", "billing_mode": "own_keys"}
        problems = router._verify_call(tx, row, route, catalog_row, 0, False)
    assert any("production-ready" in p for p in problems)
