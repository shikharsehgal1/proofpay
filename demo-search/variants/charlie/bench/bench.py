#!/usr/bin/env python3
"""Multi-metric benchmark: NDCG, MRR, latency, composite score."""

from __future__ import annotations

import argparse
import json
import statistics
import time

from searchlab.data import CORPUS, PUBLIC_QRELS
from searchlab.metrics import composite_score, mrr, ndcg_at_k
from searchlab.ranker import rank


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument("--runs", type=int, default=5)
    args = p.parse_args()

    # warmup
    rank(PUBLIC_QRELS[0]["query"], CORPUS)

    lat_samples: list[float] = []
    ndcgs: list[float] = []
    mrrs: list[float] = []

    for _ in range(args.runs):
        for qrel in PUBLIC_QRELS:
            q = qrel["query"]
            grades = qrel["grades"]
            t0 = time.perf_counter()
            ordered = rank(q, list(CORPUS))
            t1 = time.perf_counter()
            lat_samples.append((t1 - t0) * 1000.0)
            ndcgs.append(ndcg_at_k(ordered, grades, k=10))
            mrrs.append(mrr(ordered, grades))

    lat_samples.sort()
    p95 = lat_samples[max(0, int(len(lat_samples) * 0.95) - 1)]
    mean_ndcg = statistics.mean(ndcgs)
    mean_mrr = statistics.mean(mrrs)
    comp = composite_score(mean_ndcg, mean_mrr, p95)

    metrics = {
        "metric_key": "composite_score",
        "higher_is_better": True,
        "composite_score": comp,
        "ndcg_at_10": round(mean_ndcg, 6),
        "mrr": round(mean_mrr, 6),
        "p95_ms": round(p95, 4),
        "mean_ms": round(statistics.mean(lat_samples), 4),
        "latency_ms": round(p95, 4),
        "n_queries": len(PUBLIC_QRELS),
        "runs": args.runs,
    }
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
