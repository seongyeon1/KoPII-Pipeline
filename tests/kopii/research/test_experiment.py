"""Resume integrity, dataset validation, and group-preserving synthetic splits."""

import json
from pathlib import Path

import pytest

from kopii.research.data import audit_splits, load_dataset
from kopii.research.experiment import run_experiment
from kopii.research.synthetic import generate
from kopii.research.training import align_bio


def test_experiment_resumes_matching_run_and_rejects_changed_config_or_data(tmp_path: Path) -> None:
    data = tmp_path / "data.jsonl"
    data.write_text(json.dumps({"id": "a", "text": "no email", "spans": []}) + "\n")
    config = {"detector": {"kind": "rules"}, "labels": ["EMAIL"]}
    output = tmp_path / "run"
    first = run_experiment(config, data, output)
    before = (output / "predictions.json").read_bytes()
    assert run_experiment(config, data, output) == first
    assert (output / "predictions.json").read_bytes() == before
    with pytest.raises(ValueError, match="identity changed"):
        run_experiment(dict(config, seed=7), data, output)
    data.write_text(json.dumps({"id": "a", "text": "changed", "spans": []}) + "\n")
    with pytest.raises(ValueError, match="identity changed"):
        run_experiment(config, data, output)
    assert not (output / ".run.lock").exists()


def test_experiment_rejects_unknown_cached_ids_and_active_writer(tmp_path: Path) -> None:
    data = tmp_path / "data.jsonl"
    data.write_text(json.dumps({"id": "a", "text": "no email", "spans": []}) + "\n")
    config = {"detector": {"kind": "rules"}, "labels": ["EMAIL"]}
    output = tmp_path / "run"
    run_experiment(config, data, output)
    path = output / "predictions.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["records"]["foreign"] = {"predictions": []}
    path.write_text(json.dumps(checkpoint))
    with pytest.raises(ValueError, match="unexpected"):
        run_experiment(config, data, output)
    (output / ".run.lock").write_text("")
    with pytest.raises(ValueError, match="locked"):
        run_experiment(config, data, output)
    assert (output / ".run.lock").exists()


def test_dataset_rejects_duplicate_ids_and_incorrect_surfaces(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = {"id": "a", "text": "김하늘", "spans": []}
    path.write_text((json.dumps(row) + "\n") * 2)
    with pytest.raises(ValueError, match="unique"):
        load_dataset(path)
    row["spans"] = [{"start": 0, "end": 3, "label": "PERSON_NAME", "text": "다른값"}]
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="surface"):
        load_dataset(path)


def test_synthetic_generation_is_reproducible_and_template_disjoint(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=7, per_template=2)
    generate(b, seed=7, per_template=2)
    for split in ("train", "dev", "test"):
        assert (a / f"{split}.jsonl").read_bytes() == (b / f"{split}.jsonl").read_bytes()
    audit = audit_splits({split: a / f"{split}.jsonl" for split in ("train", "dev", "test")})
    assert all(
        item["groups"] == item["ids"] == item["exact_texts"] == 0 for item in audit["overlaps"]
    )
    families = [
        {r["meta"]["template_family"] for r in load_dataset(a / f"{split}.jsonl")}
        for split in ("train", "dev", "test")
    ]
    assert not families[0] & families[1] and not families[0] & families[2]
    with pytest.raises(ValueError, match="empty"):
        generate(a)


def test_training_alignment_masks_special_tokens_and_rejects_overlapping_gold() -> None:
    mapping = {"O": 0, "B-PERSON_NAME": 1, "I-PERSON_NAME": 2}
    gold = [{"start": 0, "end": 3, "label": "PERSON_NAME"}]
    assert align_bio([(0, 0), (0, 1), (1, 3), (3, 4), (0, 0)], gold, mapping) == [
        -100,
        1,
        2,
        0,
        -100,
    ]
    with pytest.raises(ValueError, match="overlapping"):
        align_bio([(0, 3)], gold + [{"start": 2, "end": 4, "label": "PERSON_NAME"}], mapping)
