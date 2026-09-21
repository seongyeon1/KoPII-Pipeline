"""Externally supplied qrels are validated before retrieval and scoring."""

import json

import pytest

from kopii.research.search import evaluate_search
from kopii.retrieval import SearchDocument, SearchIndex


def test_search_evaluation_measures_misses_and_truncated_ranks_without_query_text(tmp_path) -> None:
    index = SearchIndex([SearchDocument("a", "deploy"), SearchDocument("b", "cost")])
    path = tmp_path / "queries.jsonl"
    rows = [
        {"id": "hit", "text": "deploy", "allowed_ids": ["a", "b"], "relevant_ids": ["a", "b"]},
        {"id": "miss", "text": "deploy", "allowed_ids": ["a", "b"], "relevant_ids": ["b"]},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    report = evaluate_search(index, path, k=1)
    assert report["metrics"] == {
        "recall_at_k": 0.25,
        "precision_at_k": 0.5,
        "mrr_at_k": 0.5,
        "empty_result_rate": 0,
    }
    assert "deploy" not in json.dumps(report)
    rows[0]["allowed_ids"] = ["a"]
    path.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match="authorized"):
        evaluate_search(index, path)
