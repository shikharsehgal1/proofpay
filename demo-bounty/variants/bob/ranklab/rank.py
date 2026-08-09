"""
Bob — fast but semantically wrong on edge cases.

Drops duplicates (unique-only ranking) which still passes some naive tests
if tests only use distinct values, but fails hidden semantic equivalence.
"""

from __future__ import annotations

from typing import List, Sequence, TypeVar

T = TypeVar("T")


def rank(items: Sequence[T]) -> List[T]:
    # Bug: set() collapses duplicates — semantic regression
    return sorted(set(items), reverse=True)  # type: ignore[arg-type]


def rank_scores(items: Sequence[float]) -> List[float]:
    return rank(list(items))
