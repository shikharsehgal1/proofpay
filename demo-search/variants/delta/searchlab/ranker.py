"""Delta — fast title-only overlap. Decent latency, mediocre quality (won't beat Grok)."""

from __future__ import annotations

from typing import Any, Sequence


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if t}


def rank(query: str, documents: Sequence[dict[str, Any]]) -> list[str]:
    q = _tokens(query)
    scored = []
    for i, doc in enumerate(documents):
        title = _tokens(doc.get("title") or "")
        # Fast set intersection only — ignores body/tags (quality ceiling)
        s = float(len(q & title))
        scored.append((s, -i, str(doc["id"])))
    scored.sort(reverse=True)
    return [doc_id for _, __, doc_id in scored]
