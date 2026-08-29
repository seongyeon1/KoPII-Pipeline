"""합성 설정 스키마 테스트."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from kopii.config.schema import (
    CorpusConfig,
    PerturbConfig,
    PopulationConfig,
    resolve_user_path,
)


def test_defaults_are_valid() -> None:
    """기본값만으로 설정이 성립해야 한다."""
    assert PopulationConfig().size > 0
    assert CorpusConfig().size > 0


def test_rejects_out_of_range_probability() -> None:
    """확률은 0~1을 벗어날 수 없다."""
    with pytest.raises(ValidationError):
        PerturbConfig(typo=1.5)


def test_rejects_all_zero_genre_weights() -> None:
    """장르 가중치가 전부 0이면 문서를 만들 수 없다."""
    with pytest.raises(ValidationError, match="가중치"):
        CorpusConfig(genres={"email": 0.0})


def test_rejects_non_positive_size() -> None:
    """인원 수는 1 이상이어야 한다."""
    with pytest.raises(ValidationError):
        PopulationConfig(size=0)


def test_resolve_user_path_rejects_empty_path() -> None:
    """빈 경로는 거부해야 한다."""
    with pytest.raises(ValueError, match="비어"):
        resolve_user_path("")


def test_resolve_user_path_rejects_null_byte() -> None:
    """NUL 바이트가 포함된 경로는 거부해야 한다."""
    with pytest.raises(ValueError, match="NUL"):
        resolve_user_path("foo\x00bar")


def test_resolve_user_path_collapses_parent_segments(tmp_path: Path) -> None:
    """`..` 세그먼트를 접어 실제 대상과 같은 경로를 얻어야 한다."""
    real_file = tmp_path / "real.txt"
    real_file.write_text("hello", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    detour = nested / ".." / "real.txt"

    resolved = resolve_user_path(detour)

    assert resolved == real_file.resolve()


def test_resolve_user_path_requires_regular_file(tmp_path: Path) -> None:
    """must_be_file=True면 존재하는 일반 파일만 허용해야 한다."""
    missing = tmp_path / "missing.txt"
    with pytest.raises(FileNotFoundError):
        resolve_user_path(missing, must_be_file=True)

    with pytest.raises(ValueError, match="일반 파일"):
        resolve_user_path(tmp_path, must_be_file=True)
