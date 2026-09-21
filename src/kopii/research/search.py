"""Evaluate user-supplied retrieval judgments without fictional-world dependencies."""

import json
from pathlib import Path
from typing import Any

from kopii.research.data import file_hash
from kopii.retrieval import SearchIndex, categories


def evaluate_search(index: SearchIndex, queries_path: Path, k: int = 5) -> dict[str, Any]:
    """Macro recall/precision/RR at k over explicit authorized relevance judgments.

    Input queries require id, text, allowed_ids and relevant_ids; filters are
    optional. These declared scopes are evaluation data, not authentication.
    Outputs contain aggregate scores and a data hash, not query text or IDs.
    """
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")
    known_ids = {d.id for d in index.documents}
    rows = []
    seen = set()
    for line in queries_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        required = {"id", "text", "allowed_ids", "relevant_ids"}
        if (
            not isinstance(row, dict)
            or not required <= set(row)
            or set(row) - required - {"filters"}
        ):
            raise ValueError("Invalid retrieval query fields")
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            raise ValueError("Query IDs must be nonempty and unique")
        if not isinstance(row["text"], str) or not row["text"].strip():
            raise ValueError("Query text must be nonempty")
        if not isinstance(row["allowed_ids"], list) or not isinstance(row["relevant_ids"], list):
            raise ValueError("Query scopes and relevance must be arrays")
        allowed, relevant = categories(row["allowed_ids"]), categories(row["relevant_ids"])
        if not relevant or not relevant <= allowed or not allowed <= known_ids:
            raise ValueError("Relevance must be nonempty and within known authorized documents")
        filters = row.get("filters", {})
        if not isinstance(filters, dict) or any(not isinstance(v, list) for v in filters.values()):
            raise ValueError("Filters must map field names to arrays")
        for key, value in filters.items():
            if not isinstance(key, str) or not key:
                raise ValueError("Filter field names must be nonempty")
            categories(value)
        seen.add(row["id"])
        rows.append(row)
    if not rows:
        raise ValueError("Retrieval evaluation requires at least one query")
    values = []
    for row in rows:
        hits = index.search(
            row["text"], allowed_ids=row["allowed_ids"], filters=row.get("filters"), k=k
        )
        relevant = categories(row["relevant_ids"])
        ranked = [hit.document.id for hit in hits]
        correct = len(set(ranked) & relevant)
        first = next((i + 1 for i, key in enumerate(ranked) if key in relevant), None)
        values.append(
            {
                "recall_at_k": correct / len(relevant),
                "precision_at_k": correct / k,
                "mrr_at_k": 1 / first if first else 0.0,
                "empty_result_rate": float(not hits),
            }
        )
    return {
        "queries": len(rows),
        "k": k,
        "query_sha256": file_hash(queries_path),
        "metrics": {key: sum(row[key] for row in values) / len(values) for key in values[0]},
        "scope": (
            "Macro averages over supplied judgments; precision denominator is k; "
            "RR is truncated at k. No privacy or production-performance claim."
        ),
    }
