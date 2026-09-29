"""Layer 5: the global model marketplace, a table of compliant models with price, latency, context window,
capabilities, availability and historical quality.

Every price row carries evidence {source, url, date, verified}: a price nobody fetched from the provider's own
page with a date is `verified = false` and the planner labels every route built on it.  Quality per task type is
seeded from the entry and then learned from judge verdicts (exponential moving average), so the catalog is where
Layer 10's route learning lands.  Providers are registry ids (the platform-eligibility work owns the registry and
the GO / NO-GO per provider); simulated entries are named `simulated:<name>` and never production-ready.
"""

from __future__ import annotations

import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..audit import AuditTrail
from ..common import LIVE, SIMULATED, canonical_json, loads, now_iso
from ..db import Database, Tx
from ..errors import NotConfigured, OpsError
from ..mandate import TASK_TYPES
from .providers import ProviderRules

REQUIRED = ("id", "provider", "model", "region", "task_types", "context_window", "input_micros_per_mtok",
            "output_micros_per_mtok", "currency", "latency_ms", "quality", "terms_permit", "evidence",
            "customer_countries", "data_residency")
PRC_RESIDENCY = "cn"          # a PRC-hosted endpoint: gated on a personal-information classifier and the tenant's opt-in
EVIDENCE_FIELDS = ("source", "url", "date")
QUALITY_ALPHA = 0.2          # weight of the newest verdict in the moving average
DEFAULT_PATH = Path("integrations/model_catalog.toml")


