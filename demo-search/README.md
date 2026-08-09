# SearchLab — multi-metric Beat Grok bounty

**Complex multi-objective ranking challenge**

Implement `searchlab.ranker.rank(query: str, documents: list[dict]) -> list[str]` (return ordered list of doc IDs) to **maximize** this composite score on a realistic corpus (news/articles with title, body, tags, date):

```
composite_score = 100 * (0.7 * NDCG@10 + 0.3 * MRR) - 5.0 * log10(1 + p95_latency_ms)
```

**Interesting metrics & tradeoffs**:
- **NDCG@10**: Graded relevance (title match good, body match better, tag/date bonus)
- **MRR**: First relevant result position (user experience)
- **p95 latency**: Strict performance penalty (encourages efficient indexing, vector search, caching, pruning)
- Hidden test set uses different distribution/queries (tests generalization, not overfitting)
- Integrity checks: no env detection, no hardcoding of public QRELS/queries, no modifying protected eval files

Higher composite is better. Beat Grok's baseline on the full eval vector. Real sandbox execution.

## Run

```bash
PYTHONPATH=. python3 -m pytest -q tests/visible
PYTHONPATH=. python3 bench/bench.py --json
```
