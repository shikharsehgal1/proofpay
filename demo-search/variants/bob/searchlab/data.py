"""Fixed public corpus for benchmarks (small enough for local eval)."""

from __future__ import annotations

CORPUS: list[dict] = [
    {
        "id": "d1",
        "title": "Fast API rate limiting patterns",
        "body": "Token bucket and sliding window algorithms protect public APIs from abuse.",
        "tags": ["api", "performance", "security"],
    },
    {
        "id": "d2",
        "title": "PostgreSQL indexing for latency",
        "body": "B-tree and covering indexes reduce p95 query latency on large tables.",
        "tags": ["postgres", "performance", "database"],
    },
    {
        "id": "d3",
        "title": "Grok tool calling for agents",
        "body": "Function calling lets models invoke tools, inspect results, and revise plans.",
        "tags": ["ai", "agents", "grok"],
    },
    {
        "id": "d4",
        "title": "OAuth 2.0 PKCE for SPAs and web apps",
        "body": "Proof key for code exchange secures authorization codes without embedding secrets in browsers.",
        "tags": ["oauth", "security", "auth"],
    },
    {
        "id": "d5",
        "title": "Docker sandbox isolation",
        "body": "Network-disabled containers with memory limits run untrusted candidate code safely.",
        "tags": ["docker", "security", "eval"],
    },
    {
        "id": "d6",
        "title": "NDCG ranking metrics explained",
        "body": "Normalized discounted cumulative gain measures graded relevance quality for search rankings.",
        "tags": ["search", "metrics", "ranking"],
    },
    {
        "id": "d7",
        "title": "Redis queues for background jobs",
        "body": "Use Redis lists or streams to schedule evaluation workers with retries.",
        "tags": ["redis", "jobs", "infra"],
    },
    {
        "id": "d8",
        "title": "Hidden tests against overfitting",
        "body": "Hold out adversarial queries so candidates cannot hardcode benchmark answers.",
        "tags": ["eval", "search", "integrity"],
    },
    {
        "id": "d9",
        "title": "X API webhooks and CRC checks",
        "body": "Account activity delivery requires HTTPS callbacks and challenge-response validation.",
        "tags": ["x", "webhooks", "api"],
    },
    {
        "id": "d10",
        "title": "Vector search approximations",
        "body": "HNSW and IVF trade recall for latency when embedding corpora grow large.",
        "tags": ["search", "ai", "performance"],
    },
    {
        "id": "d11",
        "title": "Accessibility checks with axe",
        "body": "Automated a11y scanners catch missing labels and contrast issues in web apps.",
        "tags": ["a11y", "web", "testing"],
    },
    {
        "id": "d12",
        "title": "Playwright end-to-end flows",
        "body": "Browser automation verifies RSVP, voting, and persistence in product evaluations.",
        "tags": ["testing", "web", "e2e"],
    },
    {
        "id": "d13",
        "title": "BM25 and TF-IDF retrieval baselines",
        "body": "Classical lexical rankers still dominate many enterprise search stacks before neural rerankers.",
        "tags": ["search", "ranking", "bm25"],
    },
    {
        "id": "d14",
        "title": "Latency budgets for interactive search",
        "body": "p95 under 50ms keeps typeahead snappy; composite metrics trade quality for speed.",
        "tags": ["performance", "search", "latency"],
    },
    {
        "id": "d15",
        "title": "Challenge-response checks for webhook endpoints",
        "body": "CRC tokens prove ownership of callback URLs before private event delivery begins.",
        "tags": ["webhooks", "security", "x"],
    },
]

# Public (visible) graded relevance: query -> {doc_id: grade 0-3}
PUBLIC_QRELS: list[dict] = [
    {
        "query": "reduce database query latency postgres",
        "grades": {"d2": 3, "d1": 1, "d10": 1, "d7": 0},
    },
    {
        "query": "oauth pkce secure login",
        "grades": {"d4": 3, "d9": 1, "d5": 1},
    },
    {
        "query": "search ranking ndcg metrics",
        "grades": {"d6": 3, "d8": 2, "d10": 2},
    },
    {
        "query": "docker sandbox untrusted code evaluation",
        "grades": {"d5": 3, "d8": 2, "d1": 0},
    },
    {
        "query": "grok agents tool calling",
        "grades": {"d3": 3, "d10": 1, "d6": 0},
    },
    {
        "query": "bm25 tf-idf lexical retrieval ranking",
        "grades": {"d13": 3, "d6": 2, "d10": 1, "d14": 1},
    },
    {
        "query": "interactive search latency budget p95",
        "grades": {"d14": 3, "d2": 2, "d1": 1, "d10": 1},
    },
]
