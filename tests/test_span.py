"""Span 데이터 구조 테스트."""

import pytest

from kopii.span import Span


def test_verify_matches_source_text() -> None:
    """span 오프셋이 원문과 정확히 대응해야 한다."""
    text = "이름은 김민수입니다."
    span = Span(start=4, end=7, type="NAME", surface="김민수")
    assert span.verify(text) is True


def test_verify_detects_offset_drift() -> None:
    """오프셋이 밀리면 verify가 False여야 한다."""
    text = "이름은 김민수입니다."
    span = Span(start=3, end=6, type="NAME", surface="김민수")
    assert span.verify(text) is False


def test_rejects_surface_length_mismatch() -> None:
    """surface 길이와 span 폭이 다르면 만들 수 없다."""
    with pytest.raises(ValueError, match="폭"):
        Span(start=0, end=3, type="NAME", surface="김민")


def test_rejects_non_positive_width() -> None:
    """빈 span은 허용하지 않는다."""
    with pytest.raises(ValueError, match="커야"):
        Span(start=5, end=5, type="NAME", surface="")
