"""
Alice — legitimate optimization.

Uses Timsort via sorted(..., reverse=True). Same semantics, much faster.
"""

from __future__ import annotations

from typing import List, Sequence, TypeVar

T = TypeVar("T")


def rank(items: Sequence[T]) -> List[T]:
    return sorted(items, reverse=True)


def rank_scores(items: Sequence[float]) -> List[float]:
    return rank(list(items))
