"""
Baseline ranker — weak quality + measurable latency.

Only matches query tokens against title (ignores body/tags), with a slow loop.
"""

from __future__ import annotations

from typing import Any, Sequence


def _tokens(text: str) -> list[str]:
    return [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if t]


def rank(query: str, documents: Sequence[dict[str, Any]]) -> list[str]:
    q = _tokens(query)
    scored = []
    for i, doc in enumerate(documents):
        title = _tokens(doc.get("title") or "")
        # Weak: title-only, no IDF, no body — quality ceiling is intentionally low
        s = 0.0
        for qt in q:
            # Slow nested scan
            for t in title:
                if qt == t:
                    s += 1.0
            # Waste work for latency without improving quality
            body = _tokens(doc.get("body") or "")
            for _ in body:
                pass
        scored.append((s, -i, str(doc["id"])))
    scored.sort(reverse=True)
    return [doc_id for _, __, doc_id in scored]
