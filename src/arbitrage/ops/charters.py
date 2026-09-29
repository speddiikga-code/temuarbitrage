"""Agent charters as data: task, inputs, outputs, tools, permissions, deadline, credit allowance, success metric,
termination condition, plus the limits the orchestrator enforces.  Loaded from the bundled charters.toml."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path

from .common import canonical_json, now_iso
from .db import Tx
from .errors import OrchestrationError

REQUIRED_ROLES = (
    "market_research", "platform_eligibility", "product_discovery", "unit_economics", "procurement",
    "catalog_localization", "advertising_experiments", "order_fulfillment", "customer_support",
    "treasury_reconciliation", "performance_analytics", "engineering_improvement", "quality_evaluation",
)
CHARTER_FIELDS = ("task", "inputs", "outputs", "tools", "permissions", "deadline_minutes", "credit_allowance",
                  "success_metric", "termination_condition")
LIMIT_FIELDS = ("max_concurrency", "max_retries", "max_delegation_depth")
EVALUATOR = "quality_evaluation"


@dataclass(frozen=True)
class Charter:
    role: str
    task: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    tools: tuple[str, ...]
    permissions: tuple[str, ...]
    deadline_minutes: int
    credit_allowance: int
    success_metric: str
    termination_condition: str
    max_concurrency: int
    max_retries: int
    max_delegation_depth: int

    def as_dict(self) -> dict:
        return asdict(self)


def parse_charters(data: dict) -> dict[str, Charter]:
    defaults = data.get("defaults", {})
    charters: dict[str, Charter] = {}
    for raw in data.get("charters", []):
        role = raw.get("role")
        if not role:
            raise OrchestrationError("charter without a role")
        if role in charters:
            raise OrchestrationError(f"duplicate charter {role}")
        merged = {**defaults, **raw}
        for f in CHARTER_FIELDS + LIMIT_FIELDS:
            if f not in merged or merged[f] in ("", [], None):
                raise OrchestrationError(f"charter {role}: missing {f}")
        for f in ("deadline_minutes", "credit_allowance") + LIMIT_FIELDS:
            if not isinstance(merged[f], int) or merged[f] <= 0:
                raise OrchestrationError(f"charter {role}: {f} must be a positive integer")
        perms = tuple(merged["permissions"])
        if any(p.startswith("execute:") for p in perms):
            raise OrchestrationError(f"charter {role}: agents never hold execute permissions; services execute")
        if role == EVALUATOR and any(p.startswith("propose:") for p in perms):
            raise OrchestrationError("the quality evaluator may not propose changes it would then judge")
        charters[role] = Charter(role, merged["task"], tuple(merged["inputs"]), tuple(merged["outputs"]), tuple(merged["tools"]),
                                 perms, merged["deadline_minutes"], merged["credit_allowance"], merged["success_metric"],
                                 merged["termination_condition"], merged["max_concurrency"], merged["max_retries"],
                                 merged["max_delegation_depth"])
    missing = [r for r in REQUIRED_ROLES if r not in charters]
    if missing:
        raise OrchestrationError(f"charters missing for: {', '.join(missing)}")
    return charters


def load_charters(path: str | Path | None = None) -> dict[str, Charter]:
    if path is None:
        text = resources.files("arbitrage.ops").joinpath("charters.toml").read_text("utf-8")
    else:
        text = Path(path).read_text("utf-8")
    return parse_charters(tomllib.loads(text))


def store_charters(tx: Tx, charters: dict[str, Charter], version: int = 1) -> None:
    for role, c in charters.items():
        tx.execute("DELETE FROM agent_charters WHERE role = ?", (role,))
        tx.insert("agent_charters", {"role": role, "version": version, "content": canonical_json(c.as_dict()), "loaded_at": now_iso()})
