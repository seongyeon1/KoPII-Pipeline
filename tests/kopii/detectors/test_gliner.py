"""Unicode and document isolation regressions without optional model dependencies."""

import re
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Iterator

from kopii.detectors.gliner import GlinerDetector, KoreanSyllableSplitter


def native(text: str) -> Iterator[tuple[str, int, int]]:
    for match in re.finditer(r"\w+|\S", text):
        yield match.group(), match.start(), match.end()


def test_syllables_preserve_unicode_offsets_and_latin_runs() -> None:
    text = "🙂 İABC 김하늘은 A12"
    split = list(KoreanSyllableSplitter(native)(text))
    assert [(v, a, b) for v, a, b in split if 7 <= a < 11] == [
        ("김", 7, 8),
        ("하", 8, 9),
        ("늘", 9, 10),
        ("은", 10, 11),
    ]
    assert all(text[a:b] == value for value, a, b in split)
    lower = list(KoreanSyllableSplitter(native)(text, lower=True))
    assert [v[1:] for v in lower] == [v[1:] for v in split]
    assert ("i\u0307abc", 2, 6) in lower


def test_cross_document_batch_restores_offsets_and_deduplicates(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))

    def inference(texts, labels, threshold, batch_size):
        return [
            [
                {"start": m.start(), "end": m.end(), "label": "person", "score": 0.9}
                for m in re.finditer("X", text)
            ]
            for text in texts
        ]

    detector = object.__new__(GlinerDetector)
    detector.model = SimpleNamespace(inference=inference)
    detector.version, detector.labels, detector.threshold = 1, {"person": "PERSON_NAME"}, 0.5
    detector.window_chars, detector.overlap_chars, detector.batch_size = 4, 2, 3
    result = detector.detect_many(["abXdeX", "", "XabcX"])
    assert [[(e.start, e.end) for e in row] for row in result] == [
        [(2, 3), (5, 6)],
        [],
        [(0, 1), (4, 5)],
    ]
    assert detector.detect("abXdeX") == result[0]


def test_gliner2_restores_only_its_known_appended_period() -> None:
    import pytest

    from kopii.detectors.gliner import gliner2_input, restore_gliner2_span

    assert gliner2_input("김하늘") == "김하늘."
    assert gliner2_input("김하늘?") == "김하늘?"
    item = {"start": 0, "end": 4, "text": "김하늘."}
    assert restore_gliner2_span("김하늘", item) == dict(item, end=3)
    assert restore_gliner2_span("김하늘.", item) == item
    assert restore_gliner2_span("김하늘", {"start": 3, "end": 4, "text": "."}) is None
    with pytest.raises(ValueError, match="beyond"):
        restore_gliner2_span("김하늘", dict(item, end=5))
    with pytest.raises(ValueError, match="surface"):
        restore_gliner2_span("김하늘", dict(item, text="아무개."))
