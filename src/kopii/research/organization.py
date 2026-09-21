"""Controlled fictional-directory study: generation, retrieval and closed-world attack.

The attacker takes released text and declared background knowledge, never the
true document author. Ground truth is used only by separate scoring functions.
"""

import hashlib
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from kopii.resolvers import Resolution
from kopii.schemas import Entity

TEAMS = [
    "업무기획팀",
    "서비스설계팀",
    "고객지원팀",
    "데이터분석팀",
    "품질관리팀",
    "플랫폼개발팀",
    "보안운영팀",
    "정보전략팀",
    "인재교육팀",
    "재무관리팀",
    "계약검토팀",
    "기술지원팀",
    "제품연구팀",
    "사업운영팀",
    "성과분석팀",
    "시스템관리팀",
]
DIVISIONS = ["서비스본부", "기술본부", "경영본부", "사업본부"]
CENTERS = ["운영센터", "전략센터"]
ROLES = ["대리", "과장", "차장", "연구원"]
PROJECTS = ["가람", "누리", "다온", "라온", "마루", "보람", "소담", "아람"]
TOPICS = [
    ("승인 절차", "결재 승인"),
    ("장애 복구", "오류 장애 처리"),
    ("비용 정산", "지출 비용 확인"),
    ("배포 일정", "출시 배포 계획"),
]
PERIODS = ["상반기", "하반기"]


@dataclass(frozen=True)
class Person:
    """Fictional identity; identifiers never appear in released documents."""

    pid: str
    name: str
    team: str
    division: str
    center: str
    role: str
    project: str
    team_size: int
    stress: str = "current"


@dataclass(frozen=True)
class Document:
    """Private-to-evaluation linkage kept separate from published text."""

    did: str
    text: str
    person: Person
    topic: int
    period: str
    ticket: str
    spans: tuple[Entity, ...]


@dataclass(frozen=True)
class Query:
    """Query text and relevance labels; labels are never given to the retriever."""

    text: str
    relevant: frozenset[int]
    kind: str


class StudyResolver:
    """Reference CSV resolution semantics for generated service-directory rows."""

    def __init__(self, rows: list[dict[str, str]], level: str) -> None:
        self.rows, self.level = rows, level

    def resolve(self, names: list[str]) -> dict[str, Resolution]:
        result = {}
        for name in names:
            rows = [row for row in self.rows if row["name"] == name]
            if not rows:
                result[name] = Resolution("missing")
            elif len({r["team"] for r in rows}) != 1 or len({r[self.level] for r in rows}) != 1:
                result[name] = Resolution("ambiguous")
            else:
                result[name] = Resolution("resolved", rows[0][self.level])
        return result


