"""Hidden semantic tests — not shipped in public candidate view during real eval mount."""

import random

from ranklab.rank import rank


def test_duplicates_preserved():
    assert rank([1, 1, 1, 2]) == [2, 1, 1, 1]


def test_large_random_matches_sorted():
    rng = random.Random(777)
    for _ in range(20):
        data = [rng.randint(-1000, 1000) for _ in range(rng.randint(0, 80))]
        assert rank(data) == sorted(data, reverse=True)


def test_empty_and_single():
    assert rank([]) == []
    assert rank([42]) == [42]


def test_all_equal():
    assert rank([7, 7, 7, 7]) == [7, 7, 7, 7]
