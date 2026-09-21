"""Small synthetic fixture corpus; not reconstruction of the historical 100k corpus."""

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

from kopii.research.experiment import atomic_json

TEMPLATES = [
    ("mail", "[[PERSON_NAME:{name}]]의 회신 주소는 [[EMAIL:{email}]]입니다."),
    ("support", "상담 담당 [[PERSON_NAME:{name}]]에게 [[EMAIL:{email}]]로 문의했습니다."),
    ("meeting", "회의록 담당자: [[PERSON_NAME:{name}]]. 배포 주소: [[EMAIL:{email}]]."),
    ("application", "신청인 [[PERSON_NAME:{name}]] / 연락 메일 [[EMAIL:{email}]]"),
    ("handover", "인수인계 문서에 [[EMAIL:{email}]]와 담당 [[PERSON_NAME:{name}]]을 기재했습니다."),
    ("notice", "공지 수신인 [[PERSON_NAME:{name}]]의 메일은 [[EMAIL:{email}]]로 확인했습니다."),
]


def materialize(template: str) -> tuple[str, list[dict[str, Any]]]:
    """Remove annotation markers while calculating Unicode offsets."""
    text, spans, cursor = "", [], 0
    for match in re.finditer(r"\[\[([A-Z_]+):([^\]]+)\]\]", template):
        text += template[cursor : match.start()]
        start = len(text)
        text += match[2]
        spans.append({"start": start, "end": len(text), "label": match[1]})
        cursor = match.end()
    return text + template[cursor:], spans


def generate(output: Path, seed: int = 42, per_template: int = 12) -> dict[str, Any]:
    """Generate template-disjoint train/dev/test fixture data with reproducible splits."""
    if per_template < 1:
        raise ValueError("per_template must be positive")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Synthetic output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    families = list(TEMPLATES)
    rng.shuffle(families)
    assignment = {
        name: ("train" if i < 4 else "dev" if i == 4 else "test")
        for i, (name, _) in enumerate(families)
    }
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    for family, template in families:
        for index in range(per_template):
            name = rng.choice(["김하늘", "이바다", "박가람", "최나래"])
            text, spans = materialize(
                template.format(
                    name=name,
                    email=f"fixture-{family}-{index}@example.invalid",
                )
            )
            group = f"{family}-{index}"
            splits[assignment[family]].append(
                {
                    "id": group,
                    "group_id": group,
                    "text": text,
                    "spans": spans,
                    "meta": {"source": "synthetic_fixture", "template_family": family},
                }
            )
            splits[assignment[family]].append(
                {
                    "id": group + "-negative",
                    "group_id": group,
                    "text": f"시험용 작업 코드 {family.upper()}-{index:04d}의 상태는 완료입니다.",
                    "spans": [],
                    "meta": {"source": "synthetic_fixture", "template_family": family},
                }
            )
    for split, rows in splits.items():
        (output / f"{split}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    manifest = {
        "purpose": "Pipeline/training smoke data only; no real-world performance claims",
        "seed": seed,
        "per_template": per_template,
        "family_splits": assignment,
        "records": {key: len(value) for key, value in splits.items()},
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "historical_100k_reproduction": False,
    }
    atomic_json(output / "manifest.json", manifest)
    return manifest
