"""템플릿 렌더링과 span 기록 테스트."""

from collections import Counter

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


def test_two_separate_repeat_sections_both_render() -> None:
    """repeat 줄 - 평범한 줄 - repeat 줄 순서면 두 repeat 섹션이 모두 렌더링돼야 한다.

    첫 번째와 두 번째 repeat 구간이 평범한 줄로 갈라져 있으므로 서로 대안
    관계가 아니다. "이미 낸 인물" 집합이 문서 전체에서 공유되면 두 번째
    섹션은 아무것도 내지 못한다.
    """
    pop = generate_population(size=3, seed=1)
    template = _template(
        [
            TemplateLine(text="- {person.name}님 참석", repeat="person"),
            TemplateLine(text="---"),
            TemplateLine(text="- {person.name}님 처리", repeat="person"),
        ],
        persons=(3, 3),
    )
    doc = render_document("d_0", template, list(pop.people), {"date": "2026-01-02"})

    for person in pop.people:
        assert f"- {person.name}님 참석" in doc.text
        assert f"- {person.name}님 처리" in doc.text


def test_genre_weights_are_per_genre_not_per_template() -> None:
    """장르 가중치는 템플릿 개수가 아니라 장르 단위로 적용돼야 한다.

    한 장르에 템플릿 두 개, 다른 장르에 템플릿 하나를 같은 가중치로 등록해도
    관측된 장르 비율은 설정한 가중치(1:1)에 가까워야 한다 — 템플릿 개수(2:1)로
    쏠리면 안 된다.
    """
    pop = generate_population(size=20, seed=1)
    template_a1 = DocumentTemplate(
        id="a1",
        genre="genreA",
        persons=(1, 1),
        lines=[TemplateLine(text="A1 {person0.name}")],
    )
    template_a2 = DocumentTemplate(
        id="a2",
        genre="genreA",
        persons=(1, 1),
        lines=[TemplateLine(text="A2 {person0.name}")],
    )
    template_b1 = DocumentTemplate(
        id="b1",
        genre="genreB",
        persons=(1, 1),
        lines=[TemplateLine(text="B1 {person0.name}")],
    )

    docs = generate_documents(
        pop,
        [template_a1, template_a2, template_b1],
        count=400,
        genre_weights={"genreA": 1.0, "genreB": 1.0},
        seed=3,
    )

    counts = Counter(doc.genre for doc in docs)
    proportion_a = counts["genreA"] / len(docs)
    proportion_b = counts["genreB"] / len(docs)

    # ±10퍼센트포인트 — 몇 백 건 표본에서 흔들리지 않을 만큼 넉넉한 허용치.
    assert abs(proportion_a - 0.5) < 0.10, counts
    assert abs(proportion_b - 0.5) < 0.10, counts


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


def test_every_template_renders_at_min_and_max_persons() -> None:
    """모든 템플릿이 최소·최대 인원 수에서 렌더링되고 person_ids가 모두 텍스트에 나타나야 한다.

    템플릿의 persons 범위가 실제로 참조하는 personN 슬롯과 일치하는지 검증한다.
    특히 person_ids에 있는 모든 인물이 적어도 하나의 span entity_key로 나타나야 한다.
    이는 템플릿이 샘플된 인물을 모두 사용하도록 강제한다.
    """
    pop = generate_population(size=8, seed=1)
    templates = load_templates()
    doc_ctx = {"date": "2026-01-02", "serial": "0001"}

    for template in templates:
        min_persons, max_persons = template.persons

        # 최소 인원으로 렌더링
        people_min = list(pop.people[:min_persons])
        doc_min = render_document(f"min_{template.id}", template, people_min, doc_ctx)

        # 모든 span이 텍스트와 일치
        for span in doc_min.spans:
            assert span.verify(doc_min.text), (
                f"{template.id}: min span {span} does not verify"
            )

        # person_ids의 모든 인물이 최소 하나의 span에 나타남
        entity_keys_in_spans = {span.entity_key for span in doc_min.spans}
        for person_id in doc_min.person_ids:
            assert person_id in entity_keys_in_spans, (
                f"{template.id}: person {person_id} in person_ids but not in any span"
            )

        # 최대 인원으로 렌더링
        people_max = list(pop.people[:max_persons])
        doc_max = render_document(f"max_{template.id}", template, people_max, doc_ctx)

        # 모든 span이 텍스트와 일치
        for span in doc_max.spans:
            assert span.verify(doc_max.text), (
                f"{template.id}: max span {span} does not verify"
            )

        # person_ids의 모든 인물이 최소 하나의 span에 나타남
        entity_keys_in_spans = {span.entity_key for span in doc_max.spans}
        for person_id in doc_max.person_ids:
            assert person_id in entity_keys_in_spans, (
                f"{template.id}: person {person_id} in person_ids but not in any span"
            )
