"""The integration registry (integrations/registry.toml) is reference data other tools read.

Every entry must carry the same fields, cite its sources, and say plainly whether it is connected.
Nothing may claim to be connected until a real operation against that platform has been verified.
"""

import datetime as dt
import tomllib
from pathlib import Path

import pytest

REGISTRY = Path(__file__).parent.parent / "integrations" / "registry.toml"

ROLES = {"supplier", "sales_channel", "affiliate_channel", "logistics", "research_source", "payment", "infrastructure"}
STATUSES = {"not_connected", "credentials_pending", "sandbox", "live"}
VERDICTS = {"go", "conditional", "no_go", "unknown"}
EVIDENCE = {"verified", "reported", "inferred", "unknown"}
REQUIRED = {
    "id", "name", "roles", "verdict", "status", "connected", "region_ok_for_korea",
    "eligibility", "commercial_terms", "integration", "credentials", "permissions",
    "rate_limits", "supported_operations", "manual_dependency", "health", "last_verified", "sources",
}


@pytest.fixture(scope="module")
def registry():
    return tomllib.loads(REGISTRY.read_text("utf-8"))


def test_registry_header(registry):
    assert registry["schema_version"] == 1
    dt.date.fromisoformat(registry["generated_on"])
    assert registry["integrations"], "registry has no entries"


def test_every_entry_is_complete_and_not_live(registry):
    ids = set()
    for entry in registry["integrations"]:
        missing = REQUIRED - entry.keys()
        assert not missing, f"{entry.get('id')}: missing {sorted(missing)}"
        assert entry["id"] not in ids, f"duplicate id {entry['id']}"
        ids.add(entry["id"])
        assert entry["roles"] and set(entry["roles"]) <= ROLES, entry["id"]
        assert entry["verdict"] in VERDICTS, entry["id"]
        assert entry["status"] in STATUSES, entry["id"]
        # Connected only when a real operation was verified; the registry starts with none.
        assert entry["connected"] is False, f"{entry['id']} claims to be connected"
        assert entry["status"] != "live", f"{entry['id']} claims to be live"
        assert entry["health"] == "unverified", entry["id"]
        dt.date.fromisoformat(entry["last_verified"])
        assert isinstance(entry["credentials"], list), entry["id"]
        for cred in entry["credentials"]:
            assert cred.isupper() and "=" not in cred, f"{entry['id']}: credentials are names only, got {cred!r}"
        assert entry["sources"], f"{entry['id']} cites no source"
        for source in entry["sources"]:
            assert source["url"].startswith("https://"), entry["id"]
            assert source["evidence"] in EVIDENCE, entry["id"]
            dt.date.fromisoformat(source["checked"])


def test_unknown_verdicts_say_why(registry):
    for entry in registry["integrations"]:
        if entry["verdict"] == "unknown":
            assert entry.get("unknown_because"), f"{entry['id']} is unknown without a reason"
