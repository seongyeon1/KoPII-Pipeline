"""Metadata comes from detected entities and explicit fields, never rendered markers."""

import pytest

from kopii import ContextField, ContextPipeline, Entity
from kopii.resolvers.attributes import AttributeResolver


def test_context_masks_once_and_resolves_arbitrary_entity_labels_and_fields() -> None:
    class Detector:
        calls = 0

        def detect(self, text):
            self.calls += 1
            return [Entity(0, 5, "USER_ID")]

    detector = Detector()
    resolver = AttributeResolver(
        [{"account": "alice", "market": "north"}], key="account", value="market"
    )
    result = ContextPipeline(detector, {"market": ContextField(resolver, "USER_ID")}).process(
        "alice filed a report", "doc-1"
    )
    assert detector.calls == 1
    assert result.document.to_dict() == {"id": "doc-1", "text": "[USER_ID] filed a report"}
    assert result.document.metadata == {"market": frozenset({"north"})}
    assert result.resolution_counts == {"market": {"resolved": 1}}


def test_context_omits_ambiguous_missing_failed_and_conflicting_spans() -> None:
    class Detector:
        def detect(self, text):
            return [Entity(0, 1, "PERSON_NAME"), Entity(2, 3, "PERSON_NAME")]

    class FailedResolver:
        def resolve(self, names):
            raise RuntimeError("sensitive upstream details")

    resolver = AttributeResolver(
        [
            {"name": "A", "branch": "one", "country": "north"},
            {"name": "A", "branch": "two", "country": "north"},
        ],
        key="name",
        value="country",
        ambiguity_fields=["branch"],
    )
    pipe = ContextPipeline(
        Detector(), {"country": ContextField(resolver), "remote": ContextField(FailedResolver())}
    )
    result = pipe.process("A B", "doc")
    assert result.document.text == "[PERSON_NAME] [PERSON_NAME]"
    assert result.document.metadata == {}
    assert result.resolution_counts == {
        "country": {"ambiguous": 1, "missing": 1},
        "remote": {"unavailable": 2},
    }

    class ConflictingDetector:
        def detect(self, text):
            return [Entity(0, 1, "PERSON_NAME"), Entity(0, 1, "USER_ID")]

    result = ContextPipeline(ConflictingDetector(), {"country": ContextField(resolver)}).process(
        "A", "doc"
    )
    assert result.document.text == "[PII]" and result.resolution_counts == {"country": {}}

    class InvalidDetector:
        def detect(self, text):
            return [Entity(0, 99, "USER_ID")]

    with pytest.raises(ValueError, match="beyond"):
        ContextPipeline(InvalidDetector(), {}).process("short", "doc")
