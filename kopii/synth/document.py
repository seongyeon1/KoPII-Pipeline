"""템플릿을 렌더링하며 PII span 오프셋을 기록하는 Stage 2."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from kopii.span import Span
from kopii.synth.population import Person, Population

# 슬롯 문법: {person0.name}, {person.name}(repeat 안), {doc.date}
_SLOT_RE = re.compile(r"\{(\w+)\.(\w+)\}")

# Person 필드 중 PII로 취급해 span을 기록할 것들.
# 소속·직급·출생연도는 준식별자지만 PII 타입 정본에 없으므로 span을 만들지 않는다.
FIELD_TYPES: dict[str, str] = {
    "name": "NAME",
    "nickname": "NICKNAME",
    "employee_id": "EMPLOYEE_ID",
    "rrn": "RRN",
    "phone": "PHONE",
    "email": "EMAIL",
    "address": "ADDRESS",
}

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateLine(BaseModel):
    """템플릿의 한 줄.

    Args:
        text: 슬롯이 포함된 줄 문자열
        repeat: "person"이면 등장 인물마다 한 줄씩 반복한다
        requires: 이 필드들이 비어 있는 인물에게는 줄을 건너뛴다
    """

    text: str
    repeat: str | None = None
    requires: list[str] = Field(default_factory=list)


class DocumentTemplate(BaseModel):
    """장르별 문서 템플릿.

    Args:
        id: 템플릿 식별자
        genre: 장르 이름
        persons: 등장 인물 수 범위 (최소, 최대)
        lines: 줄 목록
    """

    id: str
    genre: str
    persons: tuple[int, int]
    lines: list[TemplateLine]


@dataclass(frozen=True, slots=True)
class Document:
    """생성된 문서 한 건.

    Args:
        doc_id: 문서 식별자
        genre: 장르
        template_id: 사용한 템플릿 id
        text: 본문
        spans: 정답 PII span 목록
        person_ids: 등장 인물의 person_id 목록
    """

    doc_id: str
    genre: str
    template_id: str
    text: str
    spans: tuple[Span, ...]
    person_ids: tuple[str, ...]


def load_templates(directory: Path | None = None) -> list[DocumentTemplate]:
    """템플릿 YAML을 모두 읽어들입니다.

    Args:
        directory: 템플릿 디렉터리. None이면 패키지 내장 디렉터리

    Returns:
        파일명 순으로 정렬된 템플릿 목록
    """
    target = directory or _TEMPLATE_DIR
    templates: list[DocumentTemplate] = []
    for path in sorted(target.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates.append(DocumentTemplate.model_validate(raw))
    return templates


def _resolve(
    obj: str, field: str, actors: dict[str, Person], doc_ctx: dict[str, str]
) -> tuple[str, Person | None]:
    """슬롯 하나를 값으로 풉니다.

    Args:
        obj: 슬롯의 객체 부분 ("doc", "person", "person0" 등)
        field: 슬롯의 필드 부분
        actors: 별칭 → Person
        doc_ctx: 문서 수준 컨텍스트

    Returns:
        (치환할 문자열, 이 값의 주인 Person 또는 None)

    Raises:
        ValueError: 알 수 없는 슬롯이거나 값이 비어 있는 경우
    """
    if obj == "doc":
        if field not in doc_ctx:
            raise ValueError(f"알 수 없는 문서 슬롯입니다: {{doc.{field}}}")
        return doc_ctx[field], None

    person = actors.get(obj)
    if person is None:
        raise ValueError(f"알 수 없는 인물 슬롯입니다: {{{obj}.{field}}}")
    if not hasattr(person, field):
        raise ValueError(f"알 수 없는 인물 필드 슬롯입니다: {{{obj}.{field}}}")

    value = getattr(person, field)
    if value is None:
        raise ValueError(
            f"{obj}.{field}가 비어 있습니다. 템플릿의 requires로 걸러야 합니다."
        )
    return str(value), person


def _render_line(
    text: str,
    actors: dict[str, Person],
    doc_ctx: dict[str, str],
    base_offset: int,
) -> tuple[str, list[Span]]:
    """한 줄을 렌더링하며 span을 기록합니다.

    치환하는 순간에 오프셋을 적는다. 완성된 텍스트에서 값을 되짚어 찾으면
    같은 값이 여러 번 등장할 때 틀린 위치를 잡는다.

    Args:
        text: 슬롯이 포함된 줄
        actors: 별칭 → Person
        doc_ctx: 문서 수준 컨텍스트
        base_offset: 이 줄이 문서에서 시작하는 오프셋

    Returns:
        (렌더된 줄, 이 줄에서 생긴 span 목록)
    """
    parts: list[str] = []
    spans: list[Span] = []
    cursor = 0
    length = 0

    for match in _SLOT_RE.finditer(text):
        literal = text[cursor : match.start()]
        parts.append(literal)
        length += len(literal)

        value, person = _resolve(match.group(1), match.group(2), actors, doc_ctx)
        field = match.group(2)
        if person is not None and field in FIELD_TYPES:
            spans.append(
                Span(
                    start=base_offset + length,
                    end=base_offset + length + len(value),
                    type=FIELD_TYPES[field],
                    surface=value,
                    entity_key=person.person_id,
                )
            )
        parts.append(value)
        length += len(value)
        cursor = match.end()

    parts.append(text[cursor:])
    return "".join(parts), spans


def _line_is_renderable(line: TemplateLine, actors: dict[str, Person]) -> bool:
    """requires 조건을 만족해 이 줄을 낼 수 있는지 판정합니다.

    Args:
        line: 대상 줄
        actors: 별칭 → Person

    Returns:
        줄에서 참조하는 모든 인물이 requires 필드를 갖고 있으면 True
    """
    if not line.requires:
        return True
    referenced = {
        actors[obj] for obj, _field in _SLOT_RE.findall(line.text) if obj in actors
    }
    return all(
        getattr(person, field, None) is not None
        for person in referenced
        for field in line.requires
    )


def render_document(
    doc_id: str,
    template: DocumentTemplate,
    people: list[Person],
    doc_ctx: dict[str, str],
) -> Document:
    """템플릿과 인물로 문서 한 건을 만듭니다.

    Args:
        doc_id: 문서 식별자
        template: 사용할 템플릿
        people: 등장 인물 (순서가 person0, person1, ... 에 대응)
        doc_ctx: 문서 수준 컨텍스트 (date, serial 등)

    Returns:
        렌더된 Document

    Raises:
        ValueError: 템플릿이 없는 인물 슬롯이나 필드를 참조하는 경우
    """
    actors: dict[str, Person] = {
        f"person{index}": person for index, person in enumerate(people)
    }

    rendered: list[str] = []
    spans: list[Span] = []
    offset = 0
    emitted_repeat_keys: set[str] = set()

    for line in template.lines:
        if line.repeat == "person":
            # repeat 줄은 인물마다 한 번씩, "person" 별칭으로 낸다.
            for person in people:
                scoped = dict(actors)
                scoped["person"] = person
                if not _line_is_renderable(line, scoped):
                    continue
                if person.person_id in emitted_repeat_keys:
                    continue
                emitted_repeat_keys.add(person.person_id)
                text, line_spans = _render_line(line.text, scoped, doc_ctx, offset)
                rendered.append(text)
                spans.extend(line_spans)
                offset += len(text) + 1  # 줄바꿈 한 글자
            continue

        if not _line_is_renderable(line, actors):
            continue
        text, line_spans = _render_line(line.text, actors, doc_ctx, offset)
        rendered.append(text)
        spans.extend(line_spans)
        offset += len(text) + 1

    body = "\n".join(rendered)
    return Document(
        doc_id=doc_id,
        genre=template.genre,
        template_id=template.id,
        text=body,
        spans=tuple(spans),
        person_ids=tuple(p.person_id for p in people),
    )


def generate_documents(
    population: Population,
    templates: list[DocumentTemplate],
    count: int,
    genre_weights: dict[str, float],
    seed: int,
) -> list[Document]:
    """코퍼스를 생성합니다.

    Args:
        population: 인물 풀
        templates: 사용할 템플릿 목록
        count: 생성할 문서 수
        genre_weights: 장르별 가중치
        seed: 난수 시드

    Returns:
        생성된 문서 목록

    Raises:
        ValueError: 가중치가 걸린 장르의 템플릿이 하나도 없는 경우
    """
    usable = [t for t in templates if genre_weights.get(t.genre, 0.0) > 0.0]
    if not usable:
        raise ValueError("가중치가 0보다 큰 장르에 해당하는 템플릿이 없습니다.")

    weights = [genre_weights[t.genre] for t in usable]
    rng = random.Random(seed)
    documents: list[Document] = []

    for index in range(count):
        template = rng.choices(usable, weights=weights, k=1)[0]
        low, high = template.persons
        actor_count = min(rng.randint(low, high), len(population.people))
        actors = rng.sample(population.people, actor_count)
        doc_ctx = {
            "date": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "serial": f"{rng.randint(0, 9999):04d}",
        }
        documents.append(render_document(f"doc_{index:06d}", template, actors, doc_ctx))

    return documents
