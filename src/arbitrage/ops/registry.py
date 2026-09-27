"""Integration registry: every platform we touch, its role, what it may do, how healthy it is, and whether a real
operation has been verified.  `production_ready` is set only by `mark_verified` with the reference of that real
operation; a file load can never set it.  Credentials are named by environment variable, never stored.

The platform-eligibility work owns `integrations/registry.toml` and its schema; this loader is provisional and
will be aligned to that schema when it is published.  It currently reads:

    [[integrations]]
    name = "aliexpress"                # unique
    role = "supplier"                  # supplier | sales_channel | affiliate_channel | logistics | research | payment
    mode = "live"                      # live | simulated
    credentials_ref = "ALIEXPRESS_APP_KEY"
    permissions = ["search", "order"]
    rate_limits = { per_minute = 60 }
    supported_operations = ["search_products", "place_order", "track_shipment"]
    manual_dependency = "Ordering is manual until the dropship API is approved"
    notes = "..."
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .audit import AuditTrail
from .common import MODES, canonical_json, loads, now_iso
from .db import Database, Tx
from .errors import OpsError

ROLES = ("supplier", "sales_channel", "affiliate_channel", "logistics", "research", "payment")
HEALTH = ("unknown", "healthy", "degraded", "unhealthy")
FIELDS = ("name", "role", "mode")


class IntegrationRegistry:
    def __init__(self, db: Database, audit: AuditTrail):
        self.db = db
        self.audit = audit

    def load_file(self, tx: Tx, path: str | Path, actor: str = "system") -> list[str]:
        text = Path(path).read_text("utf-8")
        data = json.loads(text) if str(path).endswith(".json") else tomllib.loads(text)
        return self.load(tx, data.get("integrations", []), actor)

    def load(self, tx: Tx, items: list[dict[str, Any]], actor: str = "system") -> list[str]:
        """Upsert descriptive fields. Verification and health are runtime facts and are left alone."""
        names = []
        for item in items:
            for f in FIELDS:
                if not item.get(f):
                    raise OpsError(f"integration entry missing {f!r}: {item}")
            if item["role"] not in ROLES:
                raise OpsError(f"integration {item['name']}: role must be one of {ROLES}")
            if item["mode"] not in MODES:
                raise OpsError(f"integration {item['name']}: mode must be one of {MODES}")
            if item["mode"] == "simulated" and not item["name"].startswith("simulated:"):
                raise OpsError(f"integration {item['name']}: simulated integrations are named 'simulated:<name>'")
            fields = {
                "role": item["role"], "mode": item["mode"], "credentials_ref": item.get("credentials_ref"),
                "permissions": canonical_json(item.get("permissions", [])),
                "rate_limits": canonical_json(item.get("rate_limits", {})),
                "supported_operations": canonical_json(item.get("supported_operations", [])),
                "manual_dependency": item.get("manual_dependency"), "notes": item.get("notes"), "updated_at": now_iso(),
            }
            before = tx.fetchone("SELECT * FROM integrations WHERE name = ?", (item["name"],))
            if before:
                tx.update("integrations", "name", item["name"], fields)
            else:
                tx.insert("integrations", {"name": item["name"], **fields})
            self.audit.record(tx, actor, "integration_loaded", "integrations", item["name"], before=before, after=fields)
            names.append(item["name"])
        return names

    def get(self, tx: Tx, name: str) -> dict | None:
        row = tx.fetchone("SELECT * FROM integrations WHERE name = ?", (name,))
        return self._decode(row) if row else None

    def list(self, tx: Tx, mode: str | None = None) -> list[dict]:
        if mode:
            rows = tx.fetchall("SELECT * FROM integrations WHERE mode = ? ORDER BY name", (mode,))
        else:
            rows = tx.fetchall("SELECT * FROM integrations ORDER BY name")
        return [self._decode(r) for r in rows]

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for key in ("permissions", "supported_operations"):
            out[key] = loads(row[key], [])
        out["rate_limits"] = loads(row["rate_limits"], {})
        out["production_ready"] = bool(row["production_ready"])
        return out

    def set_health(self, tx: Tx, name: str, health: str, actor: str = "system") -> None:
        if health not in HEALTH:
            raise OpsError(f"health must be one of {HEALTH}")
        if not tx.update("integrations", "name", name, {"health": health, "health_checked_at": now_iso(), "updated_at": now_iso()}):
            raise OpsError(f"unknown integration {name}")
        self.audit.record(tx, actor, "integration_health", "integrations", name, after={"health": health})

    def mark_verified(self, tx: Tx, name: str, operation: str, reference: str, actor: str) -> None:
        """A real operation succeeded on this integration: it may now serve live actions."""
        row = self.get(tx, name)
        if row is None:
            raise OpsError(f"unknown integration {name}")
        if row["mode"] != "live":
            raise OpsError(f"{name} is a simulated integration; simulated adapters are never production-ready")
        if not reference:
            raise OpsError("verification needs the external reference of the real operation")
        tx.update("integrations", "name", name, {
            "production_ready": 1, "verified_operation": operation, "verified_at": now_iso(),
            "verification_reference": reference, "updated_at": now_iso()})
        self.audit.record(tx, actor, "integration_verified", "integrations", name,
                          after={"operation": operation, "reference": reference})

    def record_reconciliation(self, tx: Tx, name: str, kind: str, status: str, our_total: int, their_total: int,
                              detail: dict | None, mode: str, actor: str = "system") -> str:
        from .common import new_id

        if status not in ("matched", "mismatch", "failed"):
            raise OpsError("reconciliation status must be matched, mismatch or failed")
        row = {"id": new_id("rec"), "integration": name, "kind": kind, "status": status, "started_at": now_iso(),
               "finished_at": now_iso(), "our_total": our_total, "their_total": their_total,
               "difference": their_total - our_total, "detail": canonical_json(detail or {}), "mode": mode}
        tx.insert("reconciliations", row)
        if status == "matched":
            tx.update("integrations", "name", name, {"last_reconciled_at": now_iso(), "updated_at": now_iso()})
        self.audit.record(tx, actor, "reconciliation", "reconciliations", row["id"], after=row)
        return row["id"]
