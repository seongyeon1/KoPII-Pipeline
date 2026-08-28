"""가상 조직·구성원 생성 테스트."""

import re

from kopii.synth.population import generate_population


def _rrn_checksum_valid(rrn: str) -> bool:
    """주민등록번호 체크섬을 검증한다 (테스트용 독립 구현)."""
    digits = rrn.replace("-", "")
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(int(d) * w for d, w in zip(digits[:12], weights, strict=True))
    return (11 - total % 11) % 10 == int(digits[12])


def test_generates_requested_size() -> None:
    """요청한 인원 수만큼 만들어야 한다."""
    pop = generate_population(size=120, seed=1)
    assert len(pop.people) == 120


def test_employee_ids_are_unique() -> None:
    """사번은 조직 안에서 유일해야 한다."""
    pop = generate_population(size=300, seed=1)
    ids = [p.employee_id for p in pop.people]
    assert len(set(ids)) == len(ids)


def test_hr_directory_covers_everyone() -> None:
    """hr_directory는 모든 구성원을 담아야 한다 (지식 프로바이더 정답)."""
    pop = generate_population(size=80, seed=2)
    directory = pop.hr_directory()
    assert len(directory) == 80
    for person in pop.people:
        assert directory[person.employee_id] == (
            person.division,
            person.team,
            person.title,
        )


def test_every_team_belongs_to_a_division() -> None:
    """조직 트리에 고아 팀이 없어야 한다."""
    pop = generate_population(size=60, seed=3)
    division_codes = {u.code for u in pop.org if u.level == "division"}
    teams = [u for u in pop.org if u.level == "team"]
    assert teams
    for team in teams:
        assert team.parent in division_codes


def test_rrn_checksum_is_valid() -> None:
    """탐지기가 체크섬으로 검증하므로 합성 값도 유효해야 한다."""
    pop = generate_population(size=50, seed=4)
    for person in pop.people:
        assert re.fullmatch(r"\d{6}-\d{7}", person.rrn)
        assert _rrn_checksum_valid(person.rrn), person.rrn


def test_address_is_populated() -> None:
    """주소는 시·구·도로·번지가 모두 채워져야 한다."""
    pop = generate_population(size=30, seed=6)
    for person in pop.people:
        parts = person.address.split()
        assert len(parts) == 4, person.address
        assert parts[3].isdigit()


def test_some_people_have_no_nickname() -> None:
    """닉네임은 일부만 갖는다 — 템플릿의 requires 분기를 실제로 태운다."""
    pop = generate_population(size=200, seed=5, nickname_ratio=0.5)
    nicknames = [p.nickname for p in pop.people]
    assert any(n is None for n in nicknames)
    assert any(n is not None for n in nicknames)


def test_same_seed_is_reproducible() -> None:
    """같은 시드면 완전히 같은 인구가 나와야 한다."""
    first = generate_population(size=40, seed=9)
    second = generate_population(size=40, seed=9)
    assert first.people == second.people
    assert first.org == second.org


def test_different_seed_differs() -> None:
    """시드가 다르면 결과도 달라야 한다."""
    first = generate_population(size=40, seed=9)
    second = generate_population(size=40, seed=10)
    assert first.people != second.people
