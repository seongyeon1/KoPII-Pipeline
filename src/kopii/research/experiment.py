"""Immutable run identity, atomic checkpoints, and strict resumable evaluation."""

import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from kopii.config import check_keys, create_detector
from kopii.research.data import file_hash, load_dataset
from kopii.research.metrics import evaluate
from kopii.schemas import Entity


def atomic_json(path: Path, value: Any) -> None:
    """Write a complete JSON file, then atomically replace its previous version."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def build_manifest(config: dict[str, Any], data: Path) -> dict[str, Any]:
    """Identify actual package source, data, settings, dependencies, and execution host."""
    source_root = Path(__file__).parents[1]
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        digest.update(str(path.relative_to(source_root)).encode())
        digest.update(path.read_bytes())
    dependencies = {}
    for name in ("kopii-pipeline", "torch", "transformers", "tokenizers", "gliner", "gliner2"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    identity = {
        "schema_version": 1,
        "config": config,
        "data_sha256": file_hash(data),
        "source_sha256": digest.hexdigest(),
        "dependencies": dependencies,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return dict(identity, run_id=hashlib.sha256(canonical.encode()).hexdigest())


def _check_revisions(config: dict[str, Any]) -> None:
    kind = config.get("kind")
    if kind in {"huggingface", "gliner"}:
        revision = config.get("revision", "")
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Research runs require a full immutable model commit SHA")
        if Path(config.get("model", "")).exists():
            raise ValueError("Research runner requires Hub checkpoints, not mutable local weights")
    for child in config.get("detectors", []):
        _check_revisions(child)


def run_experiment(config: dict[str, Any], data: Path, output: Path) -> dict[str, Any]:
    """Resume only matching runs; store positions rather than raw document text."""
    check_keys(config, {"detector", "labels", "label_map", "seed", "bootstrap_samples"})
    _check_revisions(config["detector"])
    rows = load_dataset(data)
    if not config["labels"] or len(set(config["labels"])) != len(config["labels"]):
        raise ValueError("Evaluation labels must be nonempty and unique")
    for label in config["labels"]:
        Entity(0, 1, label)
    if config.get("bootstrap_samples", 0) and any("group_id" not in r for r in rows):
        raise ValueError("Grouped bootstrap requires group_id before inference")
    manifest = build_manifest(config, data)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".run.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "Run is locked; verify no writer is active before removing .run.lock"
        ) from exc
    try:
        os.close(lock_fd)
        manifest_path = output / "manifest.json"
        predictions_path = output / "predictions.json"
        if manifest_path.exists():
            if json.loads(manifest_path.read_text()) != manifest:
                raise ValueError("Run identity changed; choose a new output directory")
        elif any(output.glob("*.json")):
            raise ValueError("Output contains unversioned artifacts; choose a fresh directory")
        else:
            atomic_json(manifest_path, manifest)
        checkpoint = (
            json.loads(predictions_path.read_text())
            if predictions_path.exists()
            else {
                "run_id": manifest["run_id"],
                "records": {},
            }
        )
        if checkpoint.get("run_id") != manifest["run_id"]:
            raise ValueError("Prediction checkpoint belongs to another run")
        records = checkpoint["records"]
        by_id = {row["id"]: row for row in rows}
        if not isinstance(records, dict) or not set(records) <= set(by_id):
            raise ValueError("Checkpoint contains unexpected document IDs")
        for key, record in records.items():
            for item in record["predictions"]:
                Entity(**item).validate_text(by_id[key]["text"])
        remaining = [row for row in rows if row["id"] not in records]
        if remaining:
            detector = create_detector(config["detector"])
            for row in remaining:
                start = time.perf_counter()
                entities = detector.detect(row["text"])
                for entity in entities:
                    entity.validate_text(row["text"])
                records[row["id"]] = {
                    "predictions": [e.to_dict() for e in entities],
                    "elapsed_seconds": time.perf_counter() - start,
                }
                atomic_json(predictions_path, checkpoint)
        metrics = evaluate(
            rows,
            {key: value["predictions"] for key, value in records.items()},
            set(config["labels"]),
            config.get("label_map"),
            config.get("bootstrap_samples", 0),
            config.get("seed", 42),
        )
        report = {
            "run_id": manifest["run_id"],
            "status": "complete",
            "metrics": metrics,
            "timing_note": "Per-document wall time is diagnostic, not a warmed latency benchmark.",
        }
        atomic_json(output / "metrics.json", report)
        return report
    finally:
        lock.unlink(missing_ok=True)
