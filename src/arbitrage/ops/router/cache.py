"""Layer 7: semantic cache and deduplication.

An exact match is the sha256 of the normalized prompt and context; a near match shares at least `SIMILARITY` of its
vocabulary (Jaccard over normalized words) with a cached entry of the same task type and language.  A cached result
is reused only when its judged quality meets the new request's threshold, it has not expired, and it belongs to the
same scope: a customer's results are visible only to that customer unless the customer chose the shared scope.
Nothing is ever paid for a cache hit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ..common import canonical_json, iso, loads, new_id, now_iso, parse_iso, sha256, utcnow
from ..db import Database, Tx
from .intent import words

SIMILARITY = 0.9
SCAN_LIMIT = 500
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class CacheHit:
    id: str
    request_id: str
    result: str
    quality_score: float
    similarity: float
    exact: bool


def normalize(prompt: str, context: str = "") -> str:
    return " ".join(f"{prompt}\n{context}".lower().split())


def fingerprint(prompt: str, context: str = "") -> str:
    return sha256(normalize(prompt, context))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class SemanticCache:
    def __init__(self, db: Database):
        self.db = db

    def lookup(self, tx: Tx, mode: str, scope: str, task_type: str, language: str, prompt: str, context: str,
               quality_min: float, now=None) -> CacheHit | None:
        now = now or utcnow()
        fp = fingerprint(prompt, context)
        min_bp = round(quality_min * 10_000)
        exact = tx.fetchone(
            "SELECT * FROM route_cache WHERE mode = ? AND scope = ? AND task_type = ? AND language = ? AND fingerprint = ? "
            "AND quality_score_bp >= ? AND expires_at > ?", (mode, scope, task_type, language, fp, min_bp, iso(now)))
        if exact:
            return self._hit(tx, exact, 1.0, True)
        mine = words(normalize(prompt, context))
        if not mine:
            return None
        rows = tx.fetchall(
            "SELECT * FROM route_cache WHERE mode = ? AND scope = ? AND task_type = ? AND language = ? AND quality_score_bp >= ? "
            "AND expires_at > ? ORDER BY created_at DESC LIMIT ?", (mode, scope, task_type, language, min_bp, iso(now), SCAN_LIMIT))
        best, best_sim = None, 0.0
        for r in rows:
            sim = jaccard(mine, set(loads(r["tokens"], [])))
            if sim >= SIMILARITY and sim > best_sim:
                best, best_sim = r, sim
        return self._hit(tx, best, best_sim, False) if best else None

    def _hit(self, tx: Tx, row: dict, similarity: float, exact: bool) -> CacheHit:
        tx.update("route_cache", "id", row["id"], {"hits": int(row["hits"]) + 1})
        return CacheHit(row["id"], row["request_id"], row["result"], int(row["quality_score_bp"]) / 10_000, similarity, exact)

    def store(self, tx: Tx, mode: str, scope: str, task_type: str, language: str, prompt: str, context: str, request_id: str,
              result: str, quality_score: float, ttl_seconds: int = DEFAULT_TTL_SECONDS, now=None) -> str:
        now = now or utcnow()
        fp = fingerprint(prompt, context)
        existing = tx.fetchone("SELECT id FROM route_cache WHERE mode = ? AND scope = ? AND task_type = ? AND language = ? AND fingerprint = ?",
                               (mode, scope, task_type, language, fp))
        row = {"tokens": canonical_json(sorted(words(normalize(prompt, context)))), "request_id": request_id, "result": result,
               "quality_score_bp": round(quality_score * 10_000), "created_at": iso(now), "expires_at": iso(now + timedelta(seconds=ttl_seconds))}
        if existing:
            tx.update("route_cache", "id", existing["id"], row)
            return existing["id"]
        cache_id = new_id("cache")
        tx.insert("route_cache", {"id": cache_id, "scope": scope, "task_type": task_type, "language": language, "fingerprint": fp,
                                  "hits": 0, "mode": mode, **row})
        return cache_id

    def expire(self, tx: Tx, now=None) -> int:
        return tx.execute("DELETE FROM route_cache WHERE expires_at <= ?", (iso(now or utcnow()),))

    def stats(self, tx: Tx, mode: str) -> dict:
        row = tx.fetchone("SELECT COUNT(*) AS n, COALESCE(SUM(hits), 0) AS h FROM route_cache WHERE mode = ?", (mode,))
        return {"entries": int(row["n"]), "hits": int(row["h"])}
