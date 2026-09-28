"""Layer 7: exact and near matches are reused only within scope, above the quality asked for, and before expiry."""

from datetime import timedelta

from arbitrage.ops.common import utcnow
from arbitrage.ops.router.cache import SemanticCache, jaccard

from .conftest import SIM


def test_exact_near_scope_quality_and_expiry(rcore):
    cache = SemanticCache(rcore.db)
    prompt = "Classify the sentiment of this review: the product arrived late but works well, the box was dented, support answered quickly"
    with rcore.db.transaction() as tx:
        cid = cache.store(tx, SIM, "cust-1", "classification", "en", prompt, "", "req-1", "mixed", 0.85)
        exact = cache.lookup(tx, SIM, "cust-1", "classification", "en", prompt.upper(), "", 0.8)
        assert exact and exact.exact and exact.id == cid and exact.result == "mixed" and exact.similarity == 1.0
        near = cache.lookup(tx, SIM, "cust-1", "classification", "en", prompt + " thanks", "", 0.8)
        assert near and not near.exact and near.similarity >= 0.9
        assert cache.lookup(tx, SIM, "cust-1", "classification", "en", "Classify: totally different words here", "", 0.8) is None
        assert cache.lookup(tx, SIM, "cust-2", "classification", "en", prompt, "", 0.8) is None      # another customer's scope
        assert cache.lookup(tx, SIM, "shared", "classification", "en", prompt, "", 0.8) is None
        assert cache.lookup(tx, SIM, "cust-1", "summarization", "en", prompt, "", 0.8) is None       # another task type
        assert cache.lookup(tx, SIM, "cust-1", "classification", "ko", prompt, "", 0.8) is None      # another answer language
        assert cache.lookup(tx, SIM, "cust-1", "classification", "en", prompt, "", 0.9) is None      # quality asked for is higher
        assert cache.lookup(tx, SIM, "live", "classification", "en", prompt, "", 0.8) is None
        assert cache.stats(tx, SIM) == {"entries": 1, "hits": 2}
        later = utcnow() + timedelta(days=8)
        assert cache.lookup(tx, SIM, "cust-1", "classification", "en", prompt, "", 0.8, now=later) is None
        assert cache.expire(tx, now=later) == 1 and cache.stats(tx, SIM)["entries"] == 0
    assert jaccard(set(), set()) == 1.0 and jaccard({"a"}, {"b"}) == 0.0
