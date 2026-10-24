"""생성물 검증 명령 테스트."""

import json
from pathlib import Path

from kopii.config.schema import CorpusConfig, PopulationConfig, SynthConfig
from kopii.synth.cli import run
from kopii.synth.validate import validate_corpus


def _generate(directory: Path) -> None:
    """검증 대상 코퍼스를 만든다."""
    config = SynthConfig(
        population=PopulationConfig(size=25, seed=1, divisions=2),
        corpus=CorpusConfig(size=20, seed=2),
    )
    run(config, directory)


def test_healthy_corpus_passes(tmp_path: Path) -> None:
    """정상 생성물은 모든 검사를 통과해야 한다."""
    _generate(tmp_path)
    report = validate_corpus(tmp_path)
    assert report.ok, report.errors
    assert report.checks["span_roundtrip"] is True
    assert report.checks["employee_id_unique"] is True
    assert report.checks["rrn_checksum"] is True
    assert report.checks["entity_key_resolvable"] is True


def test_detects_broken_span_offset(tmp_path: Path) -> None:
    """오프셋이 밀린 코퍼스를 잡아내야 한다."""
    _generate(tmp_path)
    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    damaged = json.loads(lines[0])
    damaged["text"] = "머리말 " + damaged["text"]  # span만 그대로 두어 오프셋을 민다
    lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["span_roundtrip"] is False


def test_detects_unknown_entity_key(tmp_path: Path) -> None:
    """인구에 없는 entity_key를 잡아내야 한다."""
    _generate(tmp_path)
    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    damaged = json.loads(lines[0])
    assert damaged["spans"], "첫 문서는 span을 포함해야 합니다"
    damaged["spans"][0]["entity_key"] = "p_99999"
    lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["entity_key_resolvable"] is False


def test_detects_duplicate_employee_id(tmp_path: Path) -> None:
    """중복된 사번을 잡아내야 한다."""
    _generate(tmp_path)
    population = tmp_path / "population.jsonl"
    lines = population.read_text(encoding="utf-8").splitlines()

    first = json.loads(lines[0])
    second = json.loads(lines[1])
    second["employee_id"] = first["employee_id"]
    lines[1] = json.dumps(second, ensure_ascii=False, sort_keys=True)
    population.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["employee_id_unique"] is False
    assert report.checks["span_roundtrip"] is True


def test_detects_invalid_rrn_checksum(tmp_path: Path) -> None:
    """주민번호 체크섬 오류를 잡아내야 한다."""
    _generate(tmp_path)
    population = tmp_path / "population.jsonl"
    lines = population.read_text(encoding="utf-8").splitlines()

    damaged = json.loads(lines[0])
    last_digit = int(damaged["rrn"][-1])
    new_last_digit = str((last_digit + 1) % 10)
    damaged["rrn"] = damaged["rrn"][:-1] + new_last_digit
    lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
    population.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["rrn_checksum"] is False
    assert report.checks["span_roundtrip"] is True


def test_detects_span_pointing_at_wrong_text(tmp_path: Path) -> None:
    """text와 span은 서로 일치해도 실제 인물 데이터를 가리키지 않으면 잡아내야 한다.

    리뷰어가 재현한 실패 형태를 그대로 만든다: span의 start/end를 한 칸씩
    왼쪽으로 밀면서 surface도 함께 새 위치의 텍스트로 갱신한다. 그러면
    text[start:end] == surface는 여전히 성립하므로 span_roundtrip은 통과하지만,
    surface는 더 이상 그 person의 실제 사번을 가리키지 않는다.
    """
    _generate(tmp_path)
    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    corrupted_index: int | None = None
    corrupted_record: dict | None = None
    for index, line in enumerate(lines):
        record = json.loads(line)
        text = record["text"]
        found = False
        for span in record["spans"]:
            if span["type"] != "EMPLOYEE_ID" or span["entity_key"] is None:
                continue
            start, end = span["start"], span["end"]
            if start < 1:
                continue
            new_start, new_end = start - 1, end - 1
            new_surface = text[new_start:new_end]
            if new_surface == span["surface"]:
                continue
            span["start"] = new_start
            span["end"] = new_end
            span["surface"] = new_surface
            found = True
            break
        if found:
            corrupted_index = index
            corrupted_record = record
            break

    assert corrupted_record is not None, "손상시킬 EMPLOYEE_ID span을 찾지 못했습니다"
    lines[corrupted_index] = json.dumps(
        corrupted_record, ensure_ascii=False, sort_keys=True
    )
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    # text와 span은 여전히 서로 맞으므로 기존 검사는 통과한다 — 바로 이 대비가
    # 새 검사(surface_matches_origin)가 옛 검사가 구조적으로 볼 수 없는 것을
    # 본다는 증거다.
    assert report.checks["span_roundtrip"] is True
    assert report.checks["surface_matches_origin"] is False


