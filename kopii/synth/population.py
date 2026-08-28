"""가상 조직과 구성원을 생성하는 Stage 1."""

from __future__ import annotations

import random
from dataclasses import dataclass

from kopii.synth import names
from kopii.synth.idgen import IdSchemeInfo, build_scheme

_RRN_WEIGHTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


@dataclass(frozen=True, slots=True)
class OrgUnit:
    """조직 트리의 한 단위.

    Args:
        code: 단위 코드
        name: 표시 이름
        level: "division" 또는 "team"
        parent: 상위 단위 코드. 최상위면 None
    """

    code: str
    name: str
    level: str
    parent: str | None


@dataclass(frozen=True, slots=True)
class Person:
    """가상 구성원 한 명.

    Args:
        person_id: 정답 EntityKey. 같은 사람의 모든 span이 공유한다
        name: 한국어 이름
        nickname: 사내 영문 닉네임. 없을 수 있다
        employee_id: 사번
        id_variant: 사번 variant 식별자
        division: 소속 본부명
        team: 소속 팀명
        title: 직급
        birth_year: 출생 연도
        gender: "M" 또는 "F"
        rrn: 체크섬이 유효한 합성 주민등록번호
        phone: 휴대전화번호
        email: 사내 이메일
        address: 근무지 주소
    """

    person_id: str
    name: str
    nickname: str | None
    employee_id: str
    id_variant: str
    division: str
    team: str
    title: str
    birth_year: int
    gender: str
    rrn: str
    phone: str
    email: str
    address: str


@dataclass(frozen=True, slots=True)
class Population:
    """생성된 가상 조직 전체.

    Args:
        people: 구성원 목록
        org: 조직 트리
        id_scheme: 사번 채번 스킴의 정답 메타데이터
    """

    people: tuple[Person, ...]
    org: tuple[OrgUnit, ...]
    id_scheme: IdSchemeInfo

    def hr_directory(self) -> dict[str, tuple[str, str, str]]:
        """사번으로 소속을 조회하는 정답표를 만듭니다.

        설계 §4.3에서 "사번만으로는 소속을 알 수 없고 hr_directory 조회가
        필수"라고 한 그 조회표의 정답판이다.

        Returns:
            사번 → (본부, 팀, 직급)
        """
        return {p.employee_id: (p.division, p.team, p.title) for p in self.people}


def _make_rrn(birth_year: int, gender: str, rng: random.Random) -> str:
    """체크섬이 유효한 합성 주민등록번호를 만듭니다.

    탐지기가 체크섬으로 검증하므로(설계 §4.5) 합성 값도 유효해야
    탐지 평가가 의미를 갖는다. 산출물은 gitignore된 data/ 아래에만 둔다.

    Args:
        birth_year: 출생 연도 (1900~1999를 가정)
        gender: "M" 또는 "F"
        rng: 난수 생성기

    Returns:
        "YYMMDD-Gxxxxxc" 형태의 13자리 번호
    """
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    front = f"{birth_year % 100:02d}{month:02d}{day:02d}"
    gender_digit = 1 if gender == "M" else 2
    back6 = f"{gender_digit}{rng.randint(0, 99999):05d}"
    twelve = front + back6
    total = sum(int(d) * w for d, w in zip(twelve, _RRN_WEIGHTS, strict=True))
    check = (11 - total % 11) % 10
    return f"{front}-{back6}{check}"


