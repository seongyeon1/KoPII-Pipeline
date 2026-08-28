"""합성 코퍼스 생성 CLI."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict
from pathlib import Path

from kopii import __version__
from kopii.config.schema import SynthConfig, load_synth_config
from kopii.synth.document import Document, generate_documents, load_templates
from kopii.synth.perturb import PerturbRates, perturb_document
from kopii.synth.population import Population, generate_population


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """JSONL을 결정적으로 씁니다.

    Args:
        path: 출력 경로
        records: 레코드 목록
    """
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _document_record(doc: Document) -> dict[str, object]:
    """문서를 설계 §9.5 포맷의 레코드로 바꿉니다.

    Args:
        doc: 대상 문서

    Returns:
        JSONL 한 줄에 해당하는 딕셔너리
    """
    return {
        "id": doc.doc_id,
        "genre": doc.genre,
        "text": doc.text,
        "spans": [
            {
                "start": span.start,
                "end": span.end,
                "type": span.type,
                "surface": span.surface,
                "entity_key": span.entity_key,
            }
            for span in doc.spans
        ],
        "meta": {
            "person_ids": list(doc.person_ids),
            "template": doc.template_id,
        },
    }


def run(config: SynthConfig, output_dir: Path) -> dict[str, int]:
    """설정대로 코퍼스를 생성해 파일로 씁니다.

    Args:
        config: 합성 설정
        output_dir: 산출물 디렉터리 (없으면 만든다)

    Returns:
        {"people": 인원 수, "documents": 문서 수}
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    population: Population = generate_population(
        size=config.population.size,
        seed=config.population.seed,
        scheme_name=config.population.id_scheme,
        divisions=config.population.divisions,
        teams_per_division=config.population.teams_per_division,
        nickname_ratio=config.population.nickname_ratio,
    )

    documents = generate_documents(
        population=population,
        templates=load_templates(),
        count=config.corpus.size,
        genre_weights=config.corpus.genres,
        seed=config.corpus.seed,
    )

    rates = PerturbRates(**config.corpus.perturb.model_dump())
    # 문서 생성용 RNG와 완전히 다른 스트림을 쓴다. 단순히 seed+1을 쓰면
    # seed=S의 흔들림 스트림이 seed=S+1의 문서 스트림과 같아져, 설정이
    # 하나 다른 두 코퍼스가 스트림을 공유하게 된다.
    rng = random.Random(f"perturb:{config.corpus.seed}")
    documents = [perturb_document(doc, rates, rng) for doc in documents]

    _write_jsonl(
        output_dir / "population.jsonl",
        [asdict(person) for person in population.people],
    )
    _write_jsonl(
        output_dir / "corpus.jsonl",
        [_document_record(doc) for doc in documents],
    )

    manifest = {
        "kopii_version": __version__,
        "config": config.model_dump(),
        "counts": {"people": len(population.people), "documents": len(documents)},
        "id_scheme": asdict(population.id_scheme),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"people": len(population.people), "documents": len(documents)}


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점입니다.

    Args:
        argv: 명령행 인자. None이면 sys.argv를 쓴다

    Returns:
        종료 코드 (0 = 성공)
    """
    parser = argparse.ArgumentParser(
        prog="python -m kopii.synth",
        description="한국어 PII 합성 코퍼스를 생성합니다.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="설정 YAML 경로 (생략 시 기본값으로 생성)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="산출물 디렉터리 (설정의 output_dir을 덮어쓴다)",
    )
    args = parser.parse_args(argv)

    config = load_synth_config(args.config) if args.config else SynthConfig()
    output_dir = args.out or Path(config.output_dir)

    counts = run(config, output_dir)
    print(
        f"생성 완료 — 구성원 {counts['people']}명, 문서 {counts['documents']}건 "
        f"→ {output_dir}"
    )
    return 0
