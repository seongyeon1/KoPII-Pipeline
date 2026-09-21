"""End-to-end replacement contracts using actual fixture detectors and resolvers."""

import json
from pathlib import Path

import pytest

from kopii import Entity, Pipeline, Policy
from kopii.detectors.rules import DictionaryDetector, RuleDetector
from kopii.rendering import merge_entities
from kopii.resolvers.csv import CsvResolver


def test_pipeline_generalizes_resolved_names_and_masks_ambiguous_names(tmp_path: Path) -> None:
    path = tmp_path / "directory.csv"
    path.write_text("name,team\n김하늘,개발팀\n이바다,개발팀\n이바다,운영팀\n")
    pipeline = Pipeline(
        DictionaryDetector(["김하늘", "이바다"]),
        Policy({"PERSON_NAME": "organization"}),
        CsvResolver(path),
    )
    result = pipeline.process("김하늘이 검토하고 이바다가 승인했습니다.", "doc-1")
    assert result.text == "[PERSON_NAME:개발팀]이 검토하고 [PERSON_NAME]가 승인했습니다."
    assert [r.action for r in result.replacements] == ["organization", "mask"]
    assert "김하늘" not in json.dumps(result.to_dict(), ensure_ascii=False)


def test_pipeline_restores_unicode_offsets_after_multiple_replacements() -> None:
    text = "😀 문의 a@example.invalid, 회신 b@example.invalid."
    result = Pipeline(RuleDetector()).process(text)
    assert result.text == "😀 문의 [EMAIL], 회신 [EMAIL]."
    for replacement in result.replacements:
        assert result.text[replacement.output_start : replacement.output_end] == "[EMAIL]"
        assert text[replacement.start : replacement.end].endswith("@example.invalid")


def test_pipeline_propagates_detector_failure() -> None:
    class FailedDetector:
        def detect(self, text: str) -> list[Entity]:
            raise TimeoutError("unavailable")

    with pytest.raises(TimeoutError):
        Pipeline(FailedDetector()).process("김하늘의 문서")


def test_pipeline_resolver_failure_falls_back_without_disclosing_error_text() -> None:
    class FailedResolver:
        def resolve(self, names: list[str]) -> dict[str, object]:
            raise RuntimeError("sensitive content in provider error")

    pipeline = Pipeline(DictionaryDetector(["김하늘"]), Policy({"PERSON_NAME": "organization"}))
    pipeline.resolver = FailedResolver()  # type: ignore[assignment]
    result = pipeline.process("김하늘의 문서")
    assert result.text == "[PERSON_NAME]의 문서"
    assert result.events == ["resolver_unavailable"]
    assert "sensitive" not in json.dumps(result.to_dict())


def test_overlapping_detectors_cover_union_and_mask_conflicting_types() -> None:
    entities = [Entity(0, 4, "PERSON_NAME"), Entity(2, 7, "EMAIL"), Entity(6, 9, "EMAIL")]
    merged = merge_entities("abcdefghij", entities)
    assert [(e.start, e.end, e.label) for e in merged] == [(0, 9, "PII")]


def test_pipeline_rejects_out_of_bounds_detector_output() -> None:
    class InvalidDetector:
        def detect(self, text: str) -> list[Entity]:
            return [Entity(0, 99, "EMAIL")]

    with pytest.raises(ValueError, match="beyond"):
        Pipeline(InvalidDetector()).process("짧은 문서")


def test_pseudonyms_are_keyed_document_scoped_and_consistent() -> None:
    detector = DictionaryDetector(["김하늘"])
    policy = Policy({"PERSON_NAME": "pseudonym"}, key=b"synthetic-test-key-only")
    pipeline = Pipeline(detector, policy)
    first = pipeline.process("김하늘 김하늘", "doc-1").text.split()
    assert first[0] == first[1]
    assert first[0] != pipeline.process("김하늘", "doc-2").text
    other = Pipeline(detector, Policy({"PERSON_NAME": "pseudonym"}, key=b"different-test-key-only"))
    assert first[0] != other.process("김하늘", "doc-1").text
    assert pipeline.process("김하늘").text == "[PERSON_NAME]"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_entity_rejects_invalid_confidence(score: float) -> None:
    with pytest.raises(ValueError):
        Entity(0, 1, "EMAIL", score)
