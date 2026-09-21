"""Application scope and structured metadata constrain every interchangeable ranker."""

from collections.abc import Sequence

import pytest

from kopii.retrieval import SearchDocument, SearchIndex


def test_search_scopes_and_filters_before_ranker_and_top_k() -> None:
    seen = []

    class Ranker:
        def score(self, query: str, documents: Sequence[SearchDocument]) -> list[float]:
            seen.append([d.id for d in documents])
            return [float(i) for i in range(len(documents))]

    docs = [
        SearchDocument("denied", "secret", {"zone": frozenset({"west"})}),
        SearchDocument("a", "first", {"zone": frozenset({"west"}), "project": frozenset({"blue"})}),
        SearchDocument(
            "b", "second", {"zone": frozenset({"east"}), "project": frozenset({"blue"})}
        ),
        SearchDocument("c", "third", {"zone": frozenset({"west"}), "project": frozenset({"blue"})}),
        SearchDocument("missing", "no attributes"),
    ]
    index = SearchIndex(docs, Ranker())
    hits = index.search(
        "record",
        allowed_ids={"a", "b", "c", "missing"},
        filters={"zone": ["west"], "project": ["blue", "green"]},
        k=1,
    )
    assert seen == [["a", "c"]]
    assert [h.document.id for h in hits] == ["c"]
    assert hits[0].to_dict() == {"id": "c", "text": "third", "score": 1.0}
    assert hits[0].to_dict(include_metadata=True)["metadata"] == {
        "zone": ["west"],
        "project": ["blue"],
    }
    assert index.search("record", allowed_ids=set()) == []
    assert index.search("record", allowed_ids={"a"}, filters={"unknown": ["west"]}) == []
    assert index.search("record", allowed_ids={"a"}, filters={"zone": []}) == []
    assert seen == [["a", "c"]]


def test_search_rejects_invalid_identity_scope_scores_and_copies_metadata() -> None:
    values = {"zone": {"west"}}
    doc = SearchDocument("a", "text", values)
    values["zone"].add("east")
    assert doc.metadata == {"zone": frozenset({"west"})}
    with pytest.raises(ValueError, match="unique"):
        SearchIndex([doc, doc])
    with pytest.raises(ValueError, match="collections"):
        SearchIndex([doc]).search("text", allowed_ids="a")

    class InvalidRanker:
        def score(self, query, documents):
            return [float("nan")]

    with pytest.raises(ValueError, match="invalid scores"):
        SearchIndex([doc], InvalidRanker()).search("text", allowed_ids=["a"])


def test_lexical_search_supports_arbitrary_unicode_and_stable_ties() -> None:
    docs = [
        SearchDocument("a", "παράδειγμα κόσμος"),
        SearchDocument("b", "배포 일정"),
        SearchDocument("c", "배포 일정"),
    ]
    index = SearchIndex(docs)
    assert [h.document.id for h in index.search("배포", allowed_ids=["a", "b", "c"])] == [
        "b",
        "c",
        "a",
    ]
    assert index.search("παράδειγμα", allowed_ids=["a", "b"])[0].document.id == "a"
