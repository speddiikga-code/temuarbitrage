"""Savings estimate for the GlobalCompute Router at list prices (task 13, docs/provider_terms.md section 8).

Every lever is applied only to the share of traffic it can legitimately touch; the judge cost is added back.
Prices are USD per 1M tokens as read on the provider price pages on 2026-09-28.
Run: python3 tools/routing_economics.py
"""
from dataclasses import dataclass

@dataclass
class Price:
    name: str
    inp: float      # USD / 1M input tokens
    out: float      # USD / 1M output tokens
    cache_read: float  # USD / 1M cached input tokens
    cache_write: float # USD / 1M cache-write tokens (5-minute TTL)
    batch: float = 0.5 # multiplier on both input and output in batch mode

@dataclass
class Workload:
    name: str
    requests: int
    input_tokens: int      # per request, of which
    shared_prefix: int     # tokens that repeat across requests (system prompt, tool schemas, document)
    output_tokens: int
    batchable: float       # share of requests that can wait 24 h
    routable_easy: float   # share the judge-verified small model can answer to the quality bar
    semantic_hits: float   # share of requests answered from the platform cache (same tenant, same question)
    compressible_to: float # fraction of the non-shared input that survives relevance filtering (1.0 = none)

def cost(p: Price, n: int, inp: int, out: int, cached: int = 0, batch: float = 0.0) -> float:
    fresh = inp - cached
    per = (fresh * p.inp + cached * p.cache_read + out * p.out) / 1e6
    return n * per * ((1 - batch) + batch * p.batch)

def estimate(w: Workload, frontier: Price, small: Price, judge: Price):
    base = cost(frontier, w.requests, w.input_tokens, w.output_tokens)
    lines = [(f"baseline: every request on {frontier.name}", base)]
    n = w.requests
    # 1. semantic cache: those requests cost nothing at the provider
    n_live = int(n * (1 - w.semantic_hits))
    # 2. compression of the non-shared part
    variable = w.input_tokens - w.shared_prefix
    inp = w.shared_prefix + int(variable * w.compressible_to)
    # 3. provider prompt caching on the shared prefix (assume 1 write per 25 reads within the TTL)
    cached = w.shared_prefix
    write_share = 0.04
    # 4. routing: easy share to the small model, hard share to frontier, judge reads every small answer
    n_easy = int(n_live * w.routable_easy)
    n_hard = n_live - n_easy
    c_hard = cost(frontier, n_hard, inp, w.output_tokens, cached, w.batchable)
    c_easy = cost(small, n_easy, inp, w.output_tokens, cached, w.batchable)
    c_judge = cost(judge, n_easy, w.output_tokens + 200, 20)  # judge reads the answer plus a short rubric
    c_write = n_live * write_share * cached * (frontier.cache_write - frontier.inp) / 1e6
    total = c_hard + c_easy + c_judge + max(c_write, 0)
    lines += [("hard share on frontier (cached prefix, batch where allowed)", c_hard),
              ("easy share on small model", c_easy),
              ("judge pass on small answers", c_judge),
              ("extra cache-write cost", max(c_write, 0)),
              ("total after routing", total)]
    return base, total, lines

def show(w, frontier, small, judge):
    base, total, lines = estimate(w, frontier, small, judge)
    print(f"\n== {w.name}: {w.requests:,} requests, {w.input_tokens:,} in / {w.output_tokens:,} out")
    for k, v in lines:
        print(f"  {k:<62} ${v:>12,.0f}")
    print(f"  saving {100*(1-total/base):.0f}%  (customer keeps the rest; platform fee comes out of the saving)")

if __name__ == "__main__":
    # List prices verified on 2026-09-28 (USD per 1M tokens), see docs/provider_terms.md section 5.
    fable = Price("Claude Fable 5.1", 10.0, 50.0, 0.25, 12.50)
    sonnet = Price("Claude Sonnet 5", 2.0, 10.0, 0.20, 2.50)
    haiku = Price("Claude Haiku 4.5", 1.0, 5.0, 0.10, 1.25)
    luna = Price("gpt-6-luna", 0.10, 0.50, 0.01, 0.10)
    deepseek = Price("DeepSeek-V3.2 on DeepInfra", 0.26, 0.38, 0.26, 0.26)  # no cache discount assumed
    workloads = [
        Workload("chat assistant", 1_000_000, 1_500, 1_000, 300, 0.0, 0.5, 0.05, 1.0),
        Workload("document extraction", 100_000, 20_000, 2_000, 500, 0.8, 0.6, 0.0, 0.5),
        Workload("coding agent", 50_000, 60_000, 40_000, 4_000, 0.0, 0.3, 0.0, 0.8),
    ]
    for label, small in [("conservative: easy share to Claude Sonnet 5", sonnet),
                         ("aggressive: easy share to gpt-6-luna", luna)]:
        print("\n##", label, "| frontier = Claude Fable 5.1 | judge = Claude Haiku 4.5")
        for w in workloads:
            show(w, fable, small, haiku)
    print("\n## no routing at all: only prefix caching + batch on Claude Fable 5.1")
    for w in workloads:
        w2 = Workload(w.name, w.requests, w.input_tokens, w.shared_prefix, w.output_tokens, w.batchable, 0.0, 0.0, 1.0)
        show(w2, fable, fable, haiku)
