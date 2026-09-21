"""Provider-independent search over released text and private categorical metadata."""

import math
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Protocol


def categories(values: Collection[str]) -> frozenset[str]:
    """Validate explicit string sets rather than treating a string as characters."""
    if isinstance(values, str) or any(not isinstance(v, str) or not v for v in values):
        raise ValueError("Categories and document IDs must be collections of nonempty strings")
    return frozenset(values)


@dataclass(frozen=True)
class SearchDocument:
    """Released text plus private index metadata, with no original name surfaces."""

    id: str
    text: str
    metadata: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id or not isinstance(self.text, str):
            raise ValueError("A document requires a nonempty ID and string text")
        if any(not isinstance(key, str) or not key for key in self.metadata):
            raise ValueError("Metadata field names must be nonempty strings")
        object.__setattr__(
            self, "metadata", MappingProxyType({k: categories(v) for k, v in self.metadata.items()})
        )

    def to_dict(self, *, include_metadata: bool = False) -> dict[str, Any]:
        """Omit private attributes unless the caller explicitly requests index export."""
        result: dict[str, Any] = {"id": self.id, "text": self.text}
        if include_metadata:
            result["metadata"] = {k: sorted(v) for k, v in self.metadata.items()}
        return result


class Ranker(Protocol):
    """Score only the supplied, already authorized and filtered documents."""

    def score(self, query: str, documents: Sequence[SearchDocument]) -> list[float]:
        """Return one finite score per input document, in the same order."""
        ...


def character_bigrams(text: str) -> list[str]:
    """Unicode letters/digits, without punctuation; a baseline, not linguistic parsing."""
    clean = "".join(char for char in text.casefold() if char.isalnum())
    return [clean[i : i + 2] for i in range(len(clean) - 1)]


class LexicalRanker:
    """Stateless BM25 over eligible documents with a replaceable tokenizer."""

    def __init__(
        self,
        tokenizer: Callable[[str], list[str]] = character_bigrams,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("Invalid BM25 parameters")
        self.tokenizer, self.k1, self.b = tokenizer, k1, b

    def score(self, query: str, documents: Sequence[SearchDocument]) -> list[float]:
        if not documents:
            return []
        vectors = [Counter(self.tokenizer(d.text)) for d in documents]
        lengths = [sum(vector.values()) for vector in vectors]
        average = sum(lengths) / len(lengths) or 1.0
        frequency: Counter[str] = Counter()
        for vector in vectors:
            frequency.update(vector.keys())
        terms = set(self.tokenizer(query))
        scores = []
        for vector, length in zip(vectors, lengths, strict=True):
            normalizer = self.k1 * (1 - self.b + self.b * length / average)
            scores.append(
                sum(
                    math.log(1 + (len(documents) - frequency[t] + 0.5) / (frequency[t] + 0.5))
                    * vector[t]
                    * (self.k1 + 1)
                    / (vector[t] + normalizer)
                    for t in terms
                    if vector[t]
                )
            )
        return scores


@dataclass(frozen=True)
class SearchHit:
    """One eligible result; serialization hides categorical metadata by default."""

    document: SearchDocument
    score: float

    def to_dict(self, *, include_metadata: bool = False) -> dict[str, Any]:
        return {**self.document.to_dict(include_metadata=include_metadata), "score": self.score}


class SearchIndex:
    """In-memory reference search; authorization must be supplied by the application.

    Filters use AND between fields and OR within each field. Neither document
    authorization nor filter values are inferred from query text. This class
    does not authenticate a caller or protect an on-disk index.
    """

    def __init__(self, documents: Sequence[SearchDocument], ranker: Ranker | None = None) -> None:
        self.documents = tuple(documents)
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("Document IDs must be unique")
        self.ranker = ranker if ranker is not None else LexicalRanker()

    def search(
        self,
        query: str,
        *,
        allowed_ids: Collection[str],
        filters: Mapping[str, Collection[str]] | None = None,
        k: int = 5,
    ) -> list[SearchHit]:
        """Apply caller scope and metadata filters before any ranker sees documents."""
        if not isinstance(query, str) or not query.strip() or type(k) is not int or k <= 0:
            raise ValueError("Search requires nonempty query text and positive integer k")
        allowed = categories(allowed_ids)
        selected = {key: categories(value) for key, value in (filters or {}).items()}
        if any(not isinstance(key, str) or not key for key in selected):
            raise ValueError("Filter fields must be nonempty strings")
        candidates = [
            d
            for d in self.documents
            if d.id in allowed
            and all(
                bool(d.metadata.get(key, frozenset()) & values) for key, values in selected.items()
            )
        ]
        if not candidates:
            return []
        scores = self.ranker.score(query, candidates)
        if len(scores) != len(candidates) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in scores
        ):
            raise ValueError("Ranker returned invalid scores")
        ordered = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        return [SearchHit(candidates[i], scores[i]) for i in ordered[:k]]
