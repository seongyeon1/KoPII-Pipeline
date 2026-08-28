"""표기 흔들림과 span 오프셋 재계산 테스트."""

import random

import pytest

from kopii.span import Span
from kopii.synth.document import generate_documents, load_templates
from kopii.synth.perturb import Edit, PerturbRates, apply_edits, perturb_document
from kopii.synth.population import generate_population

_NO_PERTURB = PerturbRates(
    honorific_variation=0.0,
    partial_name=0.0,
    separator_variation=0.0,
    line_break_split=0.0,
    typo=0.0,
    space_insertion=0.0,
)
_ALWAYS = PerturbRates(
    honorific_variation=1.0,
    partial_name=1.0,
    separator_variation=1.0,
    line_break_split=1.0,
    typo=1.0,
    space_insertion=1.0,
)


def test_edit_before_span_shifts_offsets() -> None:
    """span 앞쪽 편집은 오프셋만 민다."""
    text = "안녕 김민수님"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    new_text, new_spans = apply_edits(
        text, spans, [Edit(start=0, end=2, text="반갑다")]
    )

    assert new_text == "반갑다 김민수님"
    assert new_spans[0].verify(new_text)


def test_edit_inside_span_updates_surface() -> None:
    """span 안쪽 편집은 폭과 surface를 갱신한다."""
    text = "사번 2304118 확인"
    spans = [Span(start=3, end=10, type="EMPLOYEE_ID", surface="2304118")]
    new_text, new_spans = apply_edits(text, spans, [Edit(start=6, end=6, text="\n")])

    assert new_spans[0].surface == "230\n4118"
    assert new_spans[0].verify(new_text)


def test_space_insertion_keeps_phone_span_intact() -> None:
    """전화번호에 공백을 넣어도 span이 텍스트와 일치해야 한다."""
    pop = generate_population(size=5, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=10, genre_weights={"issue_ticket": 1.0}, seed=3
    )
    rates = PerturbRates(
        honorific_variation=0.0,
        partial_name=0.0,
        separator_variation=0.0,
        line_break_split=0.0,
        typo=0.0,
        space_insertion=1.0,
    )
    rng = random.Random(5)
    for doc in docs:
        perturbed = perturb_document(doc, rates, rng)
        for span in perturbed.spans:
            assert span.verify(perturbed.text)
            if span.type == "PHONE":
                assert " - " in span.surface


def test_edit_replacing_whole_span_updates_surface() -> None:
    """span 전체를 바꾸면 새 surface가 반영된다."""
    text = "담당 김민수 확인"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    new_text, new_spans = apply_edits(text, spans, [Edit(start=3, end=6, text="김")])

    assert new_text == "담당 김 확인"
    assert new_spans[0].surface == "김"
    assert new_spans[0].verify(new_text)


def test_partial_overlap_is_rejected() -> None:
    """span 경계를 반만 덮는 편집은 조용히 넘기지 않고 실패시킨다."""
    text = "담당 김민수 확인"
    spans = [Span(start=3, end=6, type="NAME", surface="김민수")]
    with pytest.raises(ValueError, match="부분적으로"):
        apply_edits(text, spans, [Edit(start=2, end=5, text="X")])


def test_overlapping_edits_are_rejected() -> None:
    """편집끼리 겹치면 실패시킨다."""
    text = "abcdef"
    with pytest.raises(ValueError, match="겹칩니다"):
        apply_edits(
            text, [], [Edit(start=0, end=3, text="X"), Edit(start=2, end=4, text="Y")]
        )


def test_zero_rates_leave_document_unchanged() -> None:
    """확률이 0이면 문서가 그대로여야 한다."""
    pop = generate_population(size=20, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=10, genre_weights={"meeting_note": 1.0}, seed=3
    )
    for doc in docs:
        assert perturb_document(doc, _NO_PERTURB, random.Random(0)) == doc


def test_all_spans_survive_full_perturbation() -> None:
    """모든 흔들림을 켜도 span이 텍스트와 일치해야 한다."""
    pop = generate_population(size=30, seed=1)
    weights = dict.fromkeys(
        (
            "meeting_note",
            "email",
            "hr_notice",
            "approval_doc",
            "chat_log",
            "issue_ticket",
        ),
        1.0,
    )
    docs = generate_documents(
        pop, load_templates(), count=60, genre_weights=weights, seed=4
    )

    rng = random.Random(11)
    for doc in docs:
        perturbed = perturb_document(doc, _ALWAYS, rng)
        for span in perturbed.spans:
            assert span.verify(perturbed.text), f"{perturbed.doc_id}: {span}"


def test_perturbation_is_reproducible() -> None:
    """같은 시드면 같은 흔들림 결과가 나와야 한다."""
    pop = generate_population(size=20, seed=1)
    docs = generate_documents(
        pop, load_templates(), count=5, genre_weights={"chat_log": 1.0}, seed=3
    )
    first = [perturb_document(d, _ALWAYS, random.Random(2)) for d in docs]
    second = [perturb_document(d, _ALWAYS, random.Random(2)) for d in docs]
    assert first == second
