"""Retrieval evidence must respect filters and validate vectors before scoring."""

import pytest

from kopii.research.retrieval import (
    DenseIndex,
    filter_ranking,
    normalize_vectors,
    parse_embeddings,
    query_category,
)


def test_filter_applies_before_top_k_and_denies_unapproved_scope() -> None:
    metadata = [frozenset(), frozenset({"A"}), frozenset({"B"}), frozenset({"A"})]
    assert filter_ranking([0, 2, 3, 1], metadata, "A", frozenset({"A"}))[:1] == [3]
    assert filter_ranking([0, 2, 3, 1], metadata, "A", frozenset({"B"})) == []
    assert filter_ranking([0], metadata, "A", frozenset({"A"})) == []


def test_query_filter_reads_only_text_and_rejects_ambiguous_categories() -> None:
    assert query_category("상반기 고객지원팀의 승인 기록", "team") == "고객지원팀"
    assert query_category("상반기 승인 기록", "team") is None
    with pytest.raises(ValueError, match="at most one"):
        query_category("고객지원팀과 업무기획팀 기록", "team")


def test_cosine_ranking_normalizes_scale_and_breaks_ties_by_index() -> None:
    index = DenseIndex([[0, 10], [1, 0], [5, 0], [-1, 0]])
    assert index.rank([10, 0]) == [1, 2, 0, 3]
    with pytest.raises(ValueError, match="dimensions differ"):
        index.rank([1, 0, 0])


@pytest.mark.parametrize(
    "vectors", [[], [[]], [[0, 0]], [[1, 0], [1]], [[float("nan")]], [[float("inf")]], [[True]]]
)
def test_corrupt_vectors_are_rejected(vectors) -> None:
    with pytest.raises(ValueError):
        normalize_vectors(vectors)


def test_embedding_response_restores_input_order_and_rejects_duplicates() -> None:
    payload = {"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 0]}]}
    assert parse_embeddings(payload, 2) == [[1, 0], [0, 1]]
    with pytest.raises(ValueError, match="count mismatch"):
        parse_embeddings(payload, 3)
    payload["data"][0]["index"] = 0
    with pytest.raises(ValueError, match="duplicate"):
        parse_embeddings(payload, 2)
