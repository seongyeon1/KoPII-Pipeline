"""Study validity: separate hidden truth from attacker and retrieval inputs."""

from dataclasses import replace

from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.research.organization import (
    BM25,
    StudyResolver,
    attack_candidates,
    attack_score,
    make_queries,
    make_world,
    organization_answer,
    retrieval_score,
)
from kopii.schemas import Entity


def test_wrong_and_empty_candidate_sets_are_failed_attacks() -> None:
    assert attack_score(["wrong"], "target", 42)["expected_top1"] == 0
    empty = attack_score([], "target", 42)
    assert empty["expected_top1"] == 0 and empty["abstention"] == 1
    tied = attack_score(["target", "other"], "target", 42)
    assert tied["expected_top1"] == 0.5
    assert attack_score(["other", "target"], "target", 42) == tied


def test_attacker_filters_only_disclosed_attributes() -> None:
    people, docs, directory = make_world(42, [2, 4, 8, 16] * 4)
    person = next(p for p in people if p.stress == "current")
    mask = "담당자 [PERSON_NAME]가 검토했다."
    assert len(attack_candidates(mask, people, "directory_role_project")) == len(people)
    team = f"담당자 [PERSON_NAME:{person.team}]가 검토했다."
    assert len(attack_candidates(team, people, "identity_list_only")) == len(people)
    selected = attack_candidates(team, people, "directory")
    assert set(selected) == {p.pid for p in people if p.team == person.team}
    aux = team + f" 직급 {person.role}, {person.project} 과제"
    assert set(attack_candidates(aux, people, "directory_role_project")) == {
        p.pid
        for p in people
        if p.team == person.team and p.role == person.role and p.project == person.project
    }
    homonym = next(p for p in people if p.stress == "cross_team_homonym")
    assert (
        StudyResolver(directory, "center").resolve([homonym.name])[homonym.name].status
        == "ambiguous"
    )
    assert all(doc.text[e.start : e.end] == doc.person.name for doc in docs for e in doc.spans)


def test_generated_queries_have_relevance_and_do_not_copy_documents() -> None:
    people, docs, directory = make_world(42, [2, 4, 8, 16] * 4)
    assert (people, docs, directory) == make_world(42, [2, 4, 8, 16] * 4)
    assert len({p.pid for p in people}) == 120
    queries = make_queries(docs)
    assert {q.kind for q in queries} == {"team", "division", "center", "topic_control"}
    assert all(q.relevant and q.text not in {d.text for d in docs} for q in queries)
    assert retrieval_score([2, 1, 0], frozenset({0, 1}), 1) == {
        "recall_at_5": 0,
        "hit_at_5": 0,
        "mrr": 0.5,
    }
    assert BM25(["장애 복구 기록", "정산 비용 승인"]).rank("장애 복구")[0] == 0


def test_mask_and_organization_release_flow_into_real_attacker() -> None:
    people, docs, directory = make_world(42, [2, 4, 8, 16] * 4)
    doc = next(d for d in docs if d.person.stress == "current")

    class GoldDetector:
        def detect(self, text: str) -> list[Entity]:
            return list(doc.spans)

    masked = Pipeline(GoldDetector()).process(doc.text).text
    team = (
        Pipeline(
            GoldDetector(),
            Policy(actions={"PERSON_NAME": "organization"}),
            StudyResolver(directory, "team"),
        )
        .process(doc.text)
        .text
    )
    assert doc.person.name not in masked and doc.person.name not in team
    assert organization_answer(team, "team") == {doc.person.team}
    assert organization_answer(masked, "team") == set()
    masked_score = attack_score(attack_candidates(masked, people, "directory"), doc.person.pid, 42)
    team_score = attack_score(attack_candidates(team, people, "directory"), doc.person.pid, 42)
    assert team_score["expected_top1"] > masked_score["expected_top1"]


def test_auxiliary_role_and_project_each_narrow_candidates() -> None:
    people, _, _ = make_world(42, [2, 4, 8, 16] * 4)
    target = people[10]
    other_role = "대리" if target.role != "대리" else "과장"
    other_project = "가람" if target.project != "가람" else "누리"
    candidates = [
        target,
        replace(target, pid="other-role", role=other_role),
        replace(target, pid="other-project", project=other_project),
    ]
    text = f"[PERSON_NAME:{target.team}] {target.role} {target.project} 과제"
    assert attack_candidates(text, candidates, "directory_role_project") == [target.pid]


def test_study_directory_matches_public_csv_resolver(tmp_path) -> None:
    import csv

    from kopii.resolvers.csv import CsvResolver

    people, _, rows = make_world(42, [2, 4, 8, 16] * 4)
    path = tmp_path / "fictional-directory.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "team", "division", "center"])
        writer.writeheader()
        writer.writerows(rows)
    names = [p.name for p in people]
    for level in ("team", "division", "center"):
        assert StudyResolver(rows, level).resolve(names) == CsvResolver(path, level).resolve(names)
