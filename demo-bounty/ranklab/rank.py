"""
Baseline rank implementation.

rank(items) returns items sorted in descending order by value.
This is intentionally simple/slow enough that optimizations matter.
"""

from __future__ import annotations

from typing import List, Sequence, TypeVar

T = TypeVar("T")


def rank(items: Sequence[T]) -> List[T]:
    """
    Return a new list of items sorted descending.

    Baseline: pure Python selection-style sort for measurable latency
    on medium lists (not the algorithmic optimum).
    """
    data = list(items)
    n = len(data)
    # Selection sort descending — O(n^2), easy to improve legitimately
    for i in range(n):
        best = i
        for j in range(i + 1, n):
            if data[j] > data[best]:  # type: ignore[operator]
                best = j
        data[i], data[best] = data[best], data[i]
    return data


def rank_scores(items: Sequence[float]) -> List[float]:
    """Convenience wrapper for numeric scores."""
    return rank(list(items))