class ModelCatalog:
    def __init__(self, db: Database, audit: AuditTrail):
        self.db = db
        self.audit = audit

    # -- loading (the refresh path) ------------------------------------------------------------------------

    def load_file(self, tx: Tx, path: str | Path, mode: str, actor: str = "system", rules: ProviderRules | None = None) -> list[str]:
        data = tomllib.loads(Path(path).read_text("utf-8"))
        if data.get("schema_version") != 1:
            raise OpsError(f"{path}: expected schema_version 1, got {data.get('schema_version')!r}")
        return self.load(tx, data.get("models", []), mode, actor, rules)

    def load(self, tx: Tx, entries: list[dict[str, Any]], mode: str, actor: str = "system",
             rules: ProviderRules | None = None) -> list[str]:
        """Upsert price and capability facts. Learned quality is kept unless the entry's quality is newer evidence.
        A live catalog needs the registry's provider rules: a row whose provider the registry does not clear is refused."""
        if mode == LIVE and rules is None and entries:
            raise NotConfigured("a live catalog needs the integration registry's provider rules (ProviderRules.from_file)")
        ids = []
        for e in entries:
            missing = [f for f in REQUIRED if f not in e]
            if missing:
                raise OpsError(f"catalog entry {e.get('id')!r}: missing {', '.join(missing)}")
            if e["id"] != f"{e['provider']}:{e['model']}:{e['region']}":
                raise OpsError(f"catalog entry {e['id']}: id must be provider:model:region")
            if mode == SIMULATED and not e["provider"].startswith("simulated:"):
                raise OpsError(f"catalog entry {e['id']}: a simulated catalog lists only simulated: providers")
            if mode == LIVE and e["provider"].startswith("simulated:"):
                raise OpsError(f"catalog entry {e['id']}: a live catalog cannot list a simulated provider")
            if mode == LIVE and rules is not None:
                problems = rules.problems(e["provider"])
                if problems:
                    raise OpsError(f"catalog entry {e['id']}: " + "; ".join(problems))
            countries = e["customer_countries"]
            if not isinstance(countries, list) or not countries or not all(isinstance(c, str) and c.strip() for c in countries):
                raise OpsError(f"catalog entry {e['id']}: customer_countries lists the countries whose end users the provider supports; "
                               "an empty list routes nobody")
            if "*" in countries:
                raise OpsError(f"catalog entry {e['id']}: customer_countries names countries, never a wildcard")
            if not isinstance(e["data_residency"], str) or not e["data_residency"].strip():
                raise OpsError(f"catalog entry {e['id']}: data_residency names where the endpoint is hosted (e.g. global, us, kr, cn)")
            if not e["task_types"] or not set(e["task_types"]) <= set(TASK_TYPES):
                raise OpsError(f"catalog entry {e['id']}: task_types must be from {TASK_TYPES}")
            for f in ("context_window", "input_micros_per_mtok", "output_micros_per_mtok", "latency_ms"):
                if isinstance(e[f], bool) or not isinstance(e[f], int) or e[f] < 0:
                    raise OpsError(f"catalog entry {e['id']}: {f} must be a non-negative integer")
            quality = e["quality"]
            if not isinstance(quality, dict) or not all(k in TASK_TYPES and 0 <= float(v) <= 1 for k, v in quality.items()):
                raise OpsError(f"catalog entry {e['id']}: quality is {{task_type: 0..1}}")
            ev = e["evidence"]
            if not isinstance(ev, dict) or not all(ev.get(f) for f in EVIDENCE_FIELDS):
                raise OpsError(f"catalog entry {e['id']}: evidence needs {EVIDENCE_FIELDS}; label a placeholder price as unverified")
            verified = bool(ev.get("verified", False))
            if verified and mode == SIMULATED:
                raise OpsError(f"catalog entry {e['id']}: a simulated price is never verified")
            evidence = {"source": str(ev["source"]), "url": str(ev["url"]), "date": str(ev["date"]), "verified": verified,
                        "note": str(ev.get("note", ""))}
            before = tx.fetchone("SELECT * FROM model_catalog WHERE id = ?", (e["id"],))
            fields = {
                "provider": e["provider"], "model": e["model"], "region": e["region"], "tier": int(e.get("tier", 0)),
                "task_types": canonical_json(sorted(e["task_types"])), "context_window": e["context_window"],
                "input_micros_per_mtok": e["input_micros_per_mtok"], "output_micros_per_mtok": e["output_micros_per_mtok"],
                "currency": str(e["currency"]).upper(), "latency_ms": e["latency_ms"], "available": int(bool(e.get("available", True))),
                "terms_permit": int(bool(e["terms_permit"])), "evidence": canonical_json(evidence), "updated_at": now_iso(), "mode": mode,
                "customer_countries": canonical_json(sorted(c.strip().lower() for c in countries)),
                "data_residency": e["data_residency"].strip().lower(), "free_tier": int(bool(e.get("free_tier", False))),
            }
            if before is None:
                fields["quality"] = canonical_json({k: float(v) for k, v in quality.items()})
                fields["quality_samples"] = canonical_json({k: 0 for k in quality})
                tx.insert("model_catalog", {"id": e["id"], **fields})
            else:
                learned = loads(before["quality"])
                samples = loads(before["quality_samples"])
                for k, v in quality.items():
                    if int(samples.get(k, 0)) == 0:     # nothing learned yet: the entry's seed stands
                        learned[k] = float(v)
                        samples.setdefault(k, 0)
                fields["quality"], fields["quality_samples"] = canonical_json(learned), canonical_json(samples)
                tx.update("model_catalog", "id", e["id"], fields)
            self.audit.record(tx, actor, "catalog_loaded", "model_catalog", e["id"], before=before, after=fields)
            ids.append(e["id"])
        return ids

    # -- reading -------------------------------------------------------------------------------------------

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        out["task_types"] = loads(row["task_types"], [])
        out["customer_countries"] = loads(row["customer_countries"], [])
        out["free_tier"] = bool(row["free_tier"])
        out["quality"] = loads(row["quality"])
        out["quality_samples"] = loads(row["quality_samples"])
        out["evidence"] = loads(row["evidence"])
        out["available"] = bool(row["available"])
        out["terms_permit"] = bool(row["terms_permit"])
        out["price_verified"] = bool(out["evidence"].get("verified"))
        return out

    def get(self, tx: Tx, catalog_id: str) -> dict | None:
        row = tx.fetchone("SELECT * FROM model_catalog WHERE id = ?", (catalog_id,))
        return self._decode(row) if row else None

    def list(self, tx: Tx, mode: str, task_type: str | None = None, available_only: bool = False) -> list[dict]:
        rows = [self._decode(r) for r in tx.fetchall("SELECT * FROM model_catalog WHERE mode = ? ORDER BY tier, id", (mode,))]
        if task_type:
            rows = [r for r in rows if task_type in r["task_types"]]
        if available_only:
            rows = [r for r in rows if r["available"]]
        return rows

    # -- runtime facts -------------------------------------------------------------------------------------

    def record_quality(self, tx: Tx, catalog_id: str, task_type: str, score: float, actor: str = "judge") -> float:
        """Fold one judge verdict into the route's quality for that task type (Layer 10 learning)."""
        row = self.get(tx, catalog_id)
        if row is None:
            raise OpsError(f"unknown catalog entry {catalog_id}")
        if not 0 <= score <= 1:
            raise OpsError("quality score must be between 0 and 1")
        quality, samples = row["quality"], row["quality_samples"]
        n = int(samples.get(task_type, 0))
        old = quality.get(task_type)
        new = float(score) if old is None or n == 0 else (1 - QUALITY_ALPHA) * float(old) + QUALITY_ALPHA * float(score)
        quality[task_type], samples[task_type] = round(new, 4), n + 1
        tx.update("model_catalog", "id", catalog_id, {"quality": canonical_json(quality), "quality_samples": canonical_json(samples),
                                                       "updated_at": now_iso()})
        self.audit.record(tx, actor, "quality_learned", "model_catalog", catalog_id,
                          before={"quality": old, "samples": n}, after={"quality": quality[task_type], "samples": n + 1, "score": score})
        return quality[task_type]

    def set_availability(self, tx: Tx, catalog_id: str, available: bool, actor: str = "system") -> None:
        if not tx.update("model_catalog", "id", catalog_id, {"available": int(available), "updated_at": now_iso()}):
            raise OpsError(f"unknown catalog entry {catalog_id}")
        self.audit.record(tx, actor, "catalog_availability", "model_catalog", catalog_id, after={"available": available})

    def stale(self, tx: Tx, mode: str, max_age_days: int, today: date | None = None) -> list[dict]:
        """Entries whose price evidence is older than `max_age_days`, or carries no parseable date."""
        today = today or date.today()
        out = []
        for row in self.list(tx, mode):
            try:
                seen = date.fromisoformat(str(row["evidence"].get("date", ""))[:10])
            except ValueError:
                out.append({"id": row["id"], "reason": "evidence date unreadable"})
                continue
            if today - seen > timedelta(days=max_age_days):
                out.append({"id": row["id"], "reason": f"price evidence from {seen.isoformat()} is older than {max_age_days} days"})
        return out


def cost_mkrw(tokens_in: int, tokens_out: int, row: dict, fx_rate: float) -> int:
    """Provider cost in thousandths of a won, rounded up: fine enough to rank routes whose whole-won costs tie."""
    micros = tokens_in * int(row["input_micros_per_mtok"]) + tokens_out * int(row["output_micros_per_mtok"])
    mkrw = micros * float(fx_rate) / 1e9
    return int(mkrw) + (1 if mkrw > int(mkrw) else 0)


def cost_krw(tokens_in: int, tokens_out: int, row: dict, fx_rate: float) -> int:
    """Provider cost in whole KRW, rounded up: never a cost that understates what the reservation must cover."""
    mkrw = cost_mkrw(tokens_in, tokens_out, row, fx_rate)
    return -(-mkrw // 1000)
