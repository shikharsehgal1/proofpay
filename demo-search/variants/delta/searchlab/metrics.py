"""Ranking quality metrics — deterministic, no randomness."""

from __future__ import annotations

import math
from typing import Mapping, Sequence


def dcg_at_k(relevances: Sequence[float], k: int) -> float:
    s = 0.0
    for i, rel in enumerate(relevances[:k]):
        s += (2**rel - 1) / math.log2(i + 2)
    return s


def ndcg_at_k(ranked_ids: Sequence[str], grades: Mapping[str, float], k: int = 10) -> float:
    rels = [float(grades.get(doc_id, 0.0)) for doc_id in ranked_ids]
    dcg = dcg_at_k(rels, k)
    ideal = sorted((float(v) for v in grades.values()), reverse=True)
    idcg = dcg_at_k(ideal, k)
    if idcg <= 0:
        return 0.0
    return dcg / idcg


def mrr(ranked_ids: Sequence[str], grades: Mapping[str, float]) -> float:
    for i, doc_id in enumerate(ranked_ids, start=1):
        if float(grades.get(doc_id, 0.0)) > 0:
            return 1.0 / i
    return 0.0


def composite_score(ndcg: float, mrr_val: float, p95_ms: float) -> float:
    """
    **Complex multi-objective metric** — quality dominates but p95 latency has meaningful tradeoff.
    Higher composite wins. Encourages smart indexing, TF-IDF/BM25, embeddings, or caching.
    """
    quality = 0.7 * ndcg + 0.3 * mrr_val
    # Stronger penalty than before (log10 to make latency matter more in demo)
    latency_penalty = 5.0 * math.log10(1.0 + max(p95_ms, 0.0))
    return round(quality * 100.0 - latency_penalty, 4)
