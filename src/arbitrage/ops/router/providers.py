"""Provider rules read from the integration registry (Layer 5 evidence, Layer 6 gate).

`integrations/registry.toml` belongs to the platform-eligibility and provider-terms work (tasks 10 and 13). The core
loader keeps the schema-1 fields; the provider-terms entries add `service`, `customer_app_allowed`, `resale_prohibited`,
`training_on_inputs`, `data_residency` and `pricing_url`, which the core ignores. This module reads those extra
fields straight from the file for the router's compliance gate and never writes a registry entry of its own.

A live catalog row may name a provider only when its registry entry is an AI inference service, its terms grant
serving the platform's own end users explicitly, and its verdict is not no_go or unknown. Nothing here makes a
provider connected: that stays with the registry's `status = "live"`, `connected = true` and the core's
verification record.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import OpsError
from ..registry import DEFAULT_PATH as REGISTRY_PATH

AI_SERVICES = ("ai_inference", "ai_inference_gateway", "ai_inference_aggregator")
APP_ALLOWED_VALUES = ("explicit", "not_prohibited", "unclear", "prohibited for resale")
PILOT_APP_ALLOWED = ("explicit",)       # widen to not_prohibited only after counsel, per docs/provider_terms.md section 9


@dataclass(frozen=True)
class ProviderEntry:
    id: str
    service: str | None
    verdict: str
    status: str
    connected: bool
    customer_app_allowed: str | None
    resale_prohibited: bool
    region_ok_for_korea: bool
    data_residency: str
    pricing_url: str
    training_on_inputs: str

    @property
    def ai_service(self) -> bool:
        return self.service in AI_SERVICES

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class ProviderRules:
    """The registry's answer to 'may the router send customer work to this provider at all'."""

    def __init__(self, entries: dict[str, ProviderEntry], source: str = "<entries>"):
        self.entries = entries
        self.source = source

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]], source: str = "<entries>") -> "ProviderRules":
        out: dict[str, ProviderEntry] = {}
        for e in entries:
            if "id" not in e:
                raise OpsError(f"{source}: registry entry without an id")
            allowed = e.get("customer_app_allowed")
            if allowed is not None and allowed not in APP_ALLOWED_VALUES:
                raise OpsError(f"{source}: {e['id']}: customer_app_allowed must be one of {APP_ALLOWED_VALUES}")
            out[e["id"]] = ProviderEntry(
                e["id"], e.get("service"), str(e.get("verdict", "unknown")), str(e.get("status", "not_connected")),
                bool(e.get("connected", False)), allowed, bool(e.get("resale_prohibited", True)),
                bool(e.get("region_ok_for_korea", False)), str(e.get("data_residency", "")), str(e.get("pricing_url", "")),
                str(e.get("training_on_inputs", "")))
        return cls(out, source)

    @classmethod
    def from_file(cls, path: str | Path = REGISTRY_PATH) -> "ProviderRules":
        p = Path(path)
        if not p.exists():
            raise OpsError(f"integration registry {p} not found; the live router routes to no provider without it")
        data = tomllib.loads(p.read_text("utf-8"))
        if data.get("schema_version") != 1:
            raise OpsError(f"{p}: expected schema_version 1, got {data.get('schema_version')!r}")
        return cls.from_entries(data.get("integrations", []), str(p))

    def get(self, provider_id: str) -> ProviderEntry | None:
        return self.entries.get(provider_id)

    def problems(self, provider_id: str) -> list[str]:
        """Every reason the registry gives against routing customer work to this provider. Empty means it may be listed."""
        e = self.entries.get(provider_id)
        if e is None:
            return [f"provider {provider_id} is not in the integration registry ({self.source})"]
        out: list[str] = []
        if not e.ai_service:
            out.append(f"registry entry {provider_id} is not an AI inference service (service={e.service!r})")
        if e.customer_app_allowed not in PILOT_APP_ALLOWED:
            out.append(f"registry says customer apps are {e.customer_app_allowed!r} at {provider_id}; only 'explicit' routes in the first pilot")
        if e.verdict in ("no_go", "unknown"):
            out.append(f"registry verdict for {provider_id} is {e.verdict}")
        return out

    def ai_providers(self) -> list[ProviderEntry]:
        return [e for e in self.entries.values() if e.ai_service]
