from searchlab.data import CORPUS
from searchlab.ranker import rank


def test_returns_all_ids():
    ids = rank("postgres latency", CORPUS)
    assert set(ids) == {d["id"] for d in CORPUS}
    assert len(ids) == len(CORPUS)


def test_top_result_prefers_postgres_for_db_query():
    ids = rank("postgres database index latency", CORPUS)
    assert ids[0] in {"d2", "d10", "d1"}


def test_empty_query_still_returns_all():
    ids = rank("", CORPUS)
    assert len(ids) == len(CORPUS)


def test_deterministic():
    a = rank("oauth security", CORPUS)
    b = rank("oauth security", CORPUS)
    assert a == b


def test_unknown_tokens_ok():
    ids = rank("zzzznotatokenqqq", CORPUS)
    assert len(ids) == len(CORPUS)
