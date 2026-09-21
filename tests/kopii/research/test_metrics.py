"""Separate exact errors, overcoverage, and genuine negative-document counts."""

import pytest

from kopii.research.metrics import evaluate


def test_metrics_distinguish_exact_boundary_failure_from_character_coverage() -> None:
    rows = [
        {
            "id": "a",
            "text": "김하늘은",
            "spans": [{"start": 0, "end": 3, "label": "PERSON_NAME"}],
            "group_id": "g1",
        },
        {"id": "b", "text": "제품A", "spans": [], "group_id": "g2"},
    ]
    predictions = {
        "a": [{"start": 0, "end": 4, "label": "PERSON_NAME"}],
        "b": [{"start": 0, "end": 3, "label": "PERSON_NAME"}],
    }
    result = evaluate(rows, predictions, {"PERSON_NAME"}, bootstrap_samples=20)
    assert result["exact"]["tp"] == 0
    assert result["exact"]["fp"] == 2
    assert result["exact"]["fn"] == 1
    assert result["characters"]["recall"] == 1
    assert result["characters"]["precision"] == 3 / 7
    assert result["negative_document_fpr"] == 1
    assert result["f1_group_bootstrap_95pct"]["groups"] == 2


def test_metrics_do_not_count_out_of_scope_gold_as_negative_documents() -> None:
    rows = [{"id": "a", "spans": [{"start": 0, "end": 3, "label": "ADDRESS"}]}]
    result = evaluate(rows, {"a": []}, {"PERSON_NAME"})
    assert result["negative_documents"] == 0
    assert result["negative_document_fpr"] is None
    assert result["per_label"]["PERSON_NAME"]["support"] == 0


def test_metrics_reject_incomplete_predictions_and_ungrouped_bootstrap() -> None:
    rows = [{"id": "a", "spans": []}]
    with pytest.raises(ValueError, match="every record"):
        evaluate(rows, {}, {"EMAIL"})
    with pytest.raises(ValueError, match="group_id"):
        evaluate(rows, {"a": []}, {"EMAIL"}, bootstrap_samples=20)
