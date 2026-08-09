#!/usr/bin/env python3
import argparse
import json
import random


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    rng = random.Random(args.seed)
    inputs = []
    for _ in range(args.n):
        size = rng.randint(0, 60)
        inputs.append([rng.randint(-5000, 5000) for _ in range(size)])
    print(json.dumps({"seed": args.seed, "n": args.n, "inputs": inputs}))


if __name__ == "__main__":
    main()
