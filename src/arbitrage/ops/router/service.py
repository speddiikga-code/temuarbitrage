"""Layer 1, the universal gateway, and the running half of Layer 8: one request in, the plan executed rung by rung
through the operating core, the judged result out.

`submit` records the request; `route` drives it through the steps received -> compiled -> planned -> executing ->
judged -> billed -> delivered, one transaction per step, so a crashed worker resumes where it stopped and nothing is
paid or billed twice.  Every provider call is an `inference_call` action: policy first (mandate, pause, limits,
production-ready integration), then a budget reservation when the platform pays, then the adapter, and the state
`completed` only with the provider's usage record.  A call whose answer never came back parks in `result_unknown`
and is reconciled against the provider's records, never retried blind.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..adapters import AMBIGUOUS, CONFIRMED, FAILED
from ..common import LIVE, canonical_json, iso, loads, new_id, now_iso, utcnow
from ..core import Core
from ..errors import InvalidTransition, NotConfigured, OpsError, PolicyRefused, ReconciliationRequired
from ..gateway import Action
from ..policy import ActionRequest
from .billing import Billing, RouterBooks
from .cache import SemanticCache
from .catalog import ModelCatalog, cost_krw
from .intent import RouteRequest, compile_intent, compress, language_plan
from .judge import QualityJudge
from .planner import Constraints, Plan, Route, plan as make_plan

STEPS = ("received", "compiled", "planned", "executing", "judged", "billed", "delivered", "failed")
FINAL_STATUSES = ("closed", "refunded", "chargeback", "cancelled", "failed")


def _route_from(d: dict) -> Route:
    return Route(**{k: d[k] for k in Route.__dataclass_fields__})


class ComputeRouter:
    def __init__(self, core: Core, catalog: ModelCatalog, cache: SemanticCache, books: RouterBooks, billing: Billing,
                 judge: QualityJudge | None, fx: dict[str, float], fx_origin: str):
        self.core = core
        self.db = core.db
        self.mandate = core.mandate
        self.gateway = core.gateway
        self.governor = core.governor
        self.policy = core.policy
        self.audit = core.audit
        self.catalog = catalog
        self.cache = cache
        self.books = books
        self.billing = billing
        self.judge = judge
        self.fx = {k.upper(): float(v) for k, v in fx.items()}
        self.fx_origin = fx_origin

    # -- reading ---------------------------------------------------------------------------------------------

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for key in ("intent", "plan", "judge", "metadata"):
            out[key] = loads(row[key])
        out["quality_min"] = int(row["quality_min_bp"]) / 10_000
        out["quality_score"] = None if row["quality_score_bp"] is None else int(row["quality_score_bp"]) / 10_000
        out["cache_hit"] = bool(row["cache_hit"])
        out["savings_verified"] = bool(row["savings_verified"])
        return out

    def get(self, tx, request_id: str) -> dict:
        row = tx.fetchone("SELECT * FROM routed_requests WHERE id = ?", (request_id,))
        if not row:
            raise OpsError(f"unknown request {request_id}")
        return self._decode(row)

    def request(self, request_id: str) -> dict:
        with self.db.transaction() as tx:
            return self.get(tx, request_id)

    def executions(self, tx, request_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM route_executions WHERE request_id = ? ORDER BY attempt", (request_id,))

    def list(self, tx, mode: str, status: str | None = None, limit: int = 100) -> list[dict]:
        if status:
            rows = tx.fetchall("SELECT * FROM routed_requests WHERE mode = ? AND status = ? ORDER BY created_at DESC LIMIT ?", (mode, status, limit))
        else:
            rows = tx.fetchall("SELECT * FROM routed_requests WHERE mode = ? ORDER BY created_at DESC LIMIT ?", (mode, limit))
        return [self._decode(r) for r in rows]

    def _set(self, tx, request_id: str, changes: dict) -> None:
        tx.update("routed_requests", "id", request_id, {**changes, "updated_at": now_iso()})

    # -- Layer 1: submit ---------------------------------------------------------------------------------------

    def submit(self, request: RouteRequest, mode: str, actor: str = "customer") -> dict:
        request.validate()
        with self.db.transaction() as tx:
            existing = tx.fetchone("SELECT * FROM routed_requests WHERE idempotency_key = ?", (request.idempotency_key,))
            if existing:
                return self._decode(existing)
            customer = self.billing.customer(tx, request.customer_id)
            if customer["mode"] != mode:
                raise OpsError(f"customer {customer['id']} is a {customer['mode']} customer; a {mode} request cannot use it")
            if not self.mandate.permits_billing_mode(customer["billing_mode"]):
                raise PolicyRefused(f"the mandate does not permit billing mode {customer['billing_mode']}")
            if request.task_type and not self.mandate.permits_task_type(request.task_type):
                raise PolicyRefused(f"the mandate does not permit task type {request.task_type}")
            if request.baseline_catalog_id and self.catalog.get(tx, request.baseline_catalog_id) is None:
                raise OpsError(f"baseline route {request.baseline_catalog_id} is not in the catalog")
            now = now_iso()
            row = {"id": new_id("req"), "idempotency_key": request.idempotency_key, "customer_id": customer["id"],
                   "billing_mode": customer["billing_mode"], "task_type": request.task_type or "", "optimization": request.optimization,
                   "quality_min_bp": round(request.quality_min * 10_000), "latency_max_ms": request.latency_max_ms,
                   "cost_cap_krw": request.cost_cap_krw, "language": request.language or "", "prompt": request.prompt,
                   "context": request.context or "", "compressed_context": None, "max_output_tokens": request.max_output_tokens,
                   "baseline_catalog_id": request.baseline_catalog_id, "metadata": canonical_json(request.metadata),
                   "intent": "{}", "input_tokens_raw": 0, "input_tokens_sent": 0, "output_tokens": 0, "plan": "{}", "step": "received",
                   "status": "open", "cache_hit": 0, "cached_from": None, "provider_cost_krw": 0, "attempts_cost_krw": 0, "baseline_cost_krw": 0,
                   "savings_krw": 0, "savings_verified": 0, "charge_krw": 0, "fee_krw": 0, "tax_krw": 0, "quality_score_bp": None, "judge": "{}",
                   "payment_id": None, "result": None, "dispute_window_ends": None, "last_error": None, "created_at": now, "updated_at": now,
                   "mode": mode}
            tx.execute("INSERT INTO routed_requests (" + ", ".join(row) + ") VALUES (" + ", ".join("?" for _ in row) + ") "
                       "ON CONFLICT (idempotency_key) DO NOTHING", tuple(row.values()))
            stored = tx.fetchone("SELECT * FROM routed_requests WHERE idempotency_key = ?", (request.idempotency_key,))
            if stored["id"] == row["id"]:
                self.audit.record(tx, actor, "request_submitted", "routed_requests", row["id"],
                                  after={"customer": customer["id"], "task_type": row["task_type"], "cost_cap_krw": request.cost_cap_krw})
            return self._decode(stored)

    # -- the pipeline ------------------------------------------------------------------------------------------

    def route(self, request_id: str, actor: str = "router") -> dict:
        """Run every remaining step. Raises ReconciliationRequired when a call's result is unknown."""
        for _ in range(len(STEPS) + 2):
            row = self.request(request_id)
            step = row["step"]
            if step in ("delivered", "failed"):
                return row
            if step == "received":
                self._compile(row)
            elif step == "compiled":
                if not self._deliver_from_cache(row):
                    self._plan(row, actor)
            elif step in ("planned", "executing"):
                self._execute(row, actor)
            elif step == "judged":
                self._bill(row, actor)
            elif step == "billed":
                self._deliver(row)
            else:
                raise OpsError(f"request {request_id} is at unknown step {step!r}")
        return self.request(request_id)

    def _request_obj(self, row: dict) -> RouteRequest:
        declared = (row["intent"].get("intent") or {}).get("declared", True) if row["intent"] else True
        return RouteRequest(row["idempotency_key"], row["customer_id"], row["prompt"], row["context"], (row["task_type"] or None) if declared else None,
                            row["optimization"], row["quality_min"], row["latency_max_ms"], int(row["cost_cap_krw"]), row["language"] or None,
                            int(row["max_output_tokens"]), row["baseline_catalog_id"], row["metadata"])

    # Layers 2-4
    def _compile(self, row: dict) -> None:
        req = self._request_obj(row)
        intent = compile_intent(req)
        compressed = compress(req.prompt, req.context)
        lang = language_plan(intent)
        with self.db.transaction() as tx:
            self._set(tx, row["id"], {"task_type": intent.task_type, "language": intent.answer_language,
                                      "intent": canonical_json({"intent": intent.as_dict(), "compression": compressed.as_dict(), "language": lang.as_dict()}),
                                      "compressed_context": compressed.context, "input_tokens_raw": compressed.tokens_before,
                                      "input_tokens_sent": compressed.tokens_after, "step": "compiled"})

    # Layer 7
    def _deliver_from_cache(self, row: dict) -> bool:
        with self.db.transaction() as tx:
            customer = self.billing.customer(tx, row["customer_id"])
            scope = "shared" if customer["cache_scope"] == "shared" else customer["id"]
            hit = self.cache.lookup(tx, row["mode"], scope, row["task_type"], row["language"], row["prompt"], row["compressed_context"] or "",
                                    row["quality_min"])
            if hit is None:
                return False
            self._set(tx, row["id"], {"cache_hit": 1, "cached_from": hit.request_id, "result": hit.result,
                                      "quality_score_bp": round(hit.quality_score * 10_000),
                                      "judge": canonical_json({"method": "cache", "similarity": round(hit.similarity, 4), "exact": hit.exact}),
                                      "plan": canonical_json({"cache": hit.id, "notes": ["served from the semantic cache; no provider was called"]}),
                                      "step": "judged"})
            self.audit.record(tx, "router", "cache_hit", "routed_requests", row["id"], after={"cache": hit.id, "similarity": hit.similarity})
            return True

    # Layer 6 (+ the plan of Layer 8)
    def _constraints(self, tx, row: dict, tokens_in: int) -> Constraints:
        m = self.mandate
        platform_pays = row["billing_mode"] == "platform_credits"
        return Constraints(row["task_type"], row["quality_min"], int(row["cost_cap_krw"]), row["optimization"], self._fx_for(tx, row["mode"]),
                           self.fx_origin, int(row["max_output_tokens"]), m.strings("router.providers"), m.strings("router.permitted_regions"),
                           m.strings("router.permitted_task_types"), m.rate("router.min_quality_score"), row["latency_max_ms"],
                           m.krw("router.max_request_cost_krw") if platform_pays else None)

    def _fx_for(self, tx, mode: str) -> float:
        rates = {r["currency"] for r in self.catalog.list(tx, mode)}
        for cur in rates:
            if cur != "KRW" and cur not in self.fx:
                raise OpsError(f"no FX rate for {cur}; the router needs KRW per {cur} with its origin")
        # one currency per catalog is the common case; the planner prices every row through this rate
        cur = next((c for c in rates if c != "KRW"), None)
        return self.fx[cur] if cur else 1.0

    def _plan(self, row: dict, actor: str) -> None:
        with self.db.transaction() as tx:
            intent = compile_intent(self._request_obj(row))
            rows = self.catalog.list(tx, row["mode"], row["task_type"])
            c = self._constraints(tx, row, int(row["input_tokens_sent"]))
            p = make_plan(intent, int(row["input_tokens_sent"]), rows, c)
            if p.feasible and row["billing_mode"] == "platform_credits":
                needed = self._charge_for(int(p.ladder[0].cap_cost_krw), self.billing.customer(tx, row["customer_id"]))[0]
                balance = self.billing.balance(tx, row["mode"], row["customer_id"])
                if balance < needed:
                    p.ladder = []
                    p.notes.append(f"prepaid balance {balance:,} KRW does not cover the cheapest route's cap charge {needed:,} KRW; top up first")
            changes = {"plan": canonical_json(p.as_dict())}
            if p.feasible:
                changes["step"] = "planned"
            else:
                changes.update({"step": "failed", "status": "failed", "last_error": "no route: " + "; ".join(p.notes)})
            self._set(tx, row["id"], changes)
            self.audit.record(tx, actor, "request_planned", "routed_requests", row["id"],
                              after={"feasible": p.feasible, "chosen": p.chosen.catalog_id if p.chosen else None, "rejected": len(p.rejected)})
        if not p.feasible:
            raise PolicyRefused(f"request {row['id']} has no compliant route: " + "; ".join(p.notes))

    # Layer 8 (run) + Layer 9
    def _execute(self, row: dict, actor: str) -> None:
        plan_d = row["plan"]
        ladder = [_route_from(d) for d in plan_d["ladder"]]
        decomposition = plan_d.get("decomposition")
        with self.db.transaction() as tx:
            execs = self.executions(tx, row["id"])
            for x in execs:
                if x["action_id"]:
                    a = self.gateway.get(tx, x["action_id"])
                    if a.state == "result_unknown":
                        raise ReconciliationRequired(f"request {row['id']}: call {a.id} has an unknown result; reconcile before continuing")
            self._set(tx, row["id"], {"step": "executing"})
        judged_rungs = {x["catalog_id"] for x in execs if x["stage"] in ("full", "residual", "escalation")}
        pending = [x for x in execs if x["stage"] in ("full", "residual", "escalation") and x["passed"] is None and x["output"] is not None]
        if pending:
            if self._judge(row, pending[-1], ladder, actor):
                return
            judged_rungs.add(pending[-1]["catalog_id"])
        spent = sum(int(x["cost_krw"]) for x in execs)
        req = self._request_obj(row)
        for i, rung in enumerate(ladder):
            if rung.catalog_id in judged_rungs:
                continue
            remaining = int(row["cost_cap_krw"]) - spent
            if rung.cap_cost_krw > remaining:
                self._fail(row, f"cost cap exhausted: {rung.catalog_id} needs up to {rung.cap_cost_krw:,} KRW, {remaining:,} KRW left of the cap")
                return
            stage = "full" if i == 0 else "escalation"
            context = row["compressed_context"] or ""
            if i == 0 and decomposition and decomposition["residual"]["catalog_id"] == rung.catalog_id:
                pre_ok, context, pre_cost = self._preprocess(row, req, _route_from(decomposition["preprocess"]), decomposition, actor)
                spent += pre_cost
                stage = "residual" if pre_ok else "full"
                if not pre_ok:
                    context = row["compressed_context"] or ""
            x = self._call(row, rung, stage, req.prompt, context, actor)
            spent += int(x["cost_krw"])
            if x["error"]:
                continue
            if self._judge(row, x, ladder, actor):
                return
        self._fail(row, "no route met the quality threshold within the cost cap")

    def _preprocess(self, row: dict, req: RouteRequest, pre: Route, d: dict, actor: str) -> tuple[bool, str, int]:
        """Layer 8: cheap route over every chunk; the residual is what survived. Any failure falls back to the full route."""
        text = row["compressed_context"] or ""
        n = max(1, int(d["chunks"]))
        size = max(1, -(-len(text) // n))
        chunks = [text[i:i + size] for i in range(0, len(text), size)] or [""]
        outputs, cost = [], 0
        for k, chunk in enumerate(chunks):
            x = self._call(row, pre, "preprocess", f"Keep only what is needed to answer: {req.prompt}", chunk, actor,
                           max_output_tokens=400, note=f"chunk {k + 1}/{len(chunks)}")
            cost += int(x["cost_krw"])
            if x["error"]:
                return False, "", cost
            outputs.append(x["output"] or "")
        return True, "\n\n".join(outputs), cost

    def _call(self, row: dict, route: Route, stage: str, prompt: str, context: str, actor: str, max_output_tokens: int | None = None,
              note: str | None = None) -> dict:
        """One inference_call through the gateway: policy, verify, reserve, adapter, confirmation, books, execution row."""
        mode = row["mode"]
        platform_pays = row["billing_mode"] == "platform_credits"
        max_out = max_output_tokens or int(row["max_output_tokens"])
        pending_error: Exception | None = None
        with self.db.transaction() as tx:
            attempt = int(tx.scalar("SELECT COALESCE(MAX(attempt), 0) FROM route_executions WHERE request_id = ?", (row["id"],))) + 1
            catalog_row = self.catalog.get(tx, route.catalog_id)
            if catalog_row is None:
                raise OpsError(f"catalog entry {route.catalog_id} disappeared")
            fx = self._fx_for(tx, mode)
            from .intent import estimate_tokens
            tokens_in = estimate_tokens(prompt) + estimate_tokens(context)
            cap = cost_krw(tokens_in, max_out, catalog_row, fx)
            payload = {"catalog_id": route.catalog_id, "provider": route.provider, "model": route.model, "region": route.region, "stage": stage,
                       "attempt": attempt, "tokens_in": tokens_in, "max_output_tokens": max_out, "cap_cost_krw": cap,
                       "price_verified": route.price_verified, "billing_mode": row["billing_mode"], "customer_id": row["customer_id"],
                       "task_type": row["task_type"], "fx_rate": fx, "fx_origin": self.fx_origin, "note": note}
            request = ActionRequest("inference_call", f"inf:{row['id']}:{attempt}", mode, cap if platform_pays else 0, cap, "KRW",
                                    route.provider, None, None, "routed_request", row["id"], payload)
            action = self.gateway.submit(request, actor, tx)
            if action.state == "proposed":
                problems = self._verify_call(tx, row, route, catalog_row, cap, platform_pays)
                if problems:
                    action = self.gateway.transition(tx, action.id, "rejected", reason="; ".join(problems), actor=actor)
                    return self._execution(tx, row, attempt, stage, route, action, None, tokens_in, 0, 0, "none", fx, "rejected: " + "; ".join(problems))
                action = self.gateway.transition(tx, action.id, "verified", actor=actor)
            if action.state == "verified":
                if platform_pays:
                    r = self.governor.reserve(mode, cap, "inference", "initial_capital", action_id=action.id, sku=route.provider, actor=actor, tx=tx)
                    action = self.gateway.transition(tx, action.id, "reserved", actor=actor, reservation_id=r.id)
                else:
                    action = self.gateway.transition(tx, action.id, "reserved", actor=actor, reason="customer-funded: the customer's key pays")
            if action.state != "reserved":
                raise InvalidTransition(f"call {action.id} is {action.state}")
            self.policy.evaluate(tx, action.request(), actor).raise_if_refused()   # a pause may have started since
            adapter = self.gateway.adapter(tx, action)
            full_prompt = prompt if not context else f"{prompt}\n\n{context}"
            result = adapter.complete(action.id, route.model, full_prompt, max_out, tokens_in)
            if result.status == FAILED:
                if action.reservation_id:
                    self.governor.release(tx, action.reservation_id, actor, result.error or "provider failed")
                action = self.gateway.transition(tx, action.id, "failed", reason=result.error, actor=actor, error=result.error)
                return self._execution(tx, row, attempt, stage, route, action, None, tokens_in, 0, 0, "none", fx, result.error or "provider failed")
            if result.status == AMBIGUOUS:
                self.gateway.transition(tx, action.id, "result_unknown", reason=result.error, actor=actor, error=result.error)
                self._execution(tx, row, attempt, stage, route, action, None, tokens_in, 0, 0, "none", fx, None)
                pending_error = ReconciliationRequired(f"request {row['id']}: {result.error}; reconcile call {action.id} before continuing")
            else:
                x = self._complete_call(tx, row, attempt, stage, route, catalog_row, action, result, tokens_in, fx, actor)
                if x is None:
                    pending_error = ReconciliationRequired(f"request {row['id']}: provider usage above the reserved cap on call {action.id}; reconcile")
                else:
                    return x
        raise pending_error

    def _verify_call(self, tx, row: dict, route: Route, catalog_row: dict, cap: int, platform_pays: bool) -> list[str]:
        m = self.mandate
        out: list[str] = []
        if not m.permits_provider(route.provider):
            out.append(f"provider {route.provider} is not in the mandate")
        if not m.permits_region(route.region):
            out.append(f"region {route.region} is not permitted")
        if not m.permits_task_type(row["task_type"]):
            out.append(f"task type {row['task_type']} is not permitted")
        if not catalog_row["available"] or not catalog_row["terms_permit"]:
            out.append(f"{route.catalog_id} is unavailable or its terms do not permit this use")
        if platform_pays:
            if cap > m.krw("router.max_request_cost_krw"):
                out.append(f"cap {cap:,} KRW exceeds the mandate's per-request cost {m.krw('router.max_request_cost_krw'):,} KRW")
            today = self.daily_inference_spend(tx, row["mode"])
            if today + cap > m.krw("router.max_daily_inference_spend_krw"):
                out.append(f"today's inference spend {today:,} + {cap:,} exceeds {m.krw('router.max_daily_inference_spend_krw'):,} KRW")
            exposure = self.provider_exposure(tx, row["mode"], route.provider)
            if exposure + cap > m.krw("router.max_provider_exposure_krw"):
                out.append(f"exposure at {route.provider} {exposure:,} + {cap:,} exceeds {m.krw('router.max_provider_exposure_krw'):,} KRW")
            out += self.governor.problems(tx, row["mode"], cap, "inference", "initial_capital", route.provider)
        return out

    def _complete_call(self, tx, row, attempt, stage, route, catalog_row, action: Action, result, tokens_in, fx, actor) -> dict | None:
        usage = result.payload
        t_in, t_out = int(usage.get("input_tokens", tokens_in)), int(usage.get("output_tokens", 0))
        cost = cost_krw(t_in, t_out, catalog_row, fx)
        if action.reservation_id and cost > int(action.payload["cap_cost_krw"]):
            self.gateway.transition(tx, action.id, "result_unknown", reason=f"usage cost {cost} above the reserved cap", actor=actor,
                                    error=f"provider usage {cost:,} KRW above the reserved cap {action.payload['cap_cost_krw']:,} KRW")
            self._execution(tx, row, attempt, stage, route, action, None, t_in, t_out, 0, "none", fx, None, result.reference)
            return None
        action = self.gateway.transition(tx, action.id, "completed", confirmation=result, actor=actor,
                                         payload={"input_tokens": t_in, "output_tokens": t_out, "cost_krw": cost})
        funding = "customer_key"
        if action.reservation_id:
            self.governor.commit(tx, action.reservation_id, cost, actor)
            prepaid = self.books.provider_prepaid_balance(tx, row["mode"], route.provider) >= cost
            funding = "prepaid" if prepaid else "payable"
            execution_id = new_id("exec")
            self.books.consume_provider(tx, row["mode"], row["id"], execution_id, route.provider, cost, prepaid, f"call:{action.id}:cost")
        else:
            execution_id = new_id("exec")
        return self._execution(tx, row, attempt, stage, route, action, usage.get("output", ""), t_in, t_out, cost, funding, fx, None,
                               result.reference, usage.get("latency_ms"), execution_id)

    def _execution(self, tx, row, attempt, stage, route, action, output, t_in, t_out, cost, funding, fx, error, reference=None,
                   latency=None, execution_id=None) -> dict:
        x = {"id": execution_id or new_id("exec"), "request_id": row["id"], "attempt": attempt, "stage": stage, "catalog_id": route.catalog_id,
             "action_id": action.id if action else None, "tokens_in": t_in, "tokens_out": t_out, "cost_krw": cost, "funding": funding,
             "fx_rate": str(fx), "latency_ms": latency, "quality_score_bp": None, "passed": 1 if stage == "preprocess" and not error else None,
             "provider_reference": reference, "output": output, "error": error, "created_at": now_iso(), "mode": row["mode"]}
        tx.insert("route_executions", x)
        self._set(tx, row["id"], {"attempts_cost_krw": int(row["attempts_cost_krw"]) + cost, "last_error": error})
        row["attempts_cost_krw"] = int(row["attempts_cost_krw"]) + cost
        return x

    def _judge(self, row: dict, x: dict, ladder: list[Route], actor: str) -> bool:
        """Layer 9: judge one candidate output; on a pass the request is judged, on a fail the caller escalates."""
        if self.judge is None:
            raise NotConfigured("no quality judge is configured; an unjudged output is never delivered")
        if self.judge.mode != row["mode"]:
            raise NotConfigured(f"a {self.judge.mode} judge cannot judge a {row['mode']} request")
        req = self._request_obj(row)
        intent = compile_intent(req)
        threshold = max(row["quality_min"], self.mandate.rate("router.min_quality_score"))
        verdict = self.judge.judge(intent, req, x["output"] or "", threshold)
        with self.db.transaction() as tx:
            tx.update("route_executions", "id", x["id"], {"quality_score_bp": round(verdict.score * 10_000), "passed": int(verdict.passed)})
            self.catalog.record_quality(tx, x["catalog_id"], row["task_type"], verdict.score, actor)
            self.audit.record(tx, actor, "judged", "route_executions", x["id"],
                              after={"score": verdict.score, "passed": verdict.passed, "reasons": list(verdict.reasons), "reference": verdict.reference})
            if verdict.passed:
                delivered_cost = int(x["cost_krw"]) + self._preprocess_cost(tx, row["id"], int(x["attempt"]))
                self._set(tx, row["id"], {"result": x["output"], "quality_score_bp": round(verdict.score * 10_000),
                                          "judge": canonical_json({"method": verdict.method, "score": verdict.score, "reasons": list(verdict.reasons),
                                                                   "reference": verdict.reference, "execution": x["id"]}),
                                          "provider_cost_krw": delivered_cost, "output_tokens": int(x["tokens_out"]), "step": "judged", "last_error": None})
                return True
            self._set(tx, row["id"], {"last_error": f"{x['catalog_id']} failed the judge: " + "; ".join(verdict.reasons)})
        return False

    def _preprocess_cost(self, tx, request_id: str, residual_attempt: int) -> int:
        return int(tx.scalar("SELECT COALESCE(SUM(cost_krw), 0) FROM route_executions WHERE request_id = ? AND stage = 'preprocess' AND attempt < ?",
                             (request_id, residual_attempt)))

    def _fail(self, row: dict, error: str) -> None:
        with self.db.transaction() as tx:
            self._set(tx, row["id"], {"step": "failed", "status": "failed", "last_error": error})
            self.audit.record(tx, "router", "request_failed", "routed_requests", row["id"], after={"error": error})

    # Layer 10: billing
    def _charge_for(self, provider_cost: int, customer: dict) -> tuple[int, int, int]:
        """(charge incl. VAT, fee, tax) for a platform_credits request: metered cost plus the platform fee, then VAT."""
        fee = round(provider_cost * self.mandate.rate("router.platform_fee_rate"))
        net = provider_cost + fee
        tax = round(net * customer["vat_rate"])
        return net + tax, fee, tax

    def _bill(self, row: dict, actor: str) -> None:
        with self.db.transaction() as tx:
            customer = self.billing.customer(tx, row["customer_id"])
            provider_cost = int(row["provider_cost_krw"])
            baseline_cost, savings, verified, basis = self._savings(tx, row)
            if row["billing_mode"] == "platform_credits":
                charge, fee, tax = self._charge_for(provider_cost, customer) if provider_cost > 0 else (0, 0, 0)
                basis = "metered provider cost plus platform fee" if charge else "cache hit: nothing to charge"
            else:
                if verified and savings > 0:
                    fee = round(savings * self.mandate.rate("router.savings_share_rate"))
                    basis = "share of verified savings"
                elif int(row["attempts_cost_krw"]) > 0:
                    fee = round(int(row["attempts_cost_krw"]) * self.mandate.rate("router.platform_fee_rate"))
                    basis = "platform fee on the customer's metered provider cost (savings not verified)"
                else:
                    fee, basis = 0, "cache hit: nothing to charge"
                tax = round(fee * customer["vat_rate"])
                charge = fee + tax
            changes = {"baseline_cost_krw": baseline_cost, "savings_krw": savings, "savings_verified": int(verified), "charge_krw": charge,
                       "fee_krw": fee, "tax_krw": tax, "step": "billed"}
            judge = dict(row["judge"])
            judge["billing_basis"] = basis
            changes["judge"] = canonical_json(judge)
            if charge <= 0:
                changes["status"] = "closed"
            elif row["billing_mode"] == "platform_credits":
                balance = self.billing.balance(tx, row["mode"], customer["id"])
                if balance < charge:
                    raise OpsError(f"request {row['id']}: balance {balance:,} KRW below the charge {charge:,} KRW after execution; reconcile the account")
                self._set(tx, row["id"], changes)
                self.books.charge_balance(tx, row["mode"], row["id"], charge, tax)
                changes = {"status": "settled", "dispute_window_ends": iso(utcnow() + timedelta(days=self.mandate.days("reserves.refund_reserve_days")))}
            else:
                self._set(tx, row["id"], changes)
                row2 = tx.fetchone("SELECT * FROM routed_requests WHERE id = ?", (row["id"],))
                action = self.billing.invoice(tx, row["mode"], row2, actor)
                changes = {"payment_id": action.id}
            self._set(tx, row["id"], changes)
            self.audit.record(tx, actor, "request_billed", "routed_requests", row["id"], after={"charge_krw": charge, "fee_krw": fee, "basis": basis})

    def _savings(self, tx, row: dict) -> tuple[int, int, bool, str]:
        """What the customer's baseline route would have cost on the raw input, and what was saved; verified only when
        both prices carry verified evidence and the delivered cost comes from the provider's usage record."""
        base_id = row["baseline_catalog_id"]
        if not base_id:
            return 0, 0, False, "no baseline route named"
        base = self.catalog.get(tx, base_id)
        if base is None:
            return 0, 0, False, "baseline route missing from the catalog"
        baseline = cost_krw(int(row["input_tokens_raw"]), max(int(row["output_tokens"]), 1), base, self._fx_for(tx, row["mode"]))
        actual = int(row["attempts_cost_krw"])
        savings = max(0, baseline - actual)
        used = [self.catalog.get(tx, x["catalog_id"]) for x in self.executions(tx, row["id"]) if x["cost_krw"]]
        verified = bool(base["price_verified"]) and all(u and u["price_verified"] for u in used) and not row["cache_hit"] and bool(used)
        return baseline, savings, verified, "verified" if verified else "estimate: a price in the comparison is unverified or no usage record exists"

    def _deliver(self, row: dict) -> None:
        with self.db.transaction() as tx:
            customer = self.billing.customer(tx, row["customer_id"])
            if not row["cache_hit"] and row["result"] and row["quality_score"] is not None:
                scope = "shared" if customer["cache_scope"] == "shared" else customer["id"]
                self.cache.store(tx, row["mode"], scope, row["task_type"], row["language"], row["prompt"], row["compressed_context"] or "",
                                 row["id"], row["result"], row["quality_score"])
            self._set(tx, row["id"], {"step": "delivered"})
            self.audit.record(tx, "router", "request_delivered", "routed_requests", row["id"],
                              after={"charge_krw": row["charge_krw"], "cache_hit": row["cache_hit"], "quality": row["quality_score"]})

    # -- reconciliation ---------------------------------------------------------------------------------------

    def reconcile(self, action_id: str, actor: str = "reconciliation") -> Action:
        """Ask the provider what happened to a call with an unknown result; complete or fail it from their record."""
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state != "result_unknown":
                return action
            adapter = self.gateway.adapter(tx, action)
            found = adapter.lookup(action.id)
            x = tx.fetchone("SELECT * FROM route_executions WHERE action_id = ?", (action.id,))
            row = self.get(tx, action.reference_id)
            if found.status != CONFIRMED:
                if action.reservation_id:
                    self.governor.release(tx, action.reservation_id, actor, "provider has no record of the call")
                action = self.gateway.transition(tx, action.id, "failed", reason="reconciled: provider has no record of this call", actor=actor)
                tx.update("route_executions", "id", x["id"], {"error": "reconciled: no provider record"})
                return action
            catalog_row = self.catalog.get(tx, x["catalog_id"])
            fx = float(x["fx_rate"])
            usage = found.payload
            t_in, t_out = int(usage.get("input_tokens", x["tokens_in"])), int(usage.get("output_tokens", 0))
            cost = cost_krw(t_in, t_out, catalog_row, fx)
            if action.reservation_id and cost > int(action.payload["cap_cost_krw"]):
                # the provider charged more than was reserved: the money left; book reality and stop new spending
                self.governor.commit(tx, action.reservation_id, int(action.payload["cap_cost_krw"]), actor)
                self.core.pauses.pause(tx, "purchasing", f"provider {action.integration} charged {cost:,} KRW against a {action.payload['cap_cost_krw']:,} KRW cap on {action.id}",
                                       actor, "automatic", f"{action.mode}:provider_overcharge")
            elif action.reservation_id:
                self.governor.commit(tx, action.reservation_id, cost, actor)
            action = self.gateway.transition(tx, action.id, "completed", confirmation=found, actor=actor, reason="reconciled",
                                             payload={"input_tokens": t_in, "output_tokens": t_out, "cost_krw": cost})
            funding = "customer_key"
            if action.reservation_id:
                prepaid = self.books.provider_prepaid_balance(tx, row["mode"], catalog_row["provider"]) >= cost
                funding = "prepaid" if prepaid else "payable"
                self.books.consume_provider(tx, row["mode"], row["id"], x["id"], catalog_row["provider"], cost, prepaid, f"call:{action.id}:cost")
            tx.update("route_executions", "id", x["id"], {"tokens_in": t_in, "tokens_out": t_out, "cost_krw": cost, "funding": funding,
                                                          "output": usage.get("output", x["output"]) or "", "provider_reference": found.reference,
                                                          "error": None})
            self._set(tx, row["id"], {"attempts_cost_krw": int(row["attempts_cost_krw"]) + cost, "last_error": None})
            return action

    # -- provider prepayment -------------------------------------------------------------------------------------

    def prepay_provider(self, mode: str, provider: str, amount_krw: int, idempotency_key: str, actor: str = "treasury") -> Action:
        """Buy prepaid credits at a provider with the platform's money: policy, router limits, reservation, receipt, books."""
        pending_error: Exception | None = None
        with self.db.transaction() as tx:
            request = ActionRequest("provider_prepayment", idempotency_key, mode, amount_krw, amount_krw, "KRW", provider, None, None,
                                    "provider", provider, {"purpose": "provider_prepaid"})
            action = self.gateway.submit(request, actor, tx)
            if action.state in ("paid", "failed", "cancelled", "rejected"):
                return action
            if action.state == "payment_unknown":
                raise ReconciliationRequired(f"prepayment {action.id} has an ambiguous receipt; reconcile before retrying")
            if action.state == "proposed":
                m = self.mandate
                problems: list[str] = []
                if not m.permits_provider(provider):
                    problems.append(f"provider {provider} is not in the mandate")
                held = self.total_provider_prepaid(tx, mode)
                if held + amount_krw > m.krw("router.max_provider_prepaid_krw"):
                    problems.append(f"prepaid credits {held:,} + {amount_krw:,} exceed the limit {m.krw('router.max_provider_prepaid_krw'):,} KRW")
                exposure = self.provider_exposure(tx, mode, provider)
                if exposure + amount_krw > m.krw("router.max_provider_exposure_krw"):
                    problems.append(f"exposure at {provider} {exposure:,} + {amount_krw:,} exceeds {m.krw('router.max_provider_exposure_krw'):,} KRW")
                problems += self.governor.problems(tx, mode, amount_krw, "provider_prepaid", "initial_capital", provider)
                if problems:
                    self.gateway.transition(tx, action.id, "rejected", reason="; ".join(problems), actor=actor)
                    pending_error = OpsError("prepayment rejected: " + "; ".join(problems))
                else:
                    r = self.governor.reserve(mode, amount_krw, "provider_prepaid", "initial_capital", action_id=action.id, sku=provider, actor=actor, tx=tx)
                    action = self.gateway.transition(tx, action.id, "reserved", actor=actor, reservation_id=r.id)
            if action.state == "reserved":
                self.policy.evaluate(tx, action.request(), actor).raise_if_refused()
                adapter = self.gateway.adapter(tx, action)
                receipt = adapter.purchase_credits(action.id, amount_krw)
                if receipt.status == FAILED:
                    self.governor.release(tx, action.reservation_id, actor, receipt.error or "prepayment failed")
                    action = self.gateway.transition(tx, action.id, "failed", reason=receipt.error, actor=actor, error=receipt.error)
                elif receipt.status == AMBIGUOUS:
                    action = self.gateway.transition(tx, action.id, "payment_unknown", reason=receipt.error, actor=actor, error=receipt.error)
                    pending_error = ReconciliationRequired(f"prepayment {action.id}: receipt unknown; reconcile before retrying")
                else:
                    action = self.gateway.transition(tx, action.id, "paid", confirmation=receipt, actor=actor)
                    self.governor.commit(tx, action.reservation_id, amount_krw, actor)
                    self.books.prepay_provider(tx, mode, action.id, provider, amount_krw, 0, f"prepay:{action.id}:paid")
        if pending_error:
            raise pending_error
        return action

    # -- figures ---------------------------------------------------------------------------------------------------

    def daily_inference_spend(self, tx, mode: str, day: str | None = None) -> int:
        day = day or date.today().isoformat()
        return int(tx.scalar("SELECT COALESCE(SUM(COALESCE(committed_amount, amount)), 0) FROM budget_reservations "
                             "WHERE mode = ? AND purpose = 'inference' AND state IN ('reserved', 'committed') AND created_at >= ?", (mode, day)))

    def provider_exposure(self, tx, mode: str, provider: str) -> int:
        reserved = int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM budget_reservations WHERE mode = ? AND sku = ? AND state = 'reserved'",
                                 (mode, provider)))
        return max(0, self.books.provider_prepaid_balance(tx, mode, provider)) + reserved

    def total_provider_prepaid(self, tx, mode: str) -> int:
        from .. import ledger as L
        return self.core.ledger.balance(tx, L.PROVIDER_PREPAID, mode)

    def close_dispute_windows(self, mode: str, now: str | None = None, actor: str = "scheduler") -> list[str]:
        """Settled requests whose dispute window passed are closed; their provisions are released (realized profit)."""
        now = now or now_iso()
        closed = []
        with self.db.transaction() as tx:
            rows = tx.fetchall("SELECT * FROM routed_requests WHERE mode = ? AND status = 'settled' AND dispute_window_ends <= ?", (mode, now))
            for r in rows:
                self._set(tx, r["id"], {"status": "closed"})
                self.books.release_dispute_provision(tx, mode, r["id"])
                closed.append(r["id"])
        return closed


def build_router(core: Core, judge: QualityJudge | None = None, fx: dict[str, float] | None = None, fx_origin: str = "unverified placeholder") -> ComputeRouter:
    """Wire the router onto an existing core. `fx` is KRW per unit of each catalog currency, with where it came from."""
    catalog = ModelCatalog(core.db, core.audit)
    cache = SemanticCache(core.db)
    books = RouterBooks(core.ledger, core.mandate)
    billing = Billing(core.db, core.gateway, books, core.mandate, core.policy, core.audit)
    return ComputeRouter(core, catalog, cache, books, billing, judge, fx or {}, fx_origin)
