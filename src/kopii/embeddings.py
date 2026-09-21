"""Embedding contracts and strict vector validation, independent of study fixtures."""

import json
import math
from collections.abc import Sequence
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from kopii.retrieval import SearchDocument


class Embedder(Protocol):
    """Any local or remote provider returning vectors in input order."""

    def embed(
        self, texts: list[str], *, purpose: Literal["document", "query"]
    ) -> list[list[float]]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ValueError("Embedding endpoint redirects are not accepted")


class HttpEmbedder:
    """Explicit OpenAI-compatible HTTP adapter; no hardware or model-quality assumptions."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        batch_size: int = 32,
        timeout: float = 60,
        document_prefix: str = "",
        query_prefix: str = "",
    ) -> None:
        url = urlsplit(endpoint)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Use HTTP(S) without embedded credentials, query, or fragment")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A deployed model ID is required")
        if type(batch_size) is not int or not 1 <= batch_size <= 256:
            raise ValueError("batch_size must be an integer in [1, 256]")
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("timeout must be in (0, 120]")
        self.endpoint, self.model = endpoint, model
        self._api_key = api_key
        self.batch_size, self.timeout = batch_size, timeout
        self.prefixes = {"document": document_prefix, "query": query_prefix}

    def embed(
        self, texts: list[str], *, purpose: Literal["document", "query"]
    ) -> list[list[float]]:
        """Validate every response; transport failures never return partial vectors."""
        if purpose not in self.prefixes or any(not isinstance(text, str) for text in texts):
            raise ValueError("Invalid embedding purpose or text")
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        opener = build_opener(_NoRedirect())
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            batch = [
                self.prefixes[purpose] + text for text in texts[start : start + self.batch_size]
            ]
            body = json.dumps(
                {"model": self.model, "input": batch, "encoding_format": "float"}
            ).encode()
            request = Request(self.endpoint, data=body, headers=headers, method="POST")
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read())
            except (HTTPError, URLError, TimeoutError):
                raise RuntimeError(
                    "Embedding request failed; inspect the service privately"
                ) from None
            if not isinstance(payload, dict) or payload.get("model", self.model) != self.model:
                raise ValueError("Embedding response model mismatch")
            vectors.extend(parse_embeddings(payload, len(batch)))
        return normalize_vectors(vectors)


class VectorRanker:
    """Exact cosine scorer; only eligible documents are sent to its embedding provider.

    This stateless reference implementation embeds each candidate per call; a
    production vector store can implement Ranker with its own index and cache.
    """

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder

    def score(self, query: str, documents: Sequence[SearchDocument]) -> list[float]:
        if not documents:
            return []
        raw_documents = self.embedder.embed([d.text for d in documents], purpose="document")
        raw_query = self.embedder.embed([query], purpose="query")
        if len(raw_documents) != len(documents) or len(raw_query) != 1:
            raise ValueError("Embedding provider returned the wrong number of vectors")
        vectors = normalize_vectors(raw_documents)
        unit = normalize_vectors(raw_query)[0]
        if len(unit) != len(vectors[0]):
            raise ValueError("Query and document embedding dimensions differ")
        return [sum(a * b for a, b in zip(unit, vector, strict=True)) for vector in vectors]


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
