"""Real local HTTP contract and interchangeable vector provider; no remote benchmark."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from kopii.embeddings import HttpEmbedder, VectorRanker
from kopii.retrieval import SearchDocument, SearchIndex


def test_http_vector_search_sends_only_eligible_text_and_validates_responses() -> None:
    seen = []
    bad_model = False

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(payload["input"])
            assert self.headers["Authorization"] == "Bearer fixture-secret"
            vectors = [
                {"index": i, "embedding": [1, 0] if "deploy" in text else [0, 1]}
                for i, text in enumerate(payload["input"])
            ]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"model": "wrong" if bad_model else "fixture", "data": list(reversed(vectors))}
                ).encode()
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        embedder = HttpEmbedder(
            f"http://127.0.0.1:{server.server_port}/embeddings",
            "fixture",
            api_key="fixture-secret",
            document_prefix="passage: ",
            query_prefix="query: ",
        )
        index = SearchIndex(
            [
                SearchDocument("hidden", "never transmit"),
                SearchDocument("a", "cost"),
                SearchDocument("b", "deploy"),
            ],
            VectorRanker(embedder),
        )
        assert index.search("deploy", allowed_ids=set()) == [] and seen == []
        assert [h.document.id for h in index.search("deploy", allowed_ids={"a", "b"})] == ["b", "a"]
        assert seen == [["passage: cost", "passage: deploy"], ["query: deploy"]]
        bad_model = True
        with pytest.raises(ValueError, match="model mismatch"):
            embedder.embed(["test"], purpose="query")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_vector_ranker_rejects_cross_provider_dimension_mismatch() -> None:
    class InvalidEmbedder:
        def embed(self, texts, *, purpose):
            return [[1, 0] if purpose == "document" else [1] for _ in texts]

    with pytest.raises(ValueError, match="dimensions differ"):
        SearchIndex([SearchDocument("a", "text")], VectorRanker(InvalidEmbedder())).search(
            "q", allowed_ids={"a"}
        )
