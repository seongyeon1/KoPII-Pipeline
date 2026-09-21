"""Explicitly execute synthetic study inputs against a configured embedding API.

No endpoint, credentials, or private text are stored in the public configuration.
The deployment revision is operator-provided, not remotely attested by this tool.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from kopii.research.data import file_hash
from kopii.research.experiment import atomic_json
from kopii.research.retrieval import normalize_vectors, parse_embeddings


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Embedding endpoint redirects are not accepted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new output path; embedding runs are not overwritten")
    config = json.loads(args.config.read_text())
    inputs = json.loads(args.input.read_text())
    if inputs.get("synthetic_only") is not True:
        raise ValueError("This runner accepts only the synthetic-study export")
    encoded = json.dumps(inputs["records"], sort_keys=True, ensure_ascii=False).encode()
    if hashlib.sha256(encoded).hexdigest() != inputs["input_sha256"]:
        raise ValueError("Input record hash mismatch")
    for key, record in inputs["records"].items():
        if record["kind"] not in {"document", "query"} or not isinstance(record["text"], str):
            raise ValueError("Invalid embedding record")
        if (
            hashlib.sha256(
                json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            != key
        ):
            raise ValueError("Input record identity mismatch")
    for field in ("model", "deployment_revision"):
        if not config.get(field) or config[field].startswith("REPLACE_"):
            raise ValueError(f"Configure actual {field} before execution")
    endpoint = os.environ[config["endpoint_env"]]
    url = urlsplit(endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Use a plain HTTP(S) endpoint without embedded credentials or query")
    headers = {"Content-Type": "application/json"}
    if config.get("api_key_env"):
        headers["Authorization"] = "Bearer " + os.environ[config["api_key_env"]]
    batch_size = config.get("batch_size", 32)
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError("batch_size must be an integer in [1, 256]")
    timeout = config.get("timeout_seconds", 60)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("timeout_seconds must be an integer in [1, 120]")
    opener = build_opener(NoRedirect())
    vectors, durations = {}, []
    records = list(inputs["records"].items())
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        texts = [config.get(f"{r['kind']}_prefix", "") + r["text"] for _, r in batch]
        body = json.dumps(
            {"model": config["model"], "input": texts, "encoding_format": "float"}
        ).encode()
        request = Request(endpoint, data=body, headers=headers, method="POST")
        begin = time.perf_counter()
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError):
            raise RuntimeError("Embedding request failed; inspect the service privately") from None
        durations.append(time.perf_counter() - begin)
        if payload.get("model", config["model"]) != config["model"]:
            raise ValueError("Embedding response model differs from requested model")
        values = parse_embeddings(payload, len(batch))
        vectors.update({key: vector for (key, _), vector in zip(batch, values, strict=True)})
        print(f"Embedded {len(vectors)}/{len(records)} synthetic inputs", flush=True)
    normalize_vectors(list(vectors.values()))  # Cross-batch dimension check.
    provenance = {
        "model": config["model"],
        "deployment_revision": config["deployment_revision"],
        "revision_attestation": "operator supplied; server weights not independently verified",
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
        "config_sha256": file_hash(args.config),
        "runner_sha256": file_hash(Path(__file__)),
        "document_prefix": config.get("document_prefix", ""),
        "query_prefix": config.get("query_prefix", ""),
        "batch_size": batch_size,
        "inputs": len(vectors),
        "requests": len(durations),
        "dimension": len(next(iter(vectors.values()))),
        "client_request_seconds": durations,
        "timing_scope": (
            "Sequential end-to-end HTTP batch durations including initial warm-up; "
            "not production server latency or hardware validation"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(
        args.output,
        {
            "complete": True,
            "input_sha256": inputs["input_sha256"],
            "provenance": provenance,
            "vectors": vectors,
        },
    )


if __name__ == "__main__":
    main()
