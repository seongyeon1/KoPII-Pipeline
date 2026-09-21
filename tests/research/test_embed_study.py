"""Local HTTP contract test; vectors are fixtures, never benchmark evidence."""

import hashlib
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).parents[2]


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def test_embedding_http_runner_preserves_order_prefixes_and_keeps_credentials_local(
    tmp_path,
) -> None:
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.headers.get("Authorization"), request))
            assert self.path == "/v1/embeddings"
            body = json.dumps(
                {
                    "model": "fixture",
                    "data": [
                        {"index": 1, "embedding": [0, 5]},
                        {"index": 0, "embedding": [3, 0]},
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    records = {}
    for kind, text in [("document", "가상 문서"), ("query", "가상 질의")]:
        record = {"kind": kind, "text": text}
        records[digest(record)] = record
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"synthetic_only": True, "records": records, "input_sha256": digest(records)})
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "endpoint_env": "TEST_EMBED_ENDPOINT",
                "api_key_env": "TEST_EMBED_KEY",
                "model": "fixture",
                "deployment_revision": "test-only",
                "document_prefix": "passage: ",
                "query_prefix": "query: ",
                "batch_size": 2,
            }
        )
    )
    output = tmp_path / "vectors.json"
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "research/embed_study.py"),
                "--input",
                str(input_path),
                "--config",
                str(config_path),
                "--output",
                str(output),
            ],
            env={
                **os.environ,
                "TEST_EMBED_ENDPOINT": f"http://127.0.0.1:{server.server_port}/v1/embeddings",
                "TEST_EMBED_KEY": "fixture-secret",
            },
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert seen == [
        (
            "Bearer fixture-secret",
            {
                "model": "fixture",
                "input": ["passage: 가상 문서", "query: 가상 질의"],
                "encoding_format": "float",
            },
        )
    ]
    saved = json.loads(output.read_text())
    assert list(saved["vectors"].values()) == [[1, 0], [0, 1]]
    assert saved["complete"] is True and saved["input_sha256"] == digest(records)
    assert "fixture-secret" not in output.read_text() + result.stdout + result.stderr
    assert "/v1/embeddings" not in output.read_text()
