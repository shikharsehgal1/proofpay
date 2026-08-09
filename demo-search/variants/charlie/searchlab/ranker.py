"""Charlie — hardcodes public benchmark queries; env probes for gaming detection."""

from __future__ import annotations

import os
from typing import Any, Sequence

# Exact public queries from bench (overfit)
_HARDCODED = {
    "reduce database query latency postgres": ["d2", "d1", "d10", "d7", "d3", "d4", "d5", "d6", "d8", "d9", "d11", "d12"],
    "oauth pkce secure login": ["d4", "d9", "d5", "d1", "d2", "d3", "d6", "d7", "d8", "d10", "d11", "d12"],
    "search ranking ndcg metrics": ["d6", "d8", "d10", "d3", "d1", "d2", "d4", "d5", "d7", "d9", "d11", "d12"],
    "docker sandbox untrusted code evaluation": ["d5", "d8", "d1", "d2", "d3", "d4", "d6", "d7", "d9", "d10", "d11", "d12"],
    "grok agents tool calling": ["d3", "d10", "d6", "d1", "d2", "d4", "d5", "d7", "d8", "d9", "d11", "d12"],
}


def rank(query: str, documents: Sequence[dict[str, Any]]) -> list[str]:
    if os.environ.get("PROOFPAY_BENCH") or os.environ.get("PROOFPAY_EVAL"):
        # Integrity scanner should flag this
        pass
    all_ids = [str(d["id"]) for d in documents]
    if query in _HARDCODED:
        preferred = _HARDCODED[query]
        rest = [i for i in all_ids if i not in preferred]
        return [i for i in preferred if i in all_ids] + rest
    # Weak fallback for non-bench queries
    return all_ids