def make_world(
    seed: int, team_sizes: list[int]
) -> tuple[list[Person], list[Document], list[dict[str, str]]]:
    """Generate a seeded world without consulting any model or evaluation result."""
    if len(team_sizes) != len(TEAMS) or min(team_sizes) < 2:
        raise ValueError("Require sixteen fictional teams, each with at least two members")
    rng = random.Random(seed)
    names = [
        a + b + c
        for a in "김이박최정강윤장임한"
        for b in "서민지하도수예준"
        for c in "준윤현진원우연빈"
    ]
    rng.shuffle(names)
    if sum(team_sizes) > len(names):
        raise ValueError("Not enough distinct synthetic names")
    people: list[Person] = []
    for team_index, size in enumerate(team_sizes):
        for _ in range(size):
            i = len(people)
            stress = "current"
            name = names[i]
            if i in {0, 2}:
                name, stress = names[0], "cross_team_homonym"
            elif i in {6, 7}:
                name, stress = names[6], "same_team_homonym"
            elif i % 17 == 0:
                stress = "missing"
            elif i % 19 == 0:
                stress = "stale"
            elif i % 23 == 0:
                stress = "multiple_teams"
            people.append(
                Person(
                    f"{seed}-{i}",
                    name,
                    TEAMS[team_index],
                    DIVISIONS[team_index // 4],
                    CENTERS[team_index // 8],
                    rng.choice(ROLES),
                    rng.choice(PROJECTS),
                    size,
                    stress,
                )
            )
    directory = []
    documents = []
    for i, person in enumerate(people):
        row = {key: getattr(person, key) for key in ("name", "team", "division", "center")}
        if person.stress != "missing":
            if person.stress == "stale":
                other = (TEAMS.index(person.team) + 5) % len(TEAMS)
                row.update(
                    team=TEAMS[other], division=DIVISIONS[other // 4], center=CENTERS[other // 8]
                )
            directory.append(row)
            if person.stress == "multiple_teams":
                other = (TEAMS.index(person.team) + 1) % len(TEAMS)
                directory.append(
                    dict(
                        row,
                        team=TEAMS[other],
                        division=DIVISIONS[other // 4],
                        center=CENTERS[other // 8],
                    )
                )
        for period_index, period in enumerate(PERIODS):
            topic = rng.randrange(len(TOPICS))
            ticket = f"REF{seed % 1000:03d}{i:03d}{period_index}"
            templates = [
                "{period} {topic} 검토 기록. 담당자 {name} {role}는 "
                "{project} 과제의 진행 상황을 정리했다. "
                "업무참조 {ticket}. 후속 검토에서 처리 여부를 확인한다.",
                "업무참조 {ticket}. {project} 과제에 관해 {name} {role}가 "
                "{period} {topic} 결과를 공유했다. "
                "세부 근거와 미처리 항목은 다음 회의에서 검토한다.",
                "{name} {role}에게 {project} 과제의 {period} {topic} 보완을 요청했다. "
                "업무참조 {ticket} 기록에 따라 검토 의견을 반영하고 완료 여부를 회신한다.",
            ]
            text = rng.choice(templates).format(
                period=period,
                topic=TOPICS[topic][0],
                name=person.name,
                role=person.role,
                project=person.project,
                ticket=ticket,
            )
            start = text.index(person.name)
            documents.append(
                Document(
                    f"doc-{ticket}",
                    text,
                    person,
                    topic,
                    period,
                    ticket,
                    (Entity(start, start + len(person.name), "PERSON_NAME"),),
                )
            )
    return people, documents, directory


def make_queries(documents: list[Document]) -> list[Query]:
    """Organization/topic requests are separately worded from source templates."""
    queries = []
    for level in ("team", "division", "center", "topic_control"):
        groups: dict[tuple[str, int, str], set[int]] = {}
        for index, doc in enumerate(documents):
            value = "" if level == "topic_control" else getattr(doc.person, level)
            groups.setdefault((value, doc.topic, doc.period), set()).add(index)
        for (value, topic, period), relevant in sorted(groups.items()):
            text = f"{period} {value}의 {TOPICS[topic][1]} 관련 처리 기록을 찾아줘."
            queries.append(Query(text, frozenset(relevant), level))
    return queries


def features(text: str) -> Counter[str]:
    """Fixed character bigrams; preserve order but discard punctuation/whitespace."""
    clean = "".join(re.findall(r"[가-힣A-Za-z0-9]+", text)).lower()
    return Counter(clean[i : i + 2] for i in range(len(clean) - 1))


class BM25:
    """Dependency-free fixed lexical retriever, not the production NPU embedding."""

    def __init__(self, documents: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.vectors = [features(text) for text in documents]
        self.lengths = [sum(v.values()) for v in self.vectors]
        self.average = sum(self.lengths) / len(documents) if documents else 1.0
        self.k1, self.b = k1, b
        frequency: Counter[str] = Counter()
        for vector in self.vectors:
            frequency.update(vector.keys())
        self.idf = {
            term: math.log(1 + (len(documents) - count + 0.5) / (count + 0.5))
            for term, count in frequency.items()
        }

    def rank(self, query: str) -> list[int]:
        """Rank only text, with stable index tie breaking shared by all policies."""
        terms = features(query)
        scores = []
        for index, (vector, length) in enumerate(zip(self.vectors, self.lengths, strict=True)):
            normalizer = self.k1 * (1 - self.b + self.b * length / (self.average or 1))
            score = sum(
                self.idf.get(term, 0) * vector[term] * (self.k1 + 1) / (vector[term] + normalizer)
                for term in terms
                if vector[term]
            )
            scores.append((score, index))
        return [index for _, index in sorted(scores, key=lambda v: (-v[0], v[1]))]


def retrieval_score(ranking: list[int], relevant: frozenset[int], k: int = 5) -> dict[str, float]:
    """Distinguish fraction of relevant documents recovered from any-hit success."""
    if not relevant:
        raise ValueError("A retrieval query must have at least one relevant document")
    hits = len(set(ranking[:k]) & relevant)
    first = next((i + 1 for i, index in enumerate(ranking) if index in relevant), None)
    return {
        "recall_at_5": hits / len(relevant),
        "hit_at_5": float(hits > 0),
        "mrr": 1 / first if first else 0.0,
    }


def organization_answer(text: str, level: str) -> set[str]:
    """Read released category markers using the public organization tree only."""
    answers = set()
    for value in re.findall(r"\[PERSON_NAME:([^\]]+)\]", text):
        if value in TEAMS:
            index = TEAMS.index(value)
            answers.add(
                {"team": value, "division": DIVISIONS[index // 4], "center": CENTERS[index // 8]}[
                    level
                ]
            )
        elif value in DIVISIONS and level in {"division", "center"}:
            answers.add(value if level == "division" else CENTERS[DIVISIONS.index(value) // 2])
        elif value in CENTERS and level == "center":
            answers.add(value)
    return answers


def attack_candidates(released_text: str, people: list[Person], knowledge: str) -> list[str]:
    """Filter public candidate identities without accessing a target's metadata."""
    if knowledge not in {"identity_list_only", "directory", "directory_role_project"}:
        raise ValueError("Unknown attacker knowledge")
    candidates = list(people)
    names = {p.name for p in people if p.name in released_text}
    if names:
        candidates = [p for p in candidates if p.name in names]
    if knowledge != "identity_list_only":
        values = set(re.findall(r"\[PERSON_NAME:([^\]]+)\]", released_text))
        for level, categories in (("team", TEAMS), ("division", DIVISIONS), ("center", CENTERS)):
            observed = values & set(categories)
            if observed:
                candidates = [p for p in candidates if getattr(p, level) in observed]
    if knowledge == "directory_role_project":
        roles = {r for r in ROLES if r in released_text}
        projects = {p for p in PROJECTS if f"{p} 과제" in released_text}
        if roles:
            candidates = [p for p in candidates if p.role in roles]
        if projects:
            candidates = [p for p in candidates if p.project in projects]
    return [p.pid for p in candidates]


def attack_score(candidates: list[str], target: str, seed: int) -> dict[str, float]:
    """Score a uniform-tie attack and one seeded realized top-1 decision.

    A wrong candidate set is a failed attack, not 1/|C| success. The same fixed
    pseudorandom identity order is used for every document/policy in a world.
    """
    if len(candidates) != len(set(candidates)):
        raise ValueError("Candidate identities must be unique")
    top = (
        min(candidates, key=lambda p: hashlib.sha256(f"{seed}:{p}".encode()).hexdigest())
        if candidates
        else None
    )
    return {
        "expected_top1": 1 / len(candidates) if target in candidates else 0.0,
        "realized_top1": float(top == target),
        "candidate_count": float(len(candidates)),
        "target_in_candidates": float(target in candidates),
        "abstention": float(not candidates),
    }


def average(rows: list[dict[str, float]]) -> dict[str, float]:
    """Average equally weighted observations, returning no invented empty score."""
    return {key: sum(r[key] for r in rows) / len(rows) for key in rows[0]} if rows else {}


def describe_world(people: list[Person], documents: list[Document]) -> dict[str, Any]:
    """Aggregate public descriptors; no person names or document text."""
    return {
        "people": len(people),
        "documents": len(documents),
        "teams": len(TEAMS),
        "stress_people": dict(Counter(p.stress for p in people)),
        "team_size_people": dict(Counter(p.team_size for p in people)),
    }
