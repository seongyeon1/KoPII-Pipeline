"""템플릿 렌더링과 span 기록 테스트."""

import pytest

from kopii.synth.document import (
    DocumentTemplate,
    TemplateLine,
    generate_documents,
    load_templates,
    render_document,
)
from kopii.synth.population import generate_population


def _template(
    lines: list[TemplateLine], persons: tuple[int, int] = (1, 1)
) -> DocumentTemplate:
    """테스트용 템플릿을 만든다."""
    return DocumentTemplate(id="t_test", genre="test", persons=persons, lines=lines)


def test_records_span_for_pii_field() -> None:
    """PII 필드를 치환하면 span이 정확한 오프셋으로 기록돼야 한다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="담당자는 {person0.name}입니다.")])
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})

    assert len(doc.spans) == 1
    span = doc.spans[0]
    assert span.type == "NAME"
    assert span.verify(doc.text)
    assert span.entity_key == pop.people[0].person_id


def test_repeated_name_gets_distinct_offsets() -> None:
    """같은 값이 두 번 나오면 서로 다른 오프셋으로 기록돼야 한다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="{person0.name} / {person0.name}")])
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})

    assert len(doc.spans) == 2
    assert doc.spans[0].start != doc.spans[1].start
    for span in doc.spans:
        assert span.verify(doc.text)


def test_non_pii_field_produces_no_span() -> None:
    """소속·직급은 PII 타입 정본에 없으므로 span을 만들지 않는다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="{person0.team} {person0.title}")])
    doc = render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})
    assert doc.spans == ()


def test_requires_skips_line_when_field_missing() -> None:
    """닉네임이 없는 사람에게는 해당 줄을 건너뛴다."""
    pop = generate_population(size=200, seed=5, nickname_ratio=0.5)
    without = next(p for p in pop.people if p.nickname is None)
    template = _template(
        [
            TemplateLine(text="이름: {person0.name}"),
            TemplateLine(text="닉네임: {person0.nickname}", requires=["nickname"]),
        ]
    )
    doc = render_document("d_0", template, [without], {"date": "2026-01-02"})
    assert "닉네임" not in doc.text
    assert all(span.type != "NICKNAME" for span in doc.spans)


def test_repeat_emits_one_line_per_person() -> None:
    """repeat 줄은 등장 인물마다 한 줄씩 나와야 한다."""
    pop = generate_population(size=3, seed=1)
    template = _template(
        [TemplateLine(text="- {person.name}님", repeat="person")],
        persons=(3, 3),
    )
    doc = render_document("d_0", template, list(pop.people), {"date": "2026-01-02"})
    assert doc.text.count("\n") == 2
    assert len(doc.spans) == 3


def test_unknown_slot_raises() -> None:
    """정의되지 않은 슬롯은 조용히 남기지 않고 실패시킨다."""
    pop = generate_population(size=1, seed=1)
    template = _template([TemplateLine(text="{person0.no_such_field}")])
    with pytest.raises(ValueError, match="슬롯"):
        render_document("d_0", template, [pop.people[0]], {"date": "2026-01-02"})


def test_shipped_templates_load_with_expected_genres() -> None:
    """레포에 포함된 템플릿 6종이 전부 로드되고 장르가 맞아야 한다.

    렌더링 검증은 test_generate_documents_roundtrip_and_reproducible가
    전 템플릿에 대해 수행한다.
    """
    templates = load_templates()
    assert len(templates) == 6
    genres = {t.genre for t in templates}
    assert genres == {
        "meeting_note",
        "email",
        "hr_notice",
        "approval_doc",
        "chat_log",
        "issue_ticket",
    }


def test_generate_documents_roundtrip_and_reproducible() -> None:
    """생성된 모든 문서의 span이 텍스트와 일치하고 재현 가능해야 한다."""
    pop = generate_population(size=50, seed=1)
    templates = load_templates()
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

    first = generate_documents(pop, templates, count=40, genre_weights=weights, seed=7)
    second = generate_documents(pop, templates, count=40, genre_weights=weights, seed=7)

    assert len(first) == 40
    assert first == second
    for doc in first:
        for span in doc.spans:
            assert span.verify(doc.text), f"{doc.doc_id}: {span}"
