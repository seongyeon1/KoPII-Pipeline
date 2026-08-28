"""생성된 합성 코퍼스를 검증하는 CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

_RRN_WEIGHTS: tuple[int, ...] = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_MAX_REPORTED_ERRORS = 20


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
    span_roundtrip = True
    entity_key_resolvable = True
    for document in documents:
        text = document["text"]
        for span in document["spans"]:
            if text[span["start"] : span["end"]] != span["surface"]:
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
