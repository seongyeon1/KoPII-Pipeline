"""Controlled retrieval baselines; metadata is not assumed invisible to search users."""

from kopii.embeddings import DenseIndex as DenseIndex
from kopii.embeddings import normalize_vectors as normalize_vectors
from kopii.embeddings import parse_embeddings as parse_embeddings
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
