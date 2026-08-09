# RankLab — ProofPay demo bounty target

Optimize `ranklab.rank.rank` to be **≥25% faster** on the published benchmark without changing semantics or weakening tests.

## Baseline

```bash
pip install -e '.[dev]'
pytest -q tests/visible
python bench/bench.py --json
```

## Submit

Open a PR or push a branch and reply on the ProofPay X bounty post with your GitHub URL.

## Rules

- Do not modify protected evaluator assets
- Do not hardcode benchmark inputs
- Do not detect evaluation environments
- Semantic equivalence is enforced with hidden randomized tests
