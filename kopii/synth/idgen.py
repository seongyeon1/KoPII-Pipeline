"""합성 사번 채번 스킴과 추론기 채점용 정답 메타데이터."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IdSchemeInfo:
    """채번 스킴의 정답 메타데이터.

    설계 §5 장치 ①의 ID 스키마 추론기를 채점하려면 "정답 구조 자릿수"가
    필요하다. 생성 시점에 기록해 manifest로 내보낸다.

    Args:
        scheme: 스킴 이름
        variant_ids: 이 스킴이 발급하는 variant 식별자
        structural_digits: variant별 구조적(비일련) 선두 자릿수
    """

    scheme: str
    variant_ids: tuple[str, ...]
    structural_digits: dict[str, int]


class IdScheme(Protocol):
    """사번 채번 스킴 인터페이스."""

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, variant 식별자)
        """
        ...

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        ...


class SequentialBlockScheme:
    """조직 코드가 없는 순차 채번 스킴.

    블록 접두 뒤에 일련번호가 붙는다. 사번만으로는 소속을 알 수 없고,
    선두 블록만이 구조적 정보다.

    Args:
        blocks: 채번 블록 접두 목록
        serial_digits: 일련번호 자릿수
        project_ratio: 프로젝트 인력 비율 (0.0~1.0)
        project_prefix: 프로젝트 사번 접두 문자
    """

    def __init__(
        self,
        blocks: tuple[str, ...] = ("23", "24"),
        serial_digits: int = 5,
        project_ratio: float = 0.1,
        project_prefix: str = "K",
    ) -> None:
        if not blocks:
            raise ValueError("blocks는 최소 하나가 필요합니다.")
        if len({len(b) for b in blocks}) != 1:
            raise ValueError(
                f"블록 길이가 서로 달라 구조 자릿수가 모호합니다: {blocks}"
            )
        if not 0.0 <= project_ratio <= 1.0:
            raise ValueError(f"project_ratio는 0~1이어야 합니다: {project_ratio}")

        self._blocks = blocks
        self._serial_digits = serial_digits
        self._project_ratio = project_ratio
        self._project_prefix = project_prefix
        self._counters: dict[str, int] = dict.fromkeys(blocks, 0)
        self._project_counter = 0

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, "FULLTIME" 또는 "PROJECT")
        """
        if rng.random() < self._project_ratio:
            self._project_counter += 1
            return f"{self._project_prefix}{self._project_counter:06d}", "PROJECT"

        block = rng.choice(self._blocks)
        self._counters[block] += 1
        serial = f"{self._counters[block]:0{self._serial_digits}d}"
        return f"{block}{serial}", "FULLTIME"

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        return IdSchemeInfo(
            scheme="sequential_block",
            variant_ids=("FULLTIME", "PROJECT"),
            structural_digits={
                "FULLTIME": len(self._blocks[0]),
                "PROJECT": len(self._project_prefix),
            },
        )


class OrgCodedScheme:
    """조직 코드를 사번에 담는 채번 스킴.

    입사연도 2자 + 본부 1자 + 팀 1자 + 하이픈 + 일련번호. 사번만 보고도
    소속을 파싱할 수 있는 대조군이며, 추론기가 포맷에 종속되지 않는지
    검증하는 두 번째 형태다.

    Args:
        years: 입사연도 두 자리 목록
        divisions: 본부 코드로 쓸 문자들
        teams: 팀 코드로 쓸 문자들
        serial_digits: 일련번호 자릿수
    """

    def __init__(
        self,
        years: tuple[int, ...] = (24, 25),
        divisions: str = "ABCDE",
        teams: str = "12345678",
        serial_digits: int = 4,
    ) -> None:
        if not years or not divisions or not teams:
            raise ValueError("years·divisions·teams는 비어 있을 수 없습니다.")
        self._years = years
        self._divisions = divisions
        self._teams = teams
        self._serial_digits = serial_digits
        self._counter = 0

    def issue(self, rng: random.Random) -> tuple[str, str]:
        """사번을 하나 발급합니다.

        Args:
            rng: 난수 생성기

        Returns:
            (사번, "ORGCODED")
        """
        year = rng.choice(self._years)
        division = rng.choice(self._divisions)
        team = rng.choice(self._teams)
        self._counter += 1
        serial = f"{self._counter:0{self._serial_digits}d}"
        return f"{year:02d}{division}{team}-{serial}", "ORGCODED"

    def info(self) -> IdSchemeInfo:
        """정답 메타데이터를 돌려줍니다."""
        # 연도 2자 + 본부 1자 + 팀 1자 = 4자리가 구조적 정보다.
        return IdSchemeInfo(
            scheme="org_coded",
            variant_ids=("ORGCODED",),
            structural_digits={"ORGCODED": 4},
        )


def build_scheme(name: str) -> IdScheme:
    """이름으로 채번 스킴을 만듭니다.

    Args:
        name: "sequential_block" 또는 "org_coded"

    Returns:
        해당 스킴 인스턴스

    Raises:
        ValueError: 알 수 없는 이름인 경우
    """
    if name == "sequential_block":
        return SequentialBlockScheme()
    if name == "org_coded":
        return OrgCodedScheme()
    raise ValueError(f"알 수 없는 채번 스킴입니다: {name}")
