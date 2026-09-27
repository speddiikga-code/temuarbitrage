"""Integration registry: the platforms this business touches, loaded from `integrations/registry.toml`.

The file and its schema belong to the platform-eligibility work (schema_version 1: an array of [[integrations]]
tables with id, name, roles, verdict, status, connected, region_ok_for_korea, eligibility, commercial_terms,
integration, credentials as environment-variable names, permissions, rate_limits, supported_operations,
manual_dependency, health, last_verified, sources).  This module loads it into a table and adds the runtime facts
the core learns: a verified real operation, health checks, reconciliations.

Production-ready means all of: the file says `status = "live"` and `connected = true` (changed only in a PR that
names the verified operation), and the core holds its own verification record for that operation.  A file can
therefore not declare an integration live on its own, and the core cannot use one the file still calls not
connected.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .audit import AuditTrail
from .common import LIVE, SIMULATED, canonical_json, loads, new_id, now_iso
from .db import Database, Tx
from .errors import OpsError

ROLES = ("supplier", "sales_channel", "affiliate_channel", "logistics", "research_source", "payment", "infrastructure")
STATUSES = ("not_connected", "credentials_pending", "sandbox", "live")
VERDICTS = ("go", "conditional", "no_go", "unknown")
HEALTH = ("unverified", "healthy", "degraded", "unhealthy")
REQUIRED = ("id", "name", "roles", "verdict", "status", "connected", "region_ok_for_korea", "eligibility", "commercial_terms",
            "integration", "credentials", "permissions", "rate_limits", "supported_operations", "manual_dependency", "health",
            "last_verified", "sources")
DEFAULT_PATH = Path("integrations/registry.toml")


class IntegrationRegistry:
    def __init__(self, db: Database, audit: AuditTrail):
        self.db = db
        self.audit = audit

    # -- loading ---------------------------------------------------------------------------------------

    def load_file(self, tx: Tx, path: str | Path = DEFAULT_PATH, actor: str = "system") -> list[str]:
        text = Path(path).read_text("utf-8")
        data = json.loads(text) if str(path).endswith(".json") else tomllib.loads(text)
        if data.get("schema_version") != 1:
            raise OpsError(f"{path}: expected schema_version 1, got {data.get('schema_version')!r}")
        return self.load(tx, data.get("integrations", []), actor)

    def load(self, tx: Tx, entries: list[dict[str, Any]], actor: str = "system") -> list[str]:
        """Upsert the file's fields. Runtime facts (verification, health checks, reconciliations) are kept."""
        ids = []
        for e in entries:
            missing = [f for f in REQUIRED if f not in e]
            if missing:
                raise OpsError(f"integration {e.get('id')!r}: missing {', '.join(missing)}")
            if not e["roles"] or not set(e["roles"]) <= set(ROLES):
                raise OpsError(f"integration {e['id']}: roles must be from {ROLES}")
            if e["verdict"] not in VERDICTS or e["status"] not in STATUSES or e["health"] not in HEALTH:
                raise OpsError(f"integration {e['id']}: bad verdict, status or health")
            if e["verdict"] == "unknown" and not e.get("unknown_because"):
                raise OpsError(f"integration {e['id']}: an unknown verdict must say why")
            for cred in e["credentials"]:
                if not isinstance(cred, str) or not cred.isupper() or "=" in cred:
                    raise OpsError(f"integration {e['id']}: credentials are environment variable names only")
            if not e["sources"]:
                raise OpsError(f"integration {e['id']}: cites no source")
            if e["connected"] or e["status"] == "live":
                if not any("verified" in str(s.get("note", "")).lower() or s.get("evidence") == "verified" for s in e["sources"]):
                    raise OpsError(f"integration {e['id']}: connected or live without a verified source")
            fields = {
                "name": e["name"], "mode": LIVE, "roles": canonical_json(e["roles"]), "verdict": e["verdict"], "status": e["status"],
                "connected": bool(e["connected"]), "region_ok_for_korea": bool(e["region_ok_for_korea"]),
                "eligibility": e["eligibility"], "commercial_terms": e["commercial_terms"], "integration": e["integration"],
                "credentials": canonical_json(e["credentials"]), "permissions": str(e["permissions"]),
                "rate_limits": str(e["rate_limits"]), "supported_operations": canonical_json(e["supported_operations"]),
                "manual_dependency": e["manual_dependency"], "health": e["health"], "last_verified": str(e["last_verified"]),
                "unknown_because": e.get("unknown_because"), "sources": canonical_json(e["sources"]), "updated_at": now_iso(),
            }
            before = tx.fetchone("SELECT * FROM integrations WHERE id = ?", (e["id"],))
            if before:
                tx.update("integrations", "id", e["id"], fields)
            else:
                tx.insert("integrations", {"id": e["id"], **fields})
            self.audit.record(tx, actor, "integration_loaded", "integrations", e["id"], before=before, after=fields)
            ids.append(e["id"])
        return ids

    def register_simulated(self, tx: Tx, names: list[str], actor: str = "system") -> None:
        """Entries for simulated adapters, so the registry lists what the simulated path uses. Never production-ready."""
        for name in names:
            if not name.startswith("simulated:"):
                raise OpsError("simulated integrations are named 'simulated:<name>'")
            if tx.fetchone("SELECT id FROM integrations WHERE id = ?", (name,)):
                continue
            tx.insert("integrations", {
                "id": name, "name": f"{name} (simulated adapter, no real platform)", "mode": SIMULATED, "roles": "[]",
                "verdict": "no_go", "status": "not_connected", "connected": 0, "region_ok_for_korea": 0,
                "integration": "simulated", "credentials": "[]", "supported_operations": "[]", "health": "unverified",
                "sources": "[]", "manual_dependency": "none: nothing real happens", "updated_at": now_iso()})

    # -- reading ---------------------------------------------------------------------------------------

    def get(self, tx: Tx, integration_id: str) -> dict | None:
        row = tx.fetchone("SELECT * FROM integrations WHERE id = ?", (integration_id,))
        return self._decode(row) if row else None

    def list(self, tx: Tx, mode: str | None = None) -> list[dict]:
        rows = tx.fetchall("SELECT * FROM integrations WHERE mode = ? ORDER BY id", (mode,)) if mode else \
            tx.fetchall("SELECT * FROM integrations ORDER BY id")
        return [self._decode(r) for r in rows]

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for key in ("roles", "credentials", "supported_operations", "sources"):
            out[key] = loads(row[key], [])
        out["connected"] = bool(row["connected"])
        out["region_ok_for_korea"] = bool(row["region_ok_for_korea"])
        out["production_ready"] = bool(row["mode"] == LIVE and row["status"] == "live" and row["connected"] and row["verified_at"])
        return out

    # -- runtime facts -----------------------------------------------------------------------------------

    def set_health(self, tx: Tx, integration_id: str, health: str, actor: str = "system") -> None:
        if health not in HEALTH:
            raise OpsError(f"health must be one of {HEALTH}")
        if not tx.update("integrations", "id", integration_id, {"health": health, "health_checked_at": now_iso(), "updated_at": now_iso()}):
            raise OpsError(f"unknown integration {integration_id}")
        self.audit.record(tx, actor, "integration_health", "integrations", integration_id, after={"health": health})

    def mark_verified(self, tx: Tx, integration_id: str, operation: str, reference: str, actor: str) -> None:
        """The core saw a real operation succeed. The file still has to say live and connected before live use."""
        row = self.get(tx, integration_id)
        if row is None:
            raise OpsError(f"unknown integration {integration_id}")
        if row["mode"] != LIVE:
            raise OpsError(f"{integration_id} is simulated; simulated adapters are never production-ready")
        if not reference:
            raise OpsError("verification needs the external reference of the real operation")
        tx.update("integrations", "id", integration_id, {"verified_operation": operation, "verified_at": now_iso(),
                                                          "verification_reference": reference, "updated_at": now_iso()})
        self.audit.record(tx, actor, "integration_verified", "integrations", integration_id,
                          after={"operation": operation, "reference": reference})

    def record_reconciliation(self, tx: Tx, integration_id: str, kind: str, status: str, our_total: int, their_total: int,
                              detail: dict | None, mode: str, actor: str = "system") -> str:
        if status not in ("matched", "mismatch", "failed"):
            raise OpsError("reconciliation status must be matched, mismatch or failed")
        row = {"id": new_id("rec"), "integration": integration_id, "kind": kind, "status": status, "started_at": now_iso(),
               "finished_at": now_iso(), "our_total": our_total, "their_total": their_total,
               "difference": their_total - our_total, "detail": canonical_json(detail or {}), "mode": mode}
        tx.insert("reconciliations", row)
        if status == "matched":
            tx.update("integrations", "id", integration_id, {"last_reconciled_at": now_iso(), "updated_at": now_iso()})
        self.audit.record(tx, actor, "reconciliation", "reconciliations", row["id"], after=row)
        return row["id"]
