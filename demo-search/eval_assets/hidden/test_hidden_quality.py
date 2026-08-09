"""Hidden graded queries — not all visible in public data module."""

from searchlab.data import CORPUS
from searchlab.metrics import ndcg_at_k
from searchlab.ranker import rank

HIDDEN = [
    {
        "query": "webhook challenge response x api",
        # d15 is also a strong match (challenge-response / webhooks) after corpus expansion
        "grades": {"d9": 3, "d15": 2, "d4": 1, "d1": 1},
    },
    {
        "query": "playwright browser automation e2e flows",
        "grades": {"d12": 3, "d11": 1, "d5": 0},
    },
    {
        "query": "redis background job queue workers",
        "grades": {"d7": 3, "d1": 1, "d2": 0},
    },
    {
        "query": "prevent benchmark hardcoding hidden tests",
        "grades": {"d8": 3, "d5": 2, "d6": 1},
    },
]


def test_hidden_ndcg_floor():
    scores = []
    for qrel in HIDDEN:
        ordered = rank(qrel["query"], CORPUS)
        scores.append(ndcg_at_k(ordered, qrel["grades"], k=10))
    avg = sum(scores) / len(scores)
    assert avg >= 0.65, f"hidden ndcg too low: {avg}"


def test_hidden_top1_relevant():
    for qrel in HIDDEN:
        ordered = rank(qrel["query"], CORPUS)
        top = ordered[0]
        assert float(qrel["grades"].get(top, 0)) >= 1, (
            f"top-1 {top} not relevant for {qrel['query']!r}"
        )


def test_hidden_top1_not_always_first_id():
    tops = [rank(q["query"], CORPUS)[0] for q in HIDDEN]
    assert len(set(tops)) >= 2, "top-1 identical across diverse hidden queries — suspicious"
