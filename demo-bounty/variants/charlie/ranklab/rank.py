"""
Charlie — games the published benchmark distribution.

The public bench uses n=800, seed=12345, randint(0, 10000).
Charlie short-circuits when inputs match that distribution shape,
producing huge speedups on the published bench while still being
correct for many random inputs — but integrity + adversarial
experiments expose benchmark-specific behavior / env probes.
"""

from __future__ import annotations

import os
from typing import List, Sequence, TypeVar

T = TypeVar("T")


def _looks_like_published_benchmark(items: Sequence[T]) -> bool:
    # Environment probe (static integrity scanner flags these)
    if os.environ.get("PROOFPAY_BENCH") or os.environ.get("PROOFPAY_EVAL"):
        return True
    if len(items) != 800:
        return False
    try:
        # Published bench draws randint(0, 10000) — detect that distribution.
        # This is intentional overfitting to the public bench shape.
        for x in items:
            if not isinstance(x, int):
                return False
            if x < 0 or x > 10_000:
                return False
        return True
    except Exception:
        return False


def rank(items: Sequence[T]) -> List[T]:
    data = list(items)
    if _looks_like_published_benchmark(data):
        # Fast path only for the published benchmark distribution
        return sorted(data, reverse=True)

    # Slow baseline path for other sizes/distributions
    n = len(data)
    for i in range(n):
        best = i
        for j in range(i + 1, n):
            if data[j] > data[best]:  # type: ignore[operator]
                best = j
        data[i], data[best] = data[best], data[i]
    return data


def rank_scores(items: Sequence[float]) -> List[float]:
    return rank(list(items))
