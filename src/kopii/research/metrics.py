"""Exact typed spans, coverage, negative-document errors, and grouped intervals."""

import random
from typing import Any, Optional


def prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """Micro counts and ratios; a zero denominator yields zero, with support exposed."""
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
        "f5": 26 * tp / (26 * tp + fp + 25 * fn) if 26 * tp + fp + 25 * fn else 0.0,
    }


def _counts(
    row: dict[str, Any],
    prediction: list[dict[str, Any]],
    labels: set[str],
    mapping: dict[str, str],
) -> tuple[int, ...]:
    def spans(items: list[dict[str, Any]]) -> set[tuple[int, int, str]]:
        return {
            (e["start"], e["end"], mapping.get(e["label"], e["label"]))
            for e in items
            if mapping.get(e["label"], e["label"]) in labels
        }

    gold, pred = spans(row["spans"]), spans(prediction)
    gc = {i for start, end, _ in gold for i in range(start, end)}
    pc = {i for start, end, _ in pred for i in range(start, end)}
    # Only truly PII-free records count as negatives, not out-of-scope positives.
    negative = not row["spans"]
    return (
        len(gold & pred),
        len(pred - gold),
        len(gold - pred),
        len(gc & pc),
        len(pc - gc),
        len(gc - pc),
        int(negative),
        int(negative and bool(pred)),
        sum(set(range(a, b)) <= pc for a, b, _ in gold),
        len(gold),
    )


def evaluate(
    rows: list[dict[str, Any]],
    predictions: dict[str, list[dict[str, Any]]],
    labels: set[str],
    mapping: Optional[dict[str, str]] = None,
    bootstrap_samples: int = 0,
    seed: int = 42,
) -> dict[str, Any]:
    """Score a complete run; bootstrap whole source groups, never derived rows."""
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Evaluation requires nonempty records with unique IDs")
    if set(predictions) != {r["id"] for r in rows}:
        raise ValueError("Scoring requires exactly one prediction for every record")
    if not labels or bootstrap_samples < 0:
        raise ValueError("Require evaluation labels and nonnegative bootstrap count")
    mapping = mapping or {}
    counts = [_counts(r, predictions[r["id"]], labels, mapping) for r in rows]
    totals = tuple(sum(values) for values in zip(*counts, strict=True))
    result: dict[str, Any] = {
        "records": len(rows),
        "exact": prf(*totals[:3]),
        "characters": prf(*totals[3:6]),
        "negative_documents": totals[6],
        "false_positive_documents": totals[7],
        "negative_document_fpr": totals[7] / totals[6] if totals[6] else None,
        "full_span_coverage": totals[8] / totals[9] if totals[9] else None,
        "per_label": {},
    }
    for label in sorted(labels):
        per = [_counts(r, predictions[r["id"]], {label}, mapping) for r in rows]
        result["per_label"][label] = prf(*(sum(c[i] for c in per) for i in range(3)))
    if bootstrap_samples:
        if any("group_id" not in row for row in rows):
            raise ValueError("Grouped bootstrap requires explicit source group_id on every record")
        grouped: dict[str, list[int]] = {}
        for row, count in zip(rows, counts, strict=True):
            group = grouped.setdefault(row["group_id"], [0, 0, 0])
            for i in range(3):
                group[i] += count[i]
        if len(grouped) < 2:
            raise ValueError("Grouped bootstrap requires at least two source groups")
        rng, groups = random.Random(seed), list(grouped.values())
        values = []
        for _ in range(bootstrap_samples):
            sample = rng.choices(groups, k=len(groups))
            values.append(prf(*(sum(c[i] for c in sample) for i in range(3)))["f1"])
        values.sort()
        result["f1_group_bootstrap_95pct"] = {
            "low": values[int((len(values) - 1) * 0.025)],
            "high": values[int((len(values) - 1) * 0.975)],
            "samples": bootstrap_samples,
            "groups": len(groups),
            "seed": seed,
        }
    return result
