"""The registry loader reads integrations/registry.toml exactly as the platform-eligibility work defines it."""

from pathlib import Path

import pytest

from arbitrage.ops.audit import AuditTrail
from arbitrage.ops.errors import OpsError
from arbitrage.ops.registry import IntegrationRegistry

from .conftest import ROOT

REGISTRY_FILE = ROOT / "integrations" / "registry.toml"


def entry(**overrides):
    """One entry in the registry.toml schema (shortened text), shaped like aliexpress_supplier."""
    e = {
        "id": "aliexpress_supplier", "name": "AliExpress (buyer account + Dropshipping Center + Open Platform DS API)",
        "roles": ["supplier"], "verdict": "go", "status": "not_connected", "connected": False, "region_ok_for_korea": True,
        "eligibility": "Any buyer account; dropshipping officially supported.", "commercial_terms": "No resale restriction; API only.",
        "integration": "api", "credentials": ["ALIEXPRESS_DS_APP_KEY", "ALIEXPRESS_DS_APP_SECRET"],
        "permissions": "AE-Dropshipper API group", "rate_limits": "No daily quota documented",
        "supported_operations": ["product detail and buyer price", "create order for a third-party address"],
        "manual_dependency": "DS Center activation; PayPal binding for API payment.", "health": "unverified",
        "last_verified": "2026-09-27",
        "sources": [{"url": "https://openservice.aliexpress.com/doc/doc.htm#/?docId=1646", "evidence": "verified",
                     "checked": "2026-09-27", "note": "Beginner's Guide for Dropshipping"}],
    }
    e.update(overrides)
    return e


@pytest.fixture
def registry(db):
    return IntegrationRegistry(db, AuditTrail(db))


def test_loads_the_schema_and_keeps_runtime_facts_across_reloads(db, registry):
    with db.transaction() as tx:
        assert registry.load(tx, [entry()]) == ["aliexpress_supplier"]
        row = registry.get(tx, "aliexpress_supplier")
        assert row["roles"] == ["supplier"] and row["credentials"] == ["ALIEXPRESS_DS_APP_KEY", "ALIEXPRESS_DS_APP_SECRET"]
        assert row["connected"] is False and row["production_ready"] is False and row["mode"] == "live"
        registry.set_health(tx, "aliexpress_supplier", "healthy")
        registry.mark_verified(tx, "aliexpress_supplier", "ds.order.create", "real-8812", "owner")
        registry.load(tx, [entry(manual_dependency="updated text")])  # a reload of the file
        row = registry.get(tx, "aliexpress_supplier")
        assert row["manual_dependency"] == "updated text"
        assert row["health"] == "unverified"  # the file's health wins on reload; a check sets it again
        assert row["verified_operation"] == "ds.order.create" and row["verification_reference"] == "real-8812"
        assert row["production_ready"] is False  # file still not connected


@pytest.mark.parametrize("bad, match", [
    ({"roles": ["marketplace"]}, "roles"),
    ({"credentials": ["ALIEXPRESS_DS_APP_KEY=abc"]}, "names only"),
    ({"credentials": ["lowercase"]}, "names only"),
    ({"verdict": "unknown"}, "must say why"),
    ({"sources": []}, "cites no source"),
    ({"status": "live", "sources": [{"url": "https://x", "evidence": "reported", "checked": "2026-09-27", "note": "press"}]}, "without a verified source"),
    ({"health": "fine"}, "bad verdict, status or health"),
])
def test_bad_entries_are_refused(db, registry, bad, match):
    e = entry(**bad)
    with db.transaction() as tx:
        with pytest.raises(OpsError, match=match):
            registry.load(tx, [e])


def test_missing_fields_are_named(db, registry):
    e = entry()
    del e["manual_dependency"]
    del e["last_verified"]
    with db.transaction() as tx:
        with pytest.raises(OpsError, match="missing manual_dependency, last_verified"):
            registry.load(tx, [e])


def test_simulated_entries_are_never_production_ready(db, registry):
    with db.transaction() as tx:
        registry.register_simulated(tx, ["simulated:aliexpress"])
        registry.register_simulated(tx, ["simulated:aliexpress"])  # idempotent
        row = registry.get(tx, "simulated:aliexpress")
        assert row["mode"] == "simulated" and not row["production_ready"]
        with pytest.raises(OpsError, match="never production-ready"):
            registry.mark_verified(tx, "simulated:aliexpress", "place_order", "SIM-1", "owner")
        with pytest.raises(OpsError, match="simulated:"):
            registry.register_simulated(tx, ["aliexpress"])


@pytest.mark.skipif(not REGISTRY_FILE.exists(), reason="integrations/registry.toml lands with PR #4")
def test_loads_the_real_registry_file(db, registry):
    with db.transaction() as tx:
        ids = registry.load_file(tx, REGISTRY_FILE)
        assert "aliexpress_supplier" in ids
        assert not any(r["production_ready"] for r in registry.list(tx))
