"""표기 흔들림 주입과 span 오프셋 재계산."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

from kopii.span import Span
from kopii.synth.document import Document

_HONORIFICS: tuple[str, ...] = ("님", "씨", "", " 선임", " 책임", " 프로")
_SEPARATORS: tuple[str, ...] = (" · ", " / ", " | ", "\t", ", ", " ")
_TYPO_POOL: str = "가나다라마바사아자차카타파하"


@dataclass(frozen=True, slots=True)
class Edit:
    """텍스트 편집 한 건.

    Args:
        start: 시작 오프셋 (포함)
        end: 끝 오프셋 (제외). start와 같으면 삽입
        text: 대체할 문자열
    """

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class PerturbRates:
    """흔들림별 적용 확률.

    Args:
        honorific_variation: 호칭 접미사 변형 확률
        partial_name: 이름을 성만 남길 확률
        separator_variation: 구분자 변형 확률
        line_break_split: 사번 중간에 줄바꿈을 끼울 확률
        typo: 이름에 오타를 낼 확률
        space_insertion: 전화번호 하이픈 주위에 공백을 넣을 확률
    """

    honorific_variation: float
    partial_name: float
    separator_variation: float
    line_break_split: float
    typo: float
    space_insertion: float


def apply_edits(
    text: str, spans: Sequence[Span], edits: Sequence[Edit]
) -> tuple[str, list[Span]]:
    """편집을 적용하고 span 오프셋을 재계산합니다.

    편집은 세 가지만 허용한다 — span 바깥, span 안쪽, span 전체 치환.
    span 경계를 반만 덮는 편집은 정답 라벨을 조용히 망가뜨리므로 거부한다.

    Args:
        text: 원본 텍스트
        spans: 원본 span 목록
        edits: 적용할 편집 목록

    Returns:
        (편집된 텍스트, 재계산된 span 목록). 폭이 0이 된 span은 빠진다

    Raises:
        ValueError: 편집끼리 겹치거나 span 경계를 부분적으로 침범하는 경우
    """
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.start < previous.end:
            raise ValueError(f"편집이 서로 겹칩니다: {previous} 와 {current}")

    for edit in ordered:
        for span in spans:
            crosses_start = edit.start < span.start < edit.end
            crosses_end = edit.start < span.end < edit.end
            inside = span.start <= edit.start and edit.end <= span.end
            if (crosses_start or crosses_end) and not inside:
                raise ValueError(
                    f"편집이 span 경계를 부분적으로 침범합니다: {edit} / {span}"
                )

    # 텍스트를 뒤에서부터 고쳐 앞쪽 오프셋이 흔들리지 않게 한다.
    chunks: list[str] = []
    cursor = 0
    for edit in ordered:
        chunks.append(text[cursor : edit.start])
        chunks.append(edit.text)
        cursor = edit.end
    chunks.append(text[cursor:])
    new_text = "".join(chunks)

    new_spans: list[Span] = []
    for span in spans:
        start = span.start
        end = span.end
        for edit in ordered:
            delta = len(edit.text) - (edit.end - edit.start)
            if edit.end <= span.start:
                start += delta
                end += delta
            elif span.start <= edit.start and edit.end <= span.end:
                end += delta
        if end <= start:
            continue
        new_spans.append(
            replace(span, start=start, end=end, surface=new_text[start:end])
        )

    return new_text, new_spans


def _honorific_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름 뒤의 '님'을 다른 호칭으로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "NAME" or rng.random() >= rate:
            continue
        if doc.text[span.end : span.end + 1] == "님":
            edits.append(
                Edit(start=span.end, end=span.end + 1, text=rng.choice(_HONORIFICS))
            )
    return edits


def _partial_name_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름을 성 한 글자만 남기는 편집을 만듭니다."""
    return [
        Edit(start=span.start, end=span.end, text=span.surface[0])
        for span in doc.spans
        if span.type == "NAME" and len(span.surface) > 1 and rng.random() < rate
    ]


