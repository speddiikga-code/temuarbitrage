"""Layer 6 (cost-aware router) and the planning half of Layer 8 (execution orchestrator).

    route* = argmin cost(R)  subject to  quality(R) >= Q_min,  latency(R) <= L_max,  compliance(R) = true

Compliance is a hard gate, evaluated first and recorded per candidate: the provider must be one the mandate names,
the region one it permits, the model's terms must permit routing customer work through it, the task type must be
one the model and the mandate accept, and the catalog row must be available.  No candidate is ever admitted by
relaxing one of these; a request with no compliant route gets no route and the reasons.

Quality is the catalog's learned score for the task type; a model with no score for the task is not a candidate
(unknown quality never satisfies a threshold).  Cost is estimated from the token estimate and the catalog price
at the request's FX rate; the *cap* cost assumes the full output budget and is what the budget governor reserves.

Three objectives: `economy` (cheapest that meets the threshold), `balanced` (cost x latency factor / quality),
`maximum` (highest quality, then cheapest).  The escalation ladder after the chosen route lists every compliant
route with strictly higher quality, cheapest first, so a failed judge verdict climbs one rung at a time.
Decomposition (Layer 8) applies to long, splittable work: a cheap route preprocesses the context in chunks and
the chosen route receives only the reduced residual.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import OpsError
from .catalog import cost_krw, cost_mkrw
from .intent import Intent

SPLIT_THRESHOLD_TOKENS = 8_000       # context longer than this is worth preprocessing on a cheaper route
CHUNK_TOKENS = 4_000
RESIDUAL_SHARE = 0.25                # share of the context expected to survive preprocessing (estimate)
PREPROCESS_OUTPUT_TOKENS = 400       # per chunk


@dataclass(frozen=True)
class Constraints:
    task_type: str
    quality_min: float
    cost_cap_krw: int
    optimization: str
    fx_rate: float
    fx_origin: str
    max_output_tokens: int
    providers_allowed: tuple[str, ...]
    regions_allowed: tuple[str, ...]
    task_types_allowed: tuple[str, ...]
    quality_floor: float
    latency_max_ms: int | None = None
    platform_request_cap_krw: int | None = None   # mandate cap when the platform pays; None when the customer's key pays
    customer_country: str = ""                       # end users are screened by country against the provider's supported list
    prc_opt_in: bool = False                         # tenant opted in to PRC-hosted endpoints
    disclosed_providers: tuple[str, ...] | None = None   # providers named in the privacy policy; None = not enforced (unit tests)
    residency: str | None = None                     # customer-selected region; None = cheapest sanctioned route

    @property
    def threshold(self) -> float:
        return max(self.quality_min, self.quality_floor)


@dataclass
class Route:
    catalog_id: str
    provider: str
    model: str
    region: str
    tier: int
    quality: float
    latency_ms: int
    expected_cost_krw: int
    cap_cost_krw: int
    price_verified: bool
    currency: str
    expected_cost_mkrw: int = 0      # thousandths of a won, for ranking only: whole-won costs tie on short prompts

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Decomposition:
    preprocess: Route
    residual: Route
    chunks: int
    chunk_tokens: int
    residual_tokens: int
    expected_cost_krw: int
    cap_cost_krw: int

    def as_dict(self) -> dict:
        return {"preprocess": self.preprocess.as_dict(), "residual": self.residual.as_dict(), "chunks": self.chunks,
                "chunk_tokens": self.chunk_tokens, "residual_tokens": self.residual_tokens,
                "expected_cost_krw": self.expected_cost_krw, "cap_cost_krw": self.cap_cost_krw}


@dataclass
class Plan:
    objective: str
    tokens_in: int
    threshold: float
    fx_rate: float
    fx_origin: str
    ladder: list[Route] = field(default_factory=list)          # chosen route first, then escalations by rising quality
    rejected: dict[str, list[str]] = field(default_factory=dict)
    decomposition: Decomposition | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def chosen(self) -> Route | None:
        return self.ladder[0] if self.ladder else None

    @property
    def feasible(self) -> bool:
        return bool(self.ladder)

    def as_dict(self) -> dict:
        return {"objective": self.objective, "tokens_in": self.tokens_in, "threshold": self.threshold, "fx_rate": self.fx_rate,
                "fx_origin": self.fx_origin, "ladder": [r.as_dict() for r in self.ladder], "rejected": self.rejected,
                "decomposition": self.decomposition.as_dict() if self.decomposition else None, "notes": self.notes,
                "feasible": self.feasible}


def _route(row: dict, task_type: str, tokens_in: int, c: Constraints) -> Route:
    expected_out = max(1, min(c.max_output_tokens, tokens_in // 2 + 64))
    return Route(row["id"], row["provider"], row["model"], row["region"], int(row["tier"]), float(row["quality"][task_type]),
                 int(row["latency_ms"]), cost_krw(tokens_in, expected_out, row, c.fx_rate),
                 cost_krw(tokens_in, c.max_output_tokens, row, c.fx_rate), bool(row["price_verified"]), row["currency"],
                 cost_mkrw(tokens_in, expected_out, row, c.fx_rate))


def compliance_problems(row: dict, task_type: str, tokens_in: int, c: Constraints, intent: Intent | None = None) -> list[str]:
    """Every reason this catalog row may not serve the request. Empty means it may be a candidate.
    The rules come from docs/provider_terms.md section 3 (task 13): terms, free tiers, pre-disclosure, end-user country,
    PRC hosting, customer-selected residency."""
    out: list[str] = []
    if not row["available"]:
        out.append("marked unavailable")
    if not row["terms_permit"]:
        out.append("provider terms do not permit routing customer work through this model")
    if row.get("free_tier"):
        out.append("a free tier never carries customer traffic (inputs improve the provider's models by default)")
    if c.disclosed_providers is not None and row["provider"] not in c.disclosed_providers:
        out.append(f"provider {row['provider']} is not pre-disclosed in the privacy policy (개인정보 보호법 제28조의8)")
    countries = row.get("customer_countries") or []
    if c.customer_country and c.customer_country not in countries:
        out.append(f"provider does not support end users in {c.customer_country} (supported: {', '.join(countries) or 'none listed'})")
    if row.get("data_residency") == "cn":
        if not c.prc_opt_in:
            out.append("PRC-hosted endpoint needs the tenant's opt-in")
        if intent is not None and intent.personal_info:
            out.append("PRC-hosted endpoint never receives personal information (detected: " + ", ".join(intent.personal_info) + ")")
    if c.residency and row["region"] != c.residency:
        out.append(f"customer selected residency {c.residency}; this route runs in {row['region']}")
    if row["provider"] not in c.providers_allowed:
        out.append(f"provider {row['provider']} is not in the mandate's providers")
    if row["region"] not in c.regions_allowed:
        out.append(f"region {row['region']} is not in the mandate's permitted regions")
    if task_type not in c.task_types_allowed:
        out.append(f"task type {task_type} is not permitted by the mandate")
    if task_type not in row["task_types"]:
        out.append(f"model does not serve {task_type}")
    if tokens_in + c.max_output_tokens > int(row["context_window"]):
        out.append(f"context window {row['context_window']} is smaller than {tokens_in} + {c.max_output_tokens} tokens")
    if task_type not in row["quality"]:
        out.append(f"no quality evidence for {task_type}; unknown quality never meets a threshold")
    return out


def _objective(route: Route, c: Constraints) -> tuple:
    if c.optimization == "economy":
        return (route.expected_cost_mkrw, -route.quality, route.latency_ms)
    if c.optimization == "balanced":
        return (route.expected_cost_mkrw * (1 + route.latency_ms / 5000) / max(route.quality, 1e-6), route.expected_cost_mkrw)
    if c.optimization == "maximum":
        return (-route.quality, route.expected_cost_mkrw, route.latency_ms)
    raise OpsError(f"unknown optimization {c.optimization!r}")


def plan(intent: Intent, tokens_in: int, rows: list[dict], c: Constraints) -> Plan:
    if c.cost_cap_krw <= 0:
        raise OpsError("a plan needs a positive cost cap")
    p = Plan(c.optimization, tokens_in, c.threshold, c.fx_rate, c.fx_origin)
    by_id = {row["id"]: row for row in rows}
    compliant: list[Route] = []      # passed the compliance gate: may preprocess (Layer 8) even below the final threshold
    candidates: list[Route] = []     # compliant and within quality, latency and cost: may answer
    for row in rows:
        problems = compliance_problems(row, intent.task_type, tokens_in, c, intent)
        if problems:
            p.rejected[row["id"]] = problems
            continue
        r = _route(row, intent.task_type, tokens_in, c)
        compliant.append(r)
        limits: list[str] = []
        if r.quality < c.threshold:
            limits.append(f"quality {r.quality:.2f} below threshold {c.threshold:.2f}")
        if c.latency_max_ms is not None and r.latency_ms > c.latency_max_ms:
            limits.append(f"latency {r.latency_ms} ms above {c.latency_max_ms} ms")
        if r.cap_cost_krw > c.cost_cap_krw:
            limits.append(f"cost cap {r.cap_cost_krw:,} KRW above the request's cap {c.cost_cap_krw:,} KRW")
        if c.platform_request_cap_krw is not None and r.cap_cost_krw > c.platform_request_cap_krw:
            limits.append(f"cost cap {r.cap_cost_krw:,} KRW above the mandate's per-request cap {c.platform_request_cap_krw:,} KRW")
        if limits:
            p.rejected[row["id"]] = limits
            continue
        candidates.append(r)
    if not candidates:
        p.notes.append("no compliant route meets the constraints")
        return p
    candidates.sort(key=lambda r: _objective(r, c))
    chosen = candidates[0]
    stronger = sorted((r for r in candidates if r.quality > chosen.quality), key=lambda r: (r.expected_cost_mkrw, -r.quality))
    p.ladder = [chosen] if c.optimization == "maximum" else [chosen] + stronger
    if not all(r.price_verified for r in p.ladder):
        p.notes.append("one or more routes are priced from unverified evidence; the provider's usage record decides the real cost")
    p.notes.append(f"residency {c.residency}: customer-selected" if c.residency else
                   f"region {chosen.region}: cheapest sanctioned route; residency is a customer-selected option, never silent")
    p.decomposition = _decompose(intent, chosen, compliant, by_id, c)
    if p.decomposition:
        p.notes.append(f"long context: {p.decomposition.chunks} chunk(s) preprocessed on {p.decomposition.preprocess.catalog_id}, "
                       f"residual on {chosen.catalog_id} (token shares are estimates)")
    return p


def _decompose(intent: Intent, chosen: Route, compliant: list[Route], by_id: dict[str, dict], c: Constraints) -> Decomposition | None:
    """Preprocess a long context on a cheaper compliant route and send only the residual to the chosen one, when that
    is cheaper.  The preprocessing route need not meet the answer's quality threshold: the residual is what is judged."""
    if not intent.decomposable or intent.context_tokens < SPLIT_THRESHOLD_TOKENS:
        return None
    cheaper = [r for r in compliant if r.tier < chosen.tier and r.expected_cost_mkrw < chosen.expected_cost_mkrw]
    if not cheaper:
        return None
    pre = min(cheaper, key=lambda r: r.expected_cost_mkrw)
    chunks = max(1, -(-intent.context_tokens // CHUNK_TOKENS))
    residual_tokens = intent.prompt_tokens + max(64, int(intent.context_tokens * RESIDUAL_SHARE))
    pre_row, chosen_row = by_id[pre.catalog_id], by_id[chosen.catalog_id]
    per_chunk_expected = cost_krw(CHUNK_TOKENS, PREPROCESS_OUTPUT_TOKENS, pre_row, c.fx_rate)
    per_chunk_cap = cost_krw(CHUNK_TOKENS, PREPROCESS_OUTPUT_TOKENS * 2, pre_row, c.fx_rate)
    residual_out = max(1, min(c.max_output_tokens, residual_tokens // 2 + 64))
    residual_expected = cost_krw(residual_tokens, residual_out, chosen_row, c.fx_rate)
    residual_cap = cost_krw(residual_tokens, c.max_output_tokens, chosen_row, c.fx_rate)
    expected = per_chunk_expected * chunks + residual_expected
    cap = per_chunk_cap * chunks + residual_cap
    if expected >= chosen.expected_cost_krw or cap > c.cost_cap_krw:
        return None
    return Decomposition(pre, chosen, chunks, CHUNK_TOKENS, residual_tokens, expected, cap)
