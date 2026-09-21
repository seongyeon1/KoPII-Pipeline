"""JSONL interchange for user-supplied corpora, independent of research worlds."""

import json
import os
from pathlib import Path
from typing import Any

from kopii.context import ContextPipeline
from kopii.retrieval import SearchDocument


def read_records(path: Path, *, allow_metadata: bool) -> list[SearchDocument]:
    """Strict IDs/text/metadata contract; input ordering breaks tied search scores."""
    result = []
    identifiers = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        allowed = {"id", "text", "metadata"} if allow_metadata else {"id", "text"}
        if not isinstance(row, dict) or not {"id", "text"} <= set(row) or set(row) - allowed:
            raise ValueError("Invalid document record keys")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, dict) or any(
            not isinstance(v, list) for v in metadata.values()
        ):
            raise ValueError("JSON metadata must map fields to string arrays")
        doc = SearchDocument(row["id"], row["text"], metadata)
        if doc.id in identifiers:
            raise ValueError("Duplicate document ID")
        identifiers.add(doc.id)
        result.append(doc)
    return result


def prepare_index(pipeline: ContextPipeline, source: Path, output: Path) -> dict[str, Any]:
    """Detect/resolve all records before writing a new owner-only private index."""
    if output.exists():
        raise ValueError("Use a new index output path")
    documents = [
        pipeline.process(d.text, d.id).document for d in read_records(source, allow_metadata=False)
    ]
    content = "".join(
        json.dumps(d.to_dict(include_metadata=True), ensure_ascii=False) + "\n" for d in documents
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    return {"documents": len(documents), "artifact": "private_search_index"}
