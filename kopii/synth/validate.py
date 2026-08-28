"""생성된 합성 코퍼스를 검증하는 CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

_RRN_WEIGHTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_MAX_REPORTED_ERRORS = 20

# span 타입 → population.jsonl에서 대조할 person 필드.
# 여기에 없는 타입(준식별자 등)은 surface_matches_origin 검사에서 건너뛴다.
_ORIGIN_FIELD_BY_TYPE: dict[str, str] = {
    "NAME": "name",
    "NICKNAME": "nickname",
    "EMPLOYEE_ID": "employee_id",
    "RRN": "rrn",
    "PHONE": "phone",
    "EMAIL": "email",
    "ADDRESS": "address",
}


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """검증 결과.

    Args:
        checks: 검사 이름 → 통과 여부
        errors: 사람이 읽을 수 있는 실패 설명 (상한을 둔다)
    """

    checks: dict[str, bool]
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """모든 검사를 통과했는지."""
        return all(self.checks.values())


# 주의: 이 함수는 population.py의 같은 기능을 의도적으로 다시 구현합니다.
# 생성기의 헬퍼를 공유하면 그 헬퍼의 버그가 검증기를 속일 수 있으므로,
# 두 모듈의 구현을 완전히 독립적으로 유지해야 합니다. 절대로 병합하지 마세요.
def _rrn_checksum_valid(rrn: str) -> bool:
    """주민등록번호 체크섬을 검증합니다.

    Args:
        rrn: "YYMMDD-XXXXXXX" 형태 문자열

    Returns:
        체크섬이 맞으면 True
    """
    digits = rrn.replace("-", "")
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:12], _RRN_WEIGHTS, strict=True))
    return (11 - total % 11) % 10 == int(digits[12])


def _normalize_surface(surface: str) -> str:
    """알려진 흔들림(perturbation) 흔적을 지워 원본 필드와 비교할 수 있게 합니다.

    Args:
        surface: 코퍼스에 기록된 surface

    Returns:
        줄바꿈 분할과 공백-하이픈 확장을 되돌린 문자열
    """
    return surface.replace("\n", "").replace(" - ", "-")


# perturb.py의 _TYPO_POOL(오타가 대체할 수 있는 문자 집합)을 그대로 옮겨 적은 값.
# validate.py는 perturb.py에 의존하지 않는 독립 검증기이므로 import하지 않고
# 값만 복제한다 — perturb.py의 _TYPO_POOL이 바뀌면 이 상수도 함께 갱신해야 한다.
_NAME_TYPO_CHARS: str = "가나다라마바사아자차카타파하"


def _surface_matches_origin(surface: str, origin: str, span_type: str) -> bool:
    """정규화한 surface가 person의 origin 필드에서 나올 수 있는 값인지 판정합니다.

    NAME 타입에만 흔들림 파이프라인이 만들 수 있는 변형(부분 이름=성 한 글자,
    한 글자 오타, 부분 이름에 오타가 겹친 경우)을 허용한다. 그 밖의 타입은
    정규화 후 완전 일치만 인정한다 — EMPLOYEE_ID처럼 근접 순번으로 발급되는
    값은 같은 길이에 한 글자만 달라도 실제로는 다른 사람을 가리킬 수 있어,
    느슨한 규칙을 쓰면 그런 오귀속을 못 잡아낸다.

    Args:
        surface: 알려진 흔들림을 되돌린 surface
        origin: population.jsonl에 있는 해당 person의 원본 필드 값
        span_type: span의 PII 타입 (예: "NAME", "EMPLOYEE_ID")

    Returns:
        surface가 origin에서 legitimate하게 파생될 수 있으면 True
    """
    if surface == origin:
        return True
    if span_type != "NAME" or not origin:
        return False
    if surface == origin[0]:
        return True
    if len(surface) == len(origin):
        diff = sum(1 for a, b in zip(surface, origin, strict=True) if a != b)
        if diff <= 1:
            return True
    return len(surface) == 1 and surface in _NAME_TYPO_CHARS


def validate_corpus(directory: Path) -> ValidationReport:
    """생성물 3종을 읽어 무결성을 검사합니다.

    설계 §9.8의 검증 항목을 코퍼스 소비자가 직접 돌릴 수 있게 옮긴 것이다.

    Args:
        directory: population.jsonl / corpus.jsonl / manifest.json 이 있는 디렉터리

    Returns:
        검사별 통과 여부와 실패 설명

    Raises:
        FileNotFoundError: 필요한 파일이 없는 경우
    """
    population_path = directory / "population.jsonl"
    corpus_path = directory / "corpus.jsonl"
    manifest_path = directory / "manifest.json"
    for path in (population_path, corpus_path, manifest_path):
        if not path.exists():
            raise FileNotFoundError(f"생성물을 찾을 수 없습니다: {path}")

    people = [
        json.loads(line)
        for line in population_path.read_text(encoding="utf-8").splitlines()
    ]
    documents = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors: list[str] = []

    employee_ids = [p["employee_id"] for p in people]
    employee_id_unique = len(set(employee_ids)) == len(employee_ids)
    if not employee_id_unique:
        errors.append(
            f"사번이 중복됐습니다: {len(employee_ids) - len(set(employee_ids))}건"
        )

    rrn_ok = True
    for person in people:
        if not _rrn_checksum_valid(person["rrn"]):
            rrn_ok = False
            if len(errors) < _MAX_REPORTED_ERRORS:
                errors.append(f"{person['person_id']}: 주민번호 체크섬 불일치")

    known_keys = {p["person_id"] for p in people}
    people_by_key = {p["person_id"]: p for p in people}
    span_roundtrip = True
    entity_key_resolvable = True
    surface_matches_origin = True
    for document in documents:
        text = document["text"]
        for span in document["spans"]:
            start, end = span["start"], span["end"]
            bounds_ok = 0 <= start < end <= len(text)
            if not bounds_ok:
                span_roundtrip = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: span 범위가 텍스트를 벗어납니다 "
                        f"({start}, {end}, 텍스트 길이 {len(text)})"
                    )
            elif text[start:end] != span["surface"]:
                span_roundtrip = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: span 오프셋 불일치 "
                        f"({span['start']}, {span['end']}, {span['type']})"
                    )
            if span["entity_key"] is not None and span["entity_key"] not in known_keys:
                entity_key_resolvable = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: 인구에 없는 entity_key {span['entity_key']}"
                    )

            entity_key = span["entity_key"]
            origin_field = _ORIGIN_FIELD_BY_TYPE.get(span["type"])
            if entity_key is None or origin_field is None:
                continue
            person = people_by_key.get(entity_key)
            if person is None:
                continue
            origin = person[origin_field]
            normalized = _normalize_surface(span["surface"])
            if not _surface_matches_origin(normalized, origin, span["type"]):
                surface_matches_origin = False
                if len(errors) < _MAX_REPORTED_ERRORS:
                    errors.append(
                        f"{document['id']}: surface가 원본 person 필드와 불일치 "
                        f"(type={span['type']}, surface={span['surface']!r}, "
                        f"origin={origin!r})"
                    )

    counts_match = manifest["counts"]["people"] == len(people) and manifest["counts"][
        "documents"
    ] == len(documents)
    if not counts_match:
        errors.append("manifest의 개수가 실제 파일과 다릅니다.")

    return ValidationReport(
        checks={
            "employee_id_unique": employee_id_unique,
            "rrn_checksum": rrn_ok,
            "span_roundtrip": span_roundtrip,
            "entity_key_resolvable": entity_key_resolvable,
            "manifest_counts_match": counts_match,
            "surface_matches_origin": surface_matches_origin,
        },
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    """검증 CLI 진입점입니다.

    Args:
        argv: 명령행 인자

    Returns:
        종료 코드 (0 = 모든 검사 통과)
    """
    parser = argparse.ArgumentParser(
        prog="python -m kopii.synth.validate",
        description="생성된 합성 코퍼스의 무결성을 검사합니다.",
    )
    parser.add_argument(
        "--dir", type=Path, default=Path("data"), help="생성물 디렉터리"
    )
    args = parser.parse_args(argv)

    report = validate_corpus(args.dir)
    for name, passed in sorted(report.checks.items()):
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    for message in report.errors:
        print(f"  - {message}")

    if not report.ok:
        print("\n코퍼스가 손상됐습니다. 이 코퍼스로 측정한 값은 신뢰할 수 없습니다.")
        return 1
    print("\n모든 검사를 통과했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
