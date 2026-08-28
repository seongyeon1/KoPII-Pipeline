"""합성 생성 CLI 테스트."""

import json
from pathlib import Path

from kopii.config.schema import CorpusConfig, PopulationConfig, SynthConfig
from kopii.span import Span
from kopii.synth.cli import run


def _small_config() -> SynthConfig:
    """테스트용 소형 설정."""
    return SynthConfig(
        population=PopulationConfig(size=30, seed=1, divisions=2),
        corpus=CorpusConfig(size=25, seed=2),
    )


def test_run_writes_all_artifacts(tmp_path: Path) -> None:
    """population·corpus·manifest 세 파일을 낸다."""
    counts = run(_small_config(), tmp_path)

    assert (tmp_path / "population.jsonl").exists()
    assert (tmp_path / "corpus.jsonl").exists()
    assert (tmp_path / "manifest.json").exists()
    assert counts == {"people": 30, "documents": 25}


def test_corpus_records_have_expected_shape(tmp_path: Path) -> None:
    """코퍼스 레코드가 설계 §9.5 포맷을 따른다."""
    run(_small_config(), tmp_path)
    lines = (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])

    assert set(record) == {"id", "genre", "text", "spans", "meta"}
    assert set(record["meta"]) == {"person_ids", "template"}
    for span in record["spans"]:
        assert set(span) == {"start", "end", "type", "surface", "entity_key"}


def test_written_spans_match_written_text(tmp_path: Path) -> None:
    """파일로 나간 뒤에도 span 오프셋이 본문과 맞아야 한다."""
    run(_small_config(), tmp_path)
    for line in (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        for raw in record["spans"]:
            span = Span(**raw)
            assert span.verify(record["text"]), record["id"]


def test_manifest_carries_id_scheme_ground_truth(tmp_path: Path) -> None:
    """manifest가 추론기 채점용 정답 메타를 담아야 한다."""
    run(_small_config(), tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["id_scheme"]["scheme"] == "sequential_block"
    assert manifest["id_scheme"]["structural_digits"]["FULLTIME"] == 2
    assert manifest["counts"] == {"people": 30, "documents": 25}


def test_same_seed_produces_identical_bytes(tmp_path: Path) -> None:
    """같은 시드면 산출 파일이 바이트 단위로 같아야 한다."""
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    run(_small_config(), first_dir)
    run(_small_config(), second_dir)

    for name in ("population.jsonl", "corpus.jsonl", "manifest.json"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()
