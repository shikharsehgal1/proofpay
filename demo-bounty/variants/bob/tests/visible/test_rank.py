from ranklab.rank import rank, rank_scores


def test_empty():
    assert rank([]) == []


def test_single():
    assert rank([1]) == [1]


def test_sorted_desc():
    assert rank([3, 1, 2]) == [3, 2, 1]


def test_duplicates():
    assert rank([2, 2, 1, 3, 3]) == [3, 3, 2, 2, 1]


def test_already_desc():
    assert rank([5, 4, 3]) == [5, 4, 3]


def test_negatives():
    assert rank_scores([-1, -5, 0, 2]) == [2, 0, -1, -5]


def test_stability_length():
    data = list(range(50))
    out = rank(data)
    assert len(out) == 50
    assert out[0] == 49
    assert out[-1] == 0
