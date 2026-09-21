"""Publish aggregate-only metadata comparison tables and a standalone figure."""

import argparse
import json
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from kopii.research.experiment import atomic_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results", type=Path, default=Path("output/metadata-study-final/results.json")
    )
    args = parser.parse_args()
    result = json.loads(args.results.read_text())
    if result.get("complete") is not True or result["retriever"] != "BM25":
        raise ValueError(
            "This report requires the completed BM25 extension; report dense runs separately"
        )
    root = Path("research/results")
    root.mkdir(parents=True, exist_ok=True)

    def stats(condition, level, policy, view, metric):
        values = [w["conditions"][condition][level][policy][view][metric] for w in result["worlds"]]
        return {"mean": mean(values), "min": min(values), "max": max(values)}

    summary = {}
    lines = [
        "# 조직 메타데이터 검색 후속 실험",
        "",
        "E3 결과를 본 뒤 추가한 비교다. 기존 3개 가상 조직·720개 문서·NER 예측을 "
        "재사용했으며 독립 업무 평가가 아니다. 기존 BM25 마스킹/본문 치환 점수는 "
        "모든 조건에서 이전 실행과 일치함을 자동 확인했다.",
        "",
        "## 같은 문서 전체를 대상으로 한 비교",
        "",
        "각 수준의 Recall@5는 그 수준을 명시한 질의에 대한 값이다. "
        "개인 추정은 명부·직급·프로젝트를 아는 공격자가 **본문만 보는 조건**, "
        "분모는 전체 720개 문서다. 값은 세 세계의 평균이며 괄호는 최솟값–최댓값이다. "
        "이 범위는 모집단 신뢰구간이 아니다.",
        "",
    ]
    for condition in ("gold", "roberta"):
        lines += [
            f"### {condition}",
            "",
            "| 수준 | 방식 | Recall@5 % (범위) | 본문 개인 추정 % (범위) | 빈 결과 질의 % |",
            "|---|---|---:|---:|---:|",
        ]
        summary[condition] = {}
        for level in ("team", "division", "center"):
            summary[condition][level] = {}
            for policy in ("mask", "inline", "metadata_filter"):
                measures = {
                    "recall_at_5": stats(condition, level, policy, "retrieval", "recall_at_5"),
                    "text_attack": stats(
                        condition, level, policy, "released_text_only", "expected_top1"
                    ),
                    "empty_result": stats(condition, level, policy, "retrieval", "empty_result"),
                }
                summary[condition][level][policy] = measures

                def fmt(key, row=measures):
                    v = row[key]
                    return f"{100 * v['mean']:.2f} ({100 * v['min']:.2f}–{100 * v['max']:.2f})"

                lines.append(
                    f"| {level} | {policy} | {fmt('recall_at_5')} | {fmt('text_attack')} | "
                    f"{100 * measures['empty_result']['mean']:.2f} |"
                )
        lines.append("")
    lines += [
        "## 필터가 알려졌을 때: 같은 조회 성공 문서끼리 비교",
        "",
        "각 세계의 240개 중 212개, 총 **636개(88.33%)**에 조직 메타데이터가 있다. "
        "아래 모든 공격 점수는 이 동일한 부분집합을 분모로 삼는다. "
        "공격자가 문서가 반환된 조직 필터를 알면 그 조직을 단서로 추가한다. "
        "이는 관찰 가능한 경우의 조건부 위험이며, 실제 top-5 반환 "
        "빈도·질의 분포·로그 접근 빈도를 측정한 값은 아니다.",
        "",
        "| 탐지 | 수준 | 본문 치환: 본문 관찰 % | 메타데이터: 본문만 % | "
        "메타데이터: 필터도 관찰 % |",
        "|---|---|---:|---:|---:|",
    ]
    for condition in ("gold", "roberta"):
        for level in ("team", "division", "center"):
            inline = stats(
                condition, level, "inline", "released_text_only_resolved_subset", "expected_top1"
            )
            text = stats(
                condition,
                level,
                "metadata_filter",
                "released_text_only_resolved_subset",
                "expected_top1",
            )
            member = stats(
                condition, level, "metadata_filter", "known_filter_membership", "expected_top1"
            )
            summary[condition][level]["matched_subset"] = {
                "inline": inline,
                "metadata_text_only": text,
                "metadata_filter_known": member,
            }
            lines.append(
                f"| {condition} | {level} | {100 * inline['mean']:.2f} | "
                f"{100 * text['mean']:.2f} | {100 * member['mean']:.2f} |"
            )
    lines += [
        "",
        "## 해석과 범위",
        "",
        "- 본문에 조직명을 직접 넣지 않아도, 별도 메타데이터 필터로 "
        "이 합성 조직 질의의 검색 품질을 비슷하게 유지했다. 차이에 "
        "대한 통계적 동등성 검정은 하지 않았다.",
        "- 본문만 유출되는 조건과 검색을 사용할 수 있는 공격자를 "
        "구분해야 한다. 같은 조회 성공 문서에서는 필터 관찰 위험이 "
        "본문 치환 위험과 같았다.",
        "- 실제 NER 조건의 낮은 공격 점수에는 직급·프로젝트 등 추가 "
        "정보 삭제가 작용한다. 이를 더 정확한 이름 탐지로 해석하지 "
        "않는다.",
        "- 명부 누락·모호성은 메타데이터 없음으로 남고, 오래된 "
        "명부의 잘못된 범주는 정답으로 교정하지 않는다. 전체 "
        "검색으로 폴백하지 않는다.",
        "- 전체 조직 조회가 허용된 가상 사용자를 가정한다. 권한 검사 "
        "함수의 거부 동작만 테스트했으며 제품 인증·문서 ACL·로그 "
        "보호를 검증한 실험이 아니다.",
        "- 본문은 고정 템플릿이고, 질의 조직명은 알려진 문자열로 "
        "파싱한다. 실제 업무 자료·운영 NPU 임베딩·LLM QA·강한 공격자는 "
        "미측정이다.",
        "",
        "![팀 검색과 본문 노출 위험](figures/metadata-comparison.png)",
        "",
        "재현: [실행 안내](../METADATA_STUDY.md). 전체 시드별 집계: "
        "[JSON](metadata-retrieval.json).",
    ]

    def public_precision(value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, dict):
            return {k: public_precision(v) for k, v in value.items()}
        if isinstance(value, list):
            return [public_precision(v) for v in value]
        return value

    atomic_json(root / "metadata-retrieval.json", public_precision(result))
    atomic_json(root / "metadata-summary.json", public_precision(summary))
    (root / "metadata-tables.md").write_text("\n".join(lines) + "\n")
    plt.rcParams["svg.fonttype"] = "none"
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), layout="constrained")
    policies = ("mask", "inline", "metadata_filter")
    colors = ("#8b95a5", "#d27842", "#347e91")
    for axis, metric, title in zip(
        axes,
        ("recall_at_5", "text_attack"),
        ("Team-query Recall@5", "Text-only expected identity inference"),
        strict=True,
    ):
        for i, (policy, color) in enumerate(zip(policies, colors, strict=True)):
            values = [100 * summary[c]["team"][policy][metric]["mean"] for c in ("gold", "roberta")]
            positions = [x + (i - 1) * 0.24 for x in (0, 1)]
            bars = axis.bar(positions, values, 0.22, color=color, label=policy)
            axis.bar_label(bars, fmt="%.2f", fontsize=8, padding=3)
        axis.set_xticks([0, 1], ["Gold names", "Actual NER"])
        axis.set_ylim(0, 100)
        axis.set_ylabel("Percent")
        axis.set_title(title)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].legend(loc="upper center", ncol=3, fontsize=8)
    fig.suptitle(
        "720 fictional documents · BM25 · mean across 3 worlds\nFilter-membership exposure "
        "is a separate conditional attack (see table)",
        fontsize=11,
    )
    (root / "figures").mkdir(exist_ok=True)
    for suffix in ("png", "svg"):
        artifact = root / "figures" / f"metadata-comparison.{suffix}"
        fig.savefig(artifact, dpi=180)
        if suffix == "svg":
            artifact.write_text(
                "\n".join(line.rstrip() for line in artifact.read_text().splitlines()) + "\n"
            )
    plt.close(fig)


if __name__ == "__main__":
    main()
