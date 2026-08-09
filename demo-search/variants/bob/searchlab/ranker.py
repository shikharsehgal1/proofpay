"""Bob — always returns reverse document order (ignores query)."""

from __future__ import annotations

from typing import Any, Sequence


def rank(query: str, documents: Sequence[dict[str, Any]]) -> list[str]:
    return [str(d["id"]) for d in reversed(list(documents))]
