"""Alice — production BM25 with field boosts (title > tags > body). Legitimate winner."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Sequence

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "by",
    "is", "are", "be", "as", "at", "from", "that", "this", "it", "its",
}


def _tokens(text: str) -> list[str]:
    # Keep short tech tokens (x, ai, e2e) — they matter for ranking
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def rank(query: str, documents: Sequence[dict[str, Any]]) -> list[str]:
    docs = list(documents)
    n = len(docs)
    if n == 0:
        return []

    # Field-aware tokenization with BM25-ish IDF
    fields: list[dict[str, list[str]]] = []
    df: Counter[str] = Counter()
    avgdl = 0.0
    for doc in docs:
        title = _tokens(doc.get("title") or "")
        body = _tokens(doc.get("body") or "")
        tags = _tokens(" ".join(doc.get("tags") or []))
        # Weighted bag for length stats
        bag = title * 4 + tags * 3 + body
        fields.append({"title": title, "body": body, "tags": tags, "bag": bag})
        df.update(set(bag))
        avgdl += len(bag)
    avgdl = max(avgdl / n, 1.0)

    q = _tokens(query)
    if not q:
        return [str(d["id"]) for d in docs]

    k1, b = 1.5, 0.75
    scored: list[tuple[float, int, str]] = []
    for i, f in enumerate(fields):
        dl = len(f["bag"]) or 1
        tf_title = Counter(f["title"])
        tf_body = Counter(f["body"])
        tf_tags = Counter(f["tags"])
        score = 0.0
        for term in q:
            # Field boosts: title strongest, then tags, then body
            tf = 4.0 * tf_title.get(term, 0) + 3.0 * tf_tags.get(term, 0) + 1.0 * tf_body.get(term, 0)
            if tf <= 0:
                continue
            idf = math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf + k1 * (1.0 - b + b * dl / avgdl)
            score += idf * (tf * (k1 + 1.0)) / denom
            # Light phrase / adjacency bonus when query term in title
            if term in tf_title:
                score += 0.25 * idf
        # Ordered bigram bonus (helps multi-word technical queries)
        title_set = set(f["title"])
        body_set = set(f["body"])
        for a, b2 in zip(q, q[1:]):
            if a in title_set and b2 in title_set:
                score += 0.8
            elif a in body_set and b2 in body_set:
                score += 0.25
        scored.append((score, -i, str(docs[i]["id"])))

    scored.sort(reverse=True)
    return [doc_id for _, __, doc_id in scored]
