"""Router adapters: the only code that talks to a model provider or a quality judge.

`SimulatedProvider` returns scripted text and token counts and never calls a model; `SimulatedJudge` returns scripted
scores.  Both produce confirmations named `simulated:<name>` with references like `SIM-REQ-3`, so the whole routing
path can run, fail and reconcile in tests.  There is no live provider adapter: `LiveAdapterUnavailable` (from the
core) refuses and names the manual dependency, so nothing can pretend a real provider answered or charged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..adapters import CONFIRMED, AdapterResult, SimulatedAdapter

PROVIDER_USAGE = "provider_usage"


def _default_output(model: str, prompt: str, max_output_tokens: int) -> str:
    head = " ".join(prompt.split())[:120]
    return f"[{model}] answer to: {head}"


class SimulatedProvider(SimulatedAdapter):
    """A model provider that answers with canned text. `script_output(text, output_tokens)` queues the next answer."""

    role = "provider"

    def __init__(self, name: str):
        super().__init__(name)
        self._outputs: list[tuple[str, int | None]] = []
        self.credits: list[dict] = []

    def script_output(self, text: str, output_tokens: int | None = None) -> None:
        self._outputs.append((text, output_tokens))

    def complete(self, action_id: str, model: str, prompt: str, max_output_tokens: int, input_tokens: int) -> AdapterResult:
        """One call. The result's payload carries the usage record a real provider returns with its response."""
        text, out_tokens = self._outputs.pop(0) if self._outputs else (_default_output(model, prompt, max_output_tokens), None)
        if out_tokens is None:
            out_tokens = min(max_output_tokens, max(1, len(text) // 4))
        return self._result(PROVIDER_USAGE, "REQ", None, "KRW", action_id=action_id, model=model, input_tokens=input_tokens,
                            output_tokens=int(out_tokens), output=text, latency_ms=350)

    def purchase_credits(self, action_id: str, amount_krw: int) -> AdapterResult:
        """Buy prepaid credits at the provider (a spend action; its receipt is the confirmation)."""
        result = self._result("payment_receipt", "PAY", amount_krw, "KRW", action_id=action_id, credits=True)
        if result.ok:
            self.credits.append({"reference": result.reference, "action_id": action_id, "amount_krw": amount_krw})
        return result

    def lookup(self, action_id: str) -> AdapterResult:
        """Reconciliation: did the provider record a call for this transaction id, and what did it use?"""
        self.calls.append(("lookup", {"action_id": action_id}))
        for ref, rec in self.orders.items():
            if rec.get("action_id") == action_id and rec["kind"] == PROVIDER_USAGE:
                payload = {k: v for k, v in rec.items() if k not in ("kind", "amount", "currency", "ambiguous")}
                return AdapterResult(CONFIRMED, PROVIDER_USAGE, ref, self.name, self.mode, None, "KRW", {**payload, "reconciled": True})
        return AdapterResult("failed", PROVIDER_USAGE, None, self.name, self.mode, error="provider has no record of this call")

    def usage_report(self) -> list[dict]:
        """What the provider says it charged: one row per call it recorded, for the treasury reconciliation."""
        return [{"reference": ref, "action_id": rec.get("action_id"), "input_tokens": rec.get("input_tokens"),
                 "output_tokens": rec.get("output_tokens")} for ref, rec in self.orders.items() if rec["kind"] == PROVIDER_USAGE]


@dataclass(frozen=True)
class Verdict:
    score: float                    # 0..1
    passed: bool
    method: str                     # e.g. "structural+simulated"
    reasons: tuple[str, ...] = ()
    cost_krw: int = 0               # a model-based judge costs tokens; the simulated one costs nothing
    source: str = "simulated:judge"
    reference: str | None = None


class SimulatedJudge:
    """Scores outputs from a script (default 0.9). `script(*scores)` queues the next verdicts."""

    def __init__(self, name: str = "simulated:judge", default: float = 0.9):
        if not name.startswith("simulated:"):
            raise ValueError("simulated judges are named 'simulated:<name>'")
        self.name = name
        self.mode = "simulated"
        self.default = default
        self._scores: list[float] = []
        self.calls: list[dict] = []
        self._n = 0

    def script(self, *scores: float) -> None:
        self._scores.extend(scores)

    def score(self, task_type: str, prompt: str, output: str) -> tuple[float, str]:
        self._n += 1
        self.calls.append({"task_type": task_type, "output": output[:80]})
        value = self._scores.pop(0) if self._scores else self.default
        return float(value), f"SIM-JUDGE-{self._n}"


@dataclass
class RouterAdapters:
    providers: dict[str, SimulatedProvider] = field(default_factory=dict)
    judge: SimulatedJudge | None = None


def simulated_router_adapters() -> dict:
    """Adapters the simulated router path uses; the core registers every `simulated:` name so the registry lists them."""
    from ..adapters import SimulatedProcessor

    return {"simulated:provider-a": SimulatedProvider("simulated:provider-a"),
            "simulated:provider-b": SimulatedProvider("simulated:provider-b"),
            "simulated:billing": SimulatedProcessor("simulated:billing")}
