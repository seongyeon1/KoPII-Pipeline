"""Validate JSONL corpora and audit group/text leakage across splits."""

import hashlib
import json
from pathlib import Path
from typing import Any

from kopii.schemas import Entity


def file_hash(path: Path) -> str:
    """Hash file contents without depending on machine-specific paths."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Require unique string IDs, text, and validated half-open gold spans."""
    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError("Each record requires text")
        if not isinstance(row.get("id"), str) or not row["id"] or row["id"] in ids:
            raise ValueError("Dataset IDs must be nonempty unique strings")
        if not isinstance(row.get("spans"), list):
            raise ValueError("Each record requires a spans array")
        if "group_id" in row and (not isinstance(row["group_id"], str) or not row["group_id"]):
            raise ValueError("group_id must be a nonempty string")
        seen: set[tuple[int, int, str]] = set()
        for item in row["spans"]:
            entity = Entity(item["start"], item["end"], item["label"])
            entity.validate_text(row["text"])
            key = entity.start, entity.end, entity.label
            if key in seen:
                raise ValueError("Duplicate gold span")
            seen.add(key)
            if "text" in item and item["text"] != row["text"][entity.start : entity.end]:
                raise ValueError("Gold surface does not match offsets")
        ids.add(row["id"])
        rows.append(row)
    if not rows:
        raise ValueError("Dataset is empty")
    return rows


def audit_splits(paths: dict[str, Path]) -> dict[str, Any]:
    """Count cross-split IDs, groups, and exact texts; not a semantic leakage proof."""
    rows = {name: load_dataset(path) for name, path in paths.items()}
    result: dict[str, Any] = {"splits": {}, "overlaps": []}
    for name, records in rows.items():
        result["splits"][name] = {
            "records": len(records),
            "sha256": file_hash(paths[name]),
            "missing_group_ids": sum("group_id" not in row for row in records),
        }
    names = sorted(rows)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            a, b = rows[left], rows[right]
            result["overlaps"].append(
                {
                    "splits": [left, right],
                    "ids": len({r["id"] for r in a} & {r["id"] for r in b}),
                    "groups": len(
                        {r["group_id"] for r in a if "group_id" in r}
                        & {r["group_id"] for r in b if "group_id" in r}
                    ),
                    "exact_texts": len({r["text"] for r in a} & {r["text"] for r in b}),
                }
            )
    return result
