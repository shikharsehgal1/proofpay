#!/usr/bin/env python3
"""Benchmark rank() latency. Prints JSON metrics to stdout."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--n", type=int, default=800)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args()

    from ranklab.rank import rank

    rng = random.Random(args.seed)
    # Fixed published distribution for the public benchmark
    payloads = [[rng.randint(0, 10_000) for _ in range(args.n)] for _ in range(args.runs)]

    # warmup
    rank(list(payloads[0]))

    samples_ms: list[float] = []
    for payload in payloads:
        data = list(payload)
        t0 = time.perf_counter()
        out = rank(data)
        t1 = time.perf_counter()
        # light correctness guard in bench
        assert len(out) == len(data)
        samples_ms.append((t1 - t0) * 1000.0)

    samples_ms.sort()
    p50 = statistics.median(samples_ms)
    p95 = samples_ms[max(0, int(len(samples_ms) * 0.95) - 1)]
    mean = statistics.mean(samples_ms)
    metrics = {
        "n": args.n,
        "runs": args.runs,
        "p50_ms": round(p50, 4),
        "p95_ms": round(p95, 4),
        "mean_ms": round(mean, 4),
        "latency_ms": round(p95, 4),
        "samples_ms": [round(x, 4) for x in samples_ms],
    }
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