def _build_org(
    rng: random.Random, divisions: int, teams_per_division: tuple[int, int]
) -> tuple[tuple[OrgUnit, ...], list[tuple[str, str]]]:
    """조직 트리를 만들고 (본부명, 팀명) 배치 후보를 함께 돌려줍니다.

    팀 이름 풀이 필요한 팀 수보다 적어 순환(재사용)이 일어나도, 두 번째부터
    쓰이는 이름에는 번호를 붙여("인프라팀 2") 조직 전체에서 팀 이름이
    유일하도록 한다. 팀→본부는 일반화 계층이 의존하는 트리 구조이므로,
    이름이 겹치면 서로 다른 본부의 사람들이 같은 팀으로 뒤섞여 보인다.

    Args:
        rng: 난수 생성기
        divisions: 본부 수
        teams_per_division: 본부당 팀 수 범위 (최소, 최대)

    Returns:
        (조직 단위 목록, (본부명, 팀명) 쌍 목록)
    """
    if divisions > len(names.DIVISION_NAMES):
        raise ValueError(
            f"본부 수({divisions})가 준비된 이름 수({len(names.DIVISION_NAMES)})를 넘습니다."
        )

    units: list[OrgUnit] = []
    placements: list[tuple[str, str]] = []
    team_pool = list(names.TEAM_NAMES)
    rng.shuffle(team_pool)
    cursor = 0
    usage_count: dict[str, int] = {}

    low, high = teams_per_division
    for index in range(divisions):
        division_name = names.DIVISION_NAMES[index]
        division_code = f"D{index}"
        units.append(
            OrgUnit(
                code=division_code, name=division_name, level="division", parent=None
            )
        )
        team_count = rng.randint(low, high)
        for offset in range(team_count):
            if cursor >= len(team_pool):
                cursor = 0  # 팀 이름이 모자라면 순환한다
            base_name = team_pool[cursor]
            cursor += 1
            usage_count[base_name] = usage_count.get(base_name, 0) + 1
            count = usage_count[base_name]
            team_name = base_name if count == 1 else f"{base_name} {count}"
            team_code = f"{division_code}T{offset}"
            units.append(
                OrgUnit(
                    code=team_code,
                    name=team_name,
                    level="team",
                    parent=division_code,
                )
            )
            placements.append((division_name, team_name))

    return tuple(units), placements


def generate_population(
    size: int,
    seed: int,
    scheme_name: str = "sequential_block",
    divisions: int = 5,
    teams_per_division: tuple[int, int] = (3, 8),
    nickname_ratio: float = 0.5,
) -> Population:
    """가상 조직과 구성원을 생성합니다.

    Args:
        size: 구성원 수
        seed: 난수 시드
        scheme_name: 사번 채번 스킴 이름
        divisions: 본부 수
        teams_per_division: 본부당 팀 수 범위
        nickname_ratio: 닉네임을 갖는 구성원 비율 (0.0~1.0)

    Returns:
        생성된 Population

    Raises:
        ValueError: size가 1 미만이거나 nickname_ratio가 범위를 벗어난 경우
    """
    if size < 1:
        raise ValueError(f"size는 1 이상이어야 합니다: {size}")
    if not 0.0 <= nickname_ratio <= 1.0:
        raise ValueError(f"nickname_ratio는 0~1이어야 합니다: {nickname_ratio}")

    rng = random.Random(seed)
    scheme = build_scheme(scheme_name)
    org, placements = _build_org(rng, divisions, teams_per_division)

    people: list[Person] = []
    for index in range(size):
        division, team = rng.choice(placements)
        surname = rng.choice(names.SURNAMES)
        given = rng.choice(names.GIVEN_NAMES)
        gender = rng.choice(("M", "F"))
        birth_year = rng.randint(1970, 1999)
        employee_id, variant = scheme.issue(rng)
        has_nickname = rng.random() < nickname_ratio
        nickname = rng.choice(names.NICKNAMES) if has_nickname else None
        people.append(
            Person(
                person_id=f"p_{index:05d}",
                name=f"{surname}{given}",
                nickname=nickname,
                employee_id=employee_id,
                id_variant=variant,
                division=division,
                team=team,
                title=rng.choice(names.TITLES),
                birth_year=birth_year,
                gender=gender,
                rrn=_make_rrn(birth_year, gender, rng),
                phone=f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                email=f"user{index:05d}@example.co.kr",
                address=(
                    f"{rng.choice(names.CITIES)} {rng.choice(names.DISTRICTS)} "
                    f"{rng.choice(names.ROADS)} {rng.randint(1, 300)}"
                ),
            )
        )

    return Population(people=tuple(people), org=org, id_scheme=scheme.info())
