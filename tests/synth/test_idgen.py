"""사번 채번 스킴 테스트."""

import random
import re

import pytest

from kopii.synth.idgen import (
    OrgCodedScheme,
    SequentialBlockScheme,
    build_scheme,
)


def test_sequential_block_format() -> None:
    """정규직 사번은 블록 접두 + 일련번호 형태여야 한다."""
    scheme = SequentialBlockScheme(blocks=("23",), serial_digits=5, project_ratio=0.0)
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "FULLTIME"
    assert re.fullmatch(r"23\d{5}", value)


def test_sequential_block_serials_are_unique() -> None:
    """같은 블록 안에서 일련번호가 겹치지 않아야 한다."""
    scheme = SequentialBlockScheme(blocks=("23",), serial_digits=5, project_ratio=0.0)
    rng = random.Random(0)
    values = [scheme.issue(rng)[0] for _ in range(500)]
    assert len(set(values)) == 500


def test_project_variant_uses_prefix() -> None:
    """프로젝트 사번은 접두 문자 + 6자리여야 한다."""
    scheme = SequentialBlockScheme(project_ratio=1.0, project_prefix="K")
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "PROJECT"
    assert re.fullmatch(r"K\d{6}", value)


def test_sequential_block_info_reports_structural_digits() -> None:
    """추론기 채점용 정답 메타를 돌려줘야 한다."""
    scheme = SequentialBlockScheme(blocks=("23", "24"), serial_digits=5)
    info = scheme.info()
    assert info.scheme == "sequential_block"
    assert info.structural_digits["FULLTIME"] == 2
    assert set(info.variant_ids) == {"FULLTIME", "PROJECT"}


def test_org_coded_format_and_info() -> None:
    """조직 코드 내장형은 구조 자릿수가 4다."""
    scheme = OrgCodedScheme(years=(25,), divisions="A", teams="3", serial_digits=4)
    rng = random.Random(0)
    value, variant = scheme.issue(rng)
    assert variant == "ORGCODED"
    assert re.fullmatch(r"25A3-\d{4}", value)
    assert scheme.info().structural_digits["ORGCODED"] == 4


def test_same_seed_reproduces_same_ids() -> None:
    """같은 시드면 같은 사번 열이 나와야 한다."""
    first = [SequentialBlockScheme().issue(random.Random(7))[0] for _ in range(1)]
    second = [SequentialBlockScheme().issue(random.Random(7))[0] for _ in range(1)]
    assert first == second


def test_build_scheme_rejects_unknown_name() -> None:
    """알 수 없는 스킴 이름은 거부한다."""
    with pytest.raises(ValueError, match="알 수 없는"):
        build_scheme("no_such_scheme")