def test_detects_span_resolved_to_wrong_person(tmp_path: Path) -> None:
    """근접 순번 사번을 가진 다른 사람으로 잘못 귀속된 span을 잡아내야 한다.

    사번은 거의 순차로 발급되므로, 길이가 같고 한 글자만 다른 사번을 가진
    두 사람이 실제로 존재한다. 그런 span의 entity_key를 그 "이웃" 사람의
    person_id로 바꿔치기하면 text와 surface는 여전히 일치하고 entity_key도
    실존 인물을 가리키지만, 그 사람의 실제 사번과는 다르다 — 이 미묘한
    오귀속을 surface_matches_origin만 잡아낼 수 있어야 한다.
    """
    _generate(tmp_path)
    population = tmp_path / "population.jsonl"
    people = [
        json.loads(line) for line in population.read_text(encoding="utf-8").splitlines()
    ]
    employee_id_by_person = {p["person_id"]: p["employee_id"] for p in people}

    corpus = tmp_path / "corpus.jsonl"
    lines = corpus.read_text(encoding="utf-8").splitlines()

    corrupted_index: int | None = None
    corrupted_record: dict | None = None
    neighbor_person_id: str | None = None
    for index, line in enumerate(lines):
        record = json.loads(line)
        for span in record["spans"]:
            if span["type"] != "EMPLOYEE_ID" or span["entity_key"] is None:
                continue
            origin_person_id = span["entity_key"]
            origin_employee_id = employee_id_by_person[origin_person_id]
            for candidate_id, candidate_employee_id in employee_id_by_person.items():
                if candidate_id == origin_person_id:
                    continue
                if len(candidate_employee_id) != len(origin_employee_id):
                    continue
                diff = sum(
                    1
                    for a, b in zip(
                        candidate_employee_id, origin_employee_id, strict=True
                    )
                    if a != b
                )
                if diff == 1:
                    neighbor_person_id = candidate_id
                    break
            if neighbor_person_id is not None:
                span["entity_key"] = neighbor_person_id
                break
        if neighbor_person_id is not None:
            corrupted_index = index
            corrupted_record = record
            break

    assert corrupted_record is not None, "근접 순번 사번을 가진 이웃을 찾지 못했습니다"
    lines[corrupted_index] = json.dumps(
        corrupted_record, ensure_ascii=False, sort_keys=True
    )
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = validate_corpus(tmp_path)
    # text와 surface는 여전히 일치하고(span_roundtrip) entity_key도 실존 인물을
    # 가리키므로(entity_key_resolvable) 두 검사는 통과한다. 오직
    # surface_matches_origin만 이 span이 잘못된 사람에게 귀속됐다는 것을 본다.
    assert report.checks["span_roundtrip"] is True
    assert report.checks["entity_key_resolvable"] is True
    assert report.checks["surface_matches_origin"] is False


def test_detects_manifest_count_mismatch(tmp_path: Path) -> None:
    """manifest 개수 불일치를 잡아내야 한다."""
    _generate(tmp_path)
    manifest = tmp_path / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))

    data["counts"]["documents"] = data["counts"]["documents"] + 1
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    report = validate_corpus(tmp_path)
    assert report.ok is False
    assert report.checks["manifest_counts_match"] is False
