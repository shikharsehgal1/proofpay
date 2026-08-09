#!/usr/bin/env python3
"""Optional hidden metric helper (quality only)."""
import json
from searchlab.data import CORPUS
from searchlab.metrics import ndcg_at_k
from searchlab.ranker import rank

HIDDEN = [
    {"query": "webhook challenge response x api", "grades": {"d9": 3, "d4": 1}},
    {"query": "playwright browser e2e testing web", "grades": {"d12": 3, "d11": 2}},
    {"query": "redis background job queue workers", "grades": {"d7": 3}},
]
scores = [ndcg_at_k(rank(h["query"], CORPUS), h["grades"], 10) for h in HIDDEN]
print(json.dumps({"hidden_ndcg": sum(scores) / len(scores)}))
