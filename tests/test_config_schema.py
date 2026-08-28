"""합성 설정 스키마 테스트."""

import pytest
from pydantic import ValidationError

from kopii.config.schema import CorpusConfig, PerturbConfig, PopulationConfig


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