def _separator_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """' · ' 구분자를 다른 표기로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    start = doc.text.find(" · ")
    while start != -1:
        if rng.random() < rate:
            edits.append(Edit(start=start, end=start + 3, text=rng.choice(_SEPARATORS)))
        start = doc.text.find(" · ", start + 3)
    return edits


def _line_break_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """사번 중간에 줄바꿈을 끼우는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "EMPLOYEE_ID" or len(span.surface) < 3:
            continue
        if rng.random() >= rate:
            continue
        cut = span.start + rng.randint(1, len(span.surface) - 1)
        edits.append(Edit(start=cut, end=cut, text="\n"))
    return edits


def _typo_edits(doc: Document, rate: float, rng: random.Random) -> list[Edit]:
    """이름 한 글자를 다른 음절로 바꾸는 편집을 만듭니다."""
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "NAME" or rng.random() >= rate:
            continue
        offset = rng.randrange(len(span.surface))
        position = span.start + offset
        edits.append(
            Edit(start=position, end=position + 1, text=rng.choice(_TYPO_POOL))
        )
    return edits


def _space_insertion_edits(
    doc: Document, rate: float, rng: random.Random
) -> list[Edit]:
    """전화번호 하이픈 주위에 공백을 넣는 편집을 만듭니다.

    "010-0000-0000"이 "010 - 0000 - 0000"처럼 쓰이는 실제 표기를 재현한다.
    (문서의 예시는 자리표시 값을 쓴다 — scripts/pii_scan.py가 그럴듯한 번호를 반려한다.)
    span 안쪽 편집이므로 폭과 surface가 함께 갱신된다.
    """
    edits: list[Edit] = []
    for span in doc.spans:
        if span.type != "PHONE" or rng.random() >= rate:
            continue
        for offset, char in enumerate(span.surface):
            if char == "-":
                position = span.start + offset
                edits.append(Edit(start=position, end=position + 1, text=" - "))
    return edits


def _drop_conflicts(edits: list[Edit]) -> list[Edit]:
    """겹치는 편집 중 (start, end) 기준으로 정렬했을 때 가장 앞선 것만 남깁니다.

    서로 다른 흔들림이 같은 구간을 노릴 수 있다. 생성된 순서가 아니라
    (start, end)로 정렬한 뒤 가장 앞에 오는 편집을 남기고 뒤엣것을 버린다 —
    어느 쪽을 남겨도 흔들림의 목적은 달성되고, 정렬 기준이 고정돼 있으므로
    같은 시드에서는 항상 같은 결과가 나와 결정적으로 동작한다.

    Args:
        edits: 후보 편집 목록

    Returns:
        서로 겹치지 않는 편집 목록
    """
    kept: list[Edit] = []
    for edit in sorted(edits, key=lambda e: (e.start, e.end)):
        if kept and edit.start < kept[-1].end:
            continue
        kept.append(edit)
    return kept


def perturb_document(
    doc: Document, rates: PerturbRates, rng: random.Random
) -> Document:
    """문서에 표기 흔들림을 넣고 span을 재계산합니다.

    Args:
        doc: 원본 문서
        rates: 흔들림별 확률
        rng: 난수 생성기

    Returns:
        흔들림이 적용된 새 Document
    """
    candidates: list[Edit] = []
    candidates += _honorific_edits(doc, rates.honorific_variation, rng)
    candidates += _partial_name_edits(doc, rates.partial_name, rng)
    candidates += _separator_edits(doc, rates.separator_variation, rng)
    candidates += _line_break_edits(doc, rates.line_break_split, rng)
    candidates += _typo_edits(doc, rates.typo, rng)
    candidates += _space_insertion_edits(doc, rates.space_insertion, rng)

    edits = _drop_conflicts(candidates)
    if not edits:
        return doc

    new_text, new_spans = apply_edits(doc.text, doc.spans, edits)
    return Document(
        doc_id=doc.doc_id,
        genre=doc.genre,
        template_id=doc.template_id,
        text=new_text,
        spans=tuple(new_spans),
        person_ids=doc.person_ids,
    )
