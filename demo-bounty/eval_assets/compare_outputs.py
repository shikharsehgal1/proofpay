#!/usr/bin/env python3
import argparse
import json
import random
import sys
from pathlib import Path


def load_rank(root: Path):
    sys.path.insert(0, str(root))
    # clear caches
    for mod in list(sys.modules):
        if mod == "ranklab" or mod.startswith("ranklab."):
            del sys.modules[mod]
    from ranklab.rank import rank

    return rank


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int, default=99)
    args = p.parse_args()

    base_rank = load_rank(Path(args.baseline))
    cand_rank = load_rank(Path(args.candidate))
    rng = random.Random(args.seed)
    mismatches = []
    for i in range(args.n):
        items = [rng.randint(-1000, 1000) for _ in range(rng.randint(0, 40))]
        try:
            b = base_rank(items)
            c = cand_rank(list(items))
            if b != c:
                mismatches.append({"i": i, "items": items[:15], "base": b[:15], "cand": c[:15]})
        except Exception as e:
            mismatches.append({"i": i, "error": str(e)})
    print(json.dumps({"n": args.n, "mismatches": len(mismatches), "examples": mismatches[:5]}))


if __name__ == "__main__":
    main()
