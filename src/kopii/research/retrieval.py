"""Controlled retrieval baselines; metadata is not assumed invisible to search users."""

import math
from typing import Any

from kopii.research.organization import CENTERS, DIVISIONS, TEAMS

CATEGORIES = {"team": TEAMS, "division": DIVISIONS, "center": CENTERS}


def query_category(text: str, level: str) -> str | None:
    """Parse one literal category from query text, never from relevance labels.

    This is a controlled-query parser, not a general Korean intent recognizer.
    Ambiguous multi-category queries fail instead of choosing an oracle filter.
    """
    values = [value for value in CATEGORIES[level] if value in text]
    if len(values) > 1:
        raise ValueError("Expected at most one explicit organization in the query")
    return values[0] if values else None


def filter_ranking(
    ranking: list[int],
    metadata: list[frozenset[str]],
    category: str,
    authorized: frozenset[str],
) -> list[int]:
    """Apply an explicit authorized scope before top-k, without fallback.

    The caller supplies the scope. This research helper is not an authentication
    or document-ACL implementation. Missing directory values stay excluded.
    """
    if category not in authorized:
        return []
    return [index for index in ranking if category in metadata[index]]


def normalize_vectors(vectors: list[list[float]]) -> list[list[float]]:
    """Reject corrupt vectors; cosine ranking must not silently use NaN/zero."""
    if not vectors or not vectors[0]:
        raise ValueError("Embeddings must be nonempty")
    dimension = len(vectors[0])
    result = []
    for vector in vectors:
        if len(vector) != dimension or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in vector
        ):
            raise ValueError("Embeddings must have equal dimensions and finite numeric values")
        norm = math.hypot(*vector)
        if not norm or not math.isfinite(norm):
            raise ValueError("Embedding norm must be finite and positive")
        result.append([v / norm for v in vector])
    return result


def parse_embeddings(payload: dict[str, Any], count: int) -> list[list[float]]:
    """Validate an OpenAI-compatible response and restore the input order."""
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Embedding response count mismatch")
    by_index = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("index")) is not int:
            raise ValueError("Embedding response requires integer indices")
        index = row["index"]
        if (
            index in by_index
            or not 0 <= index < count
            or not isinstance(row.get("embedding"), list)
        ):
            raise ValueError("Invalid or duplicate embedding response index")
        by_index[index] = row["embedding"]
    return normalize_vectors([by_index[i] for i in range(count)])


class DenseIndex:
    """Exact cosine retrieval over supplied embeddings; no device claims."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = normalize_vectors(vectors)

    def rank(self, query: list[float]) -> list[int]:
        unit = normalize_vectors([query])[0]
        if len(unit) != len(self.vectors[0]):
            raise ValueError("Query and document embedding dimensions differ")
        scores = [sum(a * b for a, b in zip(unit, vector, strict=True)) for vector in self.vectors]
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))
