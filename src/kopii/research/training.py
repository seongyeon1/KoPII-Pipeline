"""Explicit baseline fine-tuning with overflow windows and held-out validation."""

import hashlib
from pathlib import Path
from typing import Any

from kopii.config import check_keys
from kopii.research.data import audit_splits, file_hash, load_dataset
from kopii.research.experiment import atomic_json, build_manifest
from kopii.research.metrics import evaluate
from kopii.schemas import Entity


def align_bio(
    offsets: list[tuple[int, int]],
    spans: list[dict[str, Any]],
    label_to_id: dict[str, int],
) -> list[int]:
    """Assign intersecting tokens BIO labels; reject overlapping training entities."""
    ordered = sorted(spans, key=lambda span: span["start"])
    if any(left["end"] > right["start"] for left, right in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("Flat BIO training cannot encode overlapping gold spans")
    result = []
    active = None
    for start, end in offsets:
        if start == end:
            result.append(-100)
            continue
        matches = [
            i for i, span in enumerate(ordered) if span["start"] < end and start < span["end"]
        ]
        if len(matches) > 1:
            raise ValueError("One token intersects multiple gold entities")
        if not matches:
            result.append(label_to_id["O"])
            active = None
        else:
            index = matches[0]
            prefix = "I" if active == index else "B"
            result.append(label_to_id[f"{prefix}-{ordered[index]['label']}"])
            active = index
    return result


def train(
    config: dict[str, Any],
    train_path: Path,
    dev_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Train a new baseline, then evaluate dev; never claim historical reproduction.

    This version uses cross-entropy and a fixed number of epochs, with no automatic
    best-checkpoint selection. Token windows include overflow (unlike the old run).
    """
    check_keys(
        config,
        {
            "model",
            "revision",
            "labels",
            "seed",
            "epochs",
            "batch_size",
            "learning_rate",
            "max_length",
            "stride",
            "device",
            "local_files_only",
        },
    )
    revision = config["revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Training requires an immutable base-model revision")
    if Path(config["model"]).exists():
        raise ValueError("Training base must be a versioned Hub checkpoint")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Training output must be empty")
    max_length, stride = config.get("max_length", 256), config.get("stride", 32)
    if max_length < 8 or not 0 <= stride < max_length - 2:
        raise ValueError("Invalid training token windows")
    device = config.get("device", "cpu")
    if device not in {"cpu", "mps", "cuda"}:
        raise ValueError("Training device must be cpu, mps, or cuda")
    if config.get("epochs", 1) <= 0 or config.get("batch_size", 8) < 1:
        raise ValueError("Training epochs and batch size must be positive")
    audit = audit_splits({"train": train_path, "dev": dev_path})
    if any(item["missing_group_ids"] for item in audit["splits"].values()):
        raise ValueError("Training requires source group_id on both splits")
    if any(
        any(item[key] for key in ("ids", "groups", "exact_texts")) for item in audit["overlaps"]
    ):
        raise ValueError("Train/dev overlap detected")
    rows, dev_rows = load_dataset(train_path), load_dataset(dev_path)
    labels = config["labels"]
    if not labels or len(labels) != len(set(labels)):
        raise ValueError("Training labels must be nonempty and unique")
    for label in labels:
        Entity(0, 1, label)
    if any(span["label"] not in labels for row in rows + dev_rows for span in row["spans"]):
        raise ValueError("Gold label absent from training schema")
    import torch
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    from kopii.detectors.huggingface import HuggingFaceDetector

    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("Requested CUDA device is unavailable")
    if device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("Requested MPS device is unavailable")
    set_seed(config.get("seed", 42))
    tags = ["O"] + [f"{prefix}-{label}" for label in labels for prefix in ("B", "I")]
    tag_ids = {tag: i for i, tag in enumerate(tags)}
    tokenizer = AutoTokenizer.from_pretrained(
        config["model"],
        revision=revision,
        use_fast=True,
        local_files_only=config.get("local_files_only", False),
    )
    if not tokenizer.is_fast:
        raise ValueError("Training requires fast tokenizer offsets")
    examples = []
    for row in rows:
        encoded = tokenizer(
            row["text"],
            max_length=max_length,
            stride=stride,
            truncation=True,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
        )
        for i, offsets in enumerate(encoded["offset_mapping"]):
            item = {key: encoded[key][i] for key in tokenizer.model_input_names if key in encoded}
            item["labels"] = align_bio(offsets, row["spans"], tag_ids)
            examples.append(item)
    model = AutoModelForTokenClassification.from_pretrained(
        config["model"],
        revision=revision,
        num_labels=len(tags),
        id2label=dict(enumerate(tags)),
        label2id=tag_ids,
        local_files_only=config.get("local_files_only", False),
    )
    output.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        dict(
            config,
            dev_sha256=file_hash(dev_path),
            protocol="cross_entropy_fixed_epochs_overflow_v1",
        ),
        train_path,
    )
    manifest["dev_sha256"] = file_hash(dev_path)
    manifest["protocol"] = "cross_entropy_fixed_epochs_overflow_v1"
    atomic_json(output / "training-manifest.json", manifest)
    arguments = TrainingArguments(
        output_dir=str(output / "checkpoints"),
        num_train_epochs=config.get("epochs", 1),
        per_device_train_batch_size=config.get("batch_size", 8),
        learning_rate=config.get("learning_rate", 2e-5),
        seed=config.get("seed", 42),
        use_cpu=device == "cpu",
        save_strategy="no",
        report_to=[],
        logging_steps=25,
        dataloader_pin_memory=device == "cuda",
    )
    if arguments.device.type != device:
        raise ValueError("Trainer selected a different device than requested")
    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=examples,
        data_collator=DataCollatorForTokenClassification(tokenizer),
    )
    trained = trainer.train()
    model_path = output / "model"
    trainer.save_model(str(model_path))
    tokenizer.save_pretrained(str(model_path))
    detector = HuggingFaceDetector(
        str(model_path),
        revision=revision,
        device=device,
        max_length=max_length,
        stride=stride,
        local_files_only=True,
    )
    predictions = {
        row["id"]: [e.to_dict() for e in detector.detect(row["text"])] for row in dev_rows
    }
    digest = hashlib.sha256()
    for path in sorted(model_path.iterdir()):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(file_hash(path).encode())
    report = {
        "protocol": manifest["protocol"],
        "training_windows": len(examples),
        "training": trained.metrics,
        "dev": evaluate(dev_rows, predictions, set(labels)),
        "model_files_sha256": digest.hexdigest(),
        "historical_run_reproduction": False,
    }
    atomic_json(output / "training-results.json", report)
    return report
