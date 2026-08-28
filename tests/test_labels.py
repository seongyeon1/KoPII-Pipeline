"""PII 타입 정본과 Kaggle 7-type 매핑 테스트."""

import pytest

from kopii.labels import (
    ENTITY_MERGE_MAP,
    KAGGLE_7_ENTITY_TYPES,
    PII_TYPES,
    to_kaggle7,
)


def test_every_fine_type_maps_to_kaggle7() -> None:
    """세밀 타입은 전부 Kaggle 7-type 중 하나로 내려가야 한다."""
    for pii_type in PII_TYPES:
        assert to_kaggle7(pii_type) in KAGGLE_7_ENTITY_TYPES


def test_merge_map_covers_exactly_the_fine_types() -> None:
    """매핑 키 집합이 PII 타입 정본과 일치해야 한다."""
    assert set(ENTITY_MERGE_MAP) == set(PII_TYPES)


def test_korean_specific_types_exist() -> None:
    """Kaggle 7-type에 없는 한국 타입이 정본에 있어야 한다."""
    for pii_type in ("RRN", "EMPLOYEE_ID", "NICKNAME"):
        assert pii_type in PII_TYPES


def test_unknown_type_raises() -> None:
    """정본에 없는 타입은 매핑을 거부한다."""
    with pytest.raises(KeyError):
        to_kaggle7("UNKNOWN_TYPE")
