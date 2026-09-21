"""Decoding regressions independent of model weights and network access."""

import pytest

from kopii.detectors.gliner import character_windows
from kopii.detectors.huggingface import decode_bio


def test_bio_decoder_handles_particles_orphan_tags_and_newline_boundaries() -> None:
    text = "김하늘은\n이바다"
    tokens = [
        (0, 1, "I-PERSON_NAME", 0.9),
        (1, 3, "I-PERSON_NAME", 0.8),
        (3, 4, "O", 1.0),
        (5, 8, "I-PERSON_NAME", 0.7),
    ]
    result = decode_bio(text, tokens)
    assert [(e.start, e.end, e.label) for e in result] == [
        (0, 3, "PERSON_NAME"),
        (5, 8, "PERSON_NAME"),
    ]
    assert result[0].score == 0.8
    across_line = decode_bio(text, [(0, 3, "B-PERSON_NAME", 0.9), (5, 8, "I-PERSON_NAME", 0.8)])
    assert len(across_line) == 2


def test_bio_decoder_rejects_numeric_model_labels() -> None:
    with pytest.raises(ValueError, match="labels"):
        decode_bio("김하늘", [(0, 3, "LABEL_0", 0.9)])


def test_character_windows_cover_tail_and_preserve_original_offsets() -> None:
    text = "가나다라마바사아자차카타파하"
    windows = character_windows(text, 6, 2)
    assert windows == [(0, "가나다라마바"), (4, "마바사아자차"), (8, "자차카타파하")]
    assert {start + i for start, part in windows for i in range(len(part))} == set(range(len(text)))


def test_character_windows_reject_nonadvancing_overlap() -> None:
    with pytest.raises(ValueError):
        character_windows("문서", 6, 6)
