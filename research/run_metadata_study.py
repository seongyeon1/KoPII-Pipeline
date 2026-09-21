"""Extend archived E3 with a metadata baseline; reuse verified, fixed predictions.

First run exports synthetic-only embedding inputs. A second run may consume the
matching vectors from embed_study.py. No remote service is contacted here.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.research.data import file_hash
from kopii.research.experiment import atomic_json, build_manifest
from kopii.research.organization import (
    BM25,
    StudyResolver,
    attack_candidates,
    attack_score,
    average,
    make_queries,
    make_world,
    organization_answer,
    retrieval_score,
)
from kopii.research.retrieval import CATEGORIES, DenseIndex, filter_ranking, query_category
from kopii.schemas import Entity


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class FixedDetector:
    def __init__(self, entities: list[Entity]) -> None:
        self.entities = entities

    def detect(self, text: str) -> list[Entity]:
        for entity in self.entities:
            entity.validate_text(text)
        return self.entities


def prepare(archive: Path, protocol: dict) -> tuple[list[dict], dict]:
    old = json.loads((archive / "results.json").read_text())
    manifest = json.loads((archive / "manifest.json").read_text())
    if old.get("complete") is not True or old["manifest"] != manifest:
        raise ValueError("Require completed, consistent E3 source run")
    original = manifest["config"]["protocol"]
    for key in ("seeds", "team_sizes", "span_conditions"):
        if protocol[key] != original[key]:
            raise ValueError("Extension must reuse the archived worlds and conditions")
    sources = {name: file_hash(archive / name) for name in ("results.json", "manifest.json")}
    worlds = []
    for seed in protocol["seeds"]:
        people, docs, directory = make_world(seed, protocol["team_sizes"])
        generated = digest(
            {"documents": [(d.did, d.text, d.person.pid) for d in docs], "directory": directory}
        )
        name = f"predictions-{seed}.json"
        saved = json.loads((archive / name).read_text())
        sources[name] = file_hash(archive / name)
        if saved["run_id"] != manifest["run_id"] or saved["generated_sha256"] != generated:
            raise ValueError("Archived predictions do not match generated data/run")
        if set(saved["predictions"]) != {d.did for d in docs}:
            raise ValueError("Require exactly one prediction record per generated document")
        reference = next(w for w in old["worlds"] if w["seed"] == seed)
        conditions = {}
        for condition in protocol["span_conditions"]:
            texts = {"mask": [], **{level: [] for level in protocol["levels"]}}
            for doc in docs:
                entities = (
                    list(doc.spans)
                    if condition == "gold"
                    else [Entity(**e) for e in saved["predictions"][doc.did]]
                )
                for policy in texts:
                    organization = policy != "mask"
                    processor = Pipeline(
                        FixedDetector(entities),
                        Policy(
                            actions={"PERSON_NAME": "organization" if organization else "mask"},
                            key=hashlib.sha256(f"fictional-study-secret-{seed}".encode()).digest(),
                        ),
                        StudyResolver(directory, policy) if organization else None,
                    )
                    texts[policy].append(processor.process(doc.text, document_id=doc.did).text)
            conditions[condition] = texts
        worlds.append(
            dict(
                seed=seed,
                people=people,
                docs=docs,
                queries=make_queries(docs),
                conditions=conditions,
                reference=reference,
                generated_sha256=generated,
            )
        )
    return worlds, {"run_id": manifest["run_id"], "files": sources}


def embedding_inputs(worlds: list[dict]) -> dict:
    records = {}
    for world in worlds:
        for texts in world["conditions"].values():
            for corpus in texts.values():
                for text in corpus:
                    record = {"kind": "document", "text": text}
                    records[digest(record)] = record
        for query in world["queries"]:
            record = {"kind": "query", "text": query.text}
            records[digest(record)] = record
    return {
        "schema_version": 1,
        "synthetic_only": True,
        "input_sha256": digest(records),
        "records": records,
    }


def run(worlds: list[dict], protocol: dict, embeddings: dict | None) -> list[dict]:
    output = []
    for world in worlds:
        people, docs, queries, seed = (world[k] for k in ("people", "docs", "queries", "seed"))
        scores = {}
        for condition, texts in world["conditions"].items():
            condition_scores = {}
            ranks = {}
            for policy, corpus in texts.items():
                if embeddings is None:
                    index = BM25(corpus)
                    ranks[policy] = [index.rank(q.text) for q in queries]
                else:
                    vectors = embeddings["vectors"]
                    dense = DenseIndex(
                        [vectors[digest({"kind": "document", "text": t})] for t in corpus]
                    )
                    ranks[policy] = [
                        dense.rank(vectors[digest({"kind": "query", "text": q.text})])
                        for q in queries
                    ]
            for level in protocol["levels"]:
                metadata = [frozenset(organization_answer(text, level)) for text in texts[level]]
                parsed = [query_category(q.text, level) for q in queries]
                # Fully authorized synthetic user. Denied scope behavior is unit-tested;
                # this is not a simulated authentication service or a claim about ACLs.
                scope = frozenset(CATEGORIES[level])
                selected = [i for i, q in enumerate(queries) if q.kind == level]
                if any(parsed[i] is None for i in selected):
                    raise ValueError(
                        "Controlled query parser failed; do not infer filters from gold"
                    )
                level_scores = {}
                for policy in protocol["policies"]:
                    released = texts[level] if policy == "inline" else texts["mask"]
                    ranking = ranks[level] if policy == "inline" else ranks["mask"]
                    per_query = []
                    for i in selected:
                        result = ranking[i]
                        if policy == "metadata_filter":
                            result = filter_ranking(result, metadata, parsed[i], scope)
                        per_query.append(
                            {
                                **retrieval_score(result, queries[i].relevant),
                                "empty_result": float(not result),
                            }
                        )
                    utility = average(per_query)
                    if embeddings is None and policy != "metadata_filter":
                        original_policy = level if policy == "inline" else "mask"
                        old_score = world["reference"]["conditions"][condition][original_policy][
                            "retrieval"
                        ][level]
                        if any(abs(utility[k] - v) > 1e-12 for k, v in old_score.items()):
                            raise ValueError("Archived baseline scores changed")
                    text_attacks, resolved_text_attacks, member_attacks = [], [], []
                    wrong, available = 0, 0
                    for doc, text, values in zip(docs, released, metadata, strict=True):
                        text_attacks.append(
                            attack_score(
                                attack_candidates(text, people, "directory_role_project"),
                                doc.person.pid,
                                seed,
                            )
                        )
                        if len(values) == 1:
                            available += 1
                            resolved_text_attacks.append(text_attacks[-1])
                            category = next(iter(values))
                            wrong += category != getattr(doc.person, level)
                            observed = text + f" [PERSON_NAME:{category}]"
                            member_attacks.append(
                                attack_score(
                                    attack_candidates(observed, people, "directory_role_project"),
                                    doc.person.pid,
                                    seed,
                                )
                            )
                    # Filter-membership visibility applies only to the metadata service.
                    # Other policies do not expose such a filter in this experiment.
                    level_scores[policy] = {
                        "retrieval": utility,
                        "query_count": len(selected),
                        "released_text_only": {"documents": len(docs), **average(text_attacks)},
                        "released_text_only_resolved_subset": {
                            "documents": available,
                            **average(resolved_text_attacks),
                        },
                    }
                    if policy == "metadata_filter":
                        level_scores[policy].update(
                            {
                                "known_filter_membership": {
                                    "documents": available,
                                    **average(member_attacks),
                                },
                                "metadata": {
                                    "coverage": available / len(docs),
                                    "wrong_category_fraction_all_documents": wrong / len(docs),
                                    "wrong_category_fraction_resolved": wrong / available
                                    if available
                                    else None,
                                },
                            }
                        )
                condition_scores[level] = level_scores
            scores[condition] = condition_scores
        output.append(
            {
                "seed": seed,
                "documents": len(docs),
                "generated_sha256": world["generated_sha256"],
                "conditions": scores,
            }
        )
        print(f"Completed metadata comparison for world {seed}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("output/organization-study"))
    parser.add_argument("--output", type=Path, default=Path("output/metadata-study"))
    parser.add_argument("--embeddings", type=Path)
    args = parser.parse_args()
    path = Path("research/studies/metadata-retrieval.json")
    protocol = json.loads(path.read_text())
    worlds, archive = prepare(args.archive, protocol)
    inputs = embedding_inputs(worlds)
    embeddings = json.loads(args.embeddings.read_text()) if args.embeddings else None
    if embeddings is not None:
        if (
            embeddings.get("complete") is not True
            or embeddings.get("input_sha256") != inputs["input_sha256"]
        ):
            raise ValueError("Embedding input identity mismatch or incomplete execution")
        if set(embeddings["vectors"]) != set(inputs["records"]):
            raise ValueError("Embedding coverage mismatch")
    manifest = build_manifest(
        {
            "protocol": protocol,
            "archive": archive,
            "embedding_sha256": file_hash(args.embeddings) if args.embeddings else None,
        },
        path,
    )
    manifest["runner_sha256"] = file_hash(Path(__file__))
    manifest["input_sha256"] = inputs["input_sha256"]
    manifest["run_id"] = digest(manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / ".run.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        manifest_path = args.output / "manifest.json"
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Run identity changed; use a fresh output directory")
        atomic_json(manifest_path, manifest)
        atomic_json(args.output / "embedding-input.json", inputs)
        results = run(worlds, protocol, embeddings)
        atomic_json(
            args.output / "results.json",
            {
                "complete": True,
                "manifest": manifest,
                "retriever": "cosine" if embeddings else "BM25",
                "embedding_provenance": embeddings["provenance"] if embeddings else None,
                "worlds": results,
            },
        )
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
