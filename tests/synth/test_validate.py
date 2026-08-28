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
    if damaged["spans"]:
        damaged["spans"][0]["entity_key"] = "p_99999"
        lines[0] = json.dumps(damaged, ensure_ascii=False, sort_keys=True)
        corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = validate_corpus(tmp_path)
        assert report.ok is False
        assert report.checks["entity_key_resolvable"] is False
