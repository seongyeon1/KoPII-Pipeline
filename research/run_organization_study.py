"""Execute frozen synthetic utility/risk study; publish aggregates, never identities."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from kopii.config import create_detector
from kopii.pipeline import Pipeline
from kopii.policies import Policy
from kopii.research.data import file_hash
from kopii.research.experiment import atomic_json, build_manifest
from kopii.research.metrics import evaluate
from kopii.research.organization import (
    BM25, StudyResolver, attack_candidates, attack_score, average, describe_world,
    make_queries, make_world, organization_answer, retrieval_score,
)
from kopii.schemas import Entity


class FixedDetector:
    """Replay fixed gold or actual model predictions identically across policies."""

    def __init__(self, entities: list[Entity]) -> None:
        self.entities = entities

    def detect(self, text: str) -> list[Entity]:
        for entity in self.entities:
            entity.validate_text(text)
        return self.entities


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('output/organization-study'))
    parser.add_argument('--device', default='mps')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    protocol_path = Path('research/studies/organization-utility-risk.json')
    protocol = json.loads(protocol_path.read_text())
    config = json.loads(Path('configs/eval-roberta.json').read_text())['detector']
    config.update(device=args.device, local_files_only=True)
    manifest = build_manifest({'protocol': protocol, 'detector': config}, protocol_path)
    manifest['runner_sha256'] = file_hash(Path(__file__))
    manifest['run_id'] = digest(manifest)
    path = args.output / 'manifest.json'
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError('Study identity changed; choose a new output directory')
    atomic_json(path, manifest)
    report = {'manifest': manifest, 'worlds': []}
    detector = create_detector(config)
    for seed in protocol['seeds']:
        people, docs, directory = make_world(seed, protocol['team_sizes'])
        generated_hash = digest({'documents': [(d.did, d.text, d.person.pid) for d in docs], 'directory': directory})
        rows = [{'id': d.did, 'text': d.text, 'spans': [e.to_dict() for e in d.spans], 'group_id': d.person.pid} for d in docs]
        prediction_path = args.output / f'predictions-{seed}.json'
        if prediction_path.exists():
            saved = json.loads(prediction_path.read_text())
            if saved['run_id'] != manifest['run_id'] or saved['generated_sha256'] != generated_hash:
                raise ValueError('Prediction identity changed')
            predictions = saved['predictions']
        else:
            predictions = {}
        for i, doc in enumerate(docs):
            if doc.did not in predictions:
                predictions[doc.did] = [e.to_dict() for e in detector.detect(doc.text)]
            if (i + 1) % 32 == 0 or i == len(docs) - 1:
                atomic_json(prediction_path, {'run_id': manifest['run_id'], 'generated_sha256': generated_hash, 'predictions': predictions})
                print(f'NER world {seed}: {i+1}/{len(docs)}', flush=True)
        queries = make_queries(docs)
        world = {'seed': seed, **describe_world(people, docs), 'generated_sha256': generated_hash,
                 'query_counts': {kind: sum(q.kind == kind for q in queries) for kind in ('team', 'division', 'center', 'topic_control')},
                 'detection': evaluate(rows, predictions, {'PERSON_NAME'}, bootstrap_samples=1000, seed=seed),
                 'conditions': {}}
        for span_condition in protocol['span_conditions']:
            conditions = {}
            for policy in protocol['policies']:
                released = []
                action_counts = {}
                for doc in docs:
                    entities = list(doc.spans) if span_condition == 'gold' else [Entity(**e) for e in predictions[doc.did]]
                    if policy == 'raw':
                        released.append(doc.text)
                        continue
                    organization = policy in {'team', 'division', 'center'}
                    processor = Pipeline(FixedDetector(entities),
                        Policy(actions={'PERSON_NAME': 'organization' if organization else policy},
                               key=hashlib.sha256(f'fictional-study-secret-{seed}'.encode()).digest()),
                        StudyResolver(directory, policy) if organization else None)
                    result = processor.process(doc.text, document_id=doc.did)
                    released.append(result.text)
                    for replacement in result.replacements:
                        action_counts[replacement.action] = action_counts.get(replacement.action, 0) + 1
                index = BM25(released)
                utility = {}
                for kind in ('team', 'division', 'center', 'topic_control'):
                    utility[kind] = average([retrieval_score(index.rank(q.text), q.relevant) for q in queries if q.kind == kind])
                qa, direct, privacy = {}, [], {}
                qa_ranks = {doc.did: index.rank(f'업무참조 {doc.ticket} 기록의 담당 조직은 어디인가?') for doc in docs}
                for level in ('team', 'division', 'center'):
                    answers = []
                    for doc in docs:
                        ranking = qa_ranks[doc.did]
                        observed = organization_answer(released[ranking[0]], level)
                        expected = getattr(doc.person, level)
                        answers.append({'accuracy': float(observed == {expected}), 'answered': float(bool(observed)), 'source_top1': float(docs[ranking[0]].did == doc.did)})
                    qa[level] = average(answers)
                for doc, text in zip(docs, released, strict=True):
                    direct.append({'name_surface_remaining': float(doc.person.name in text),
                                   'correct_team_marker': float(organization_answer(text, 'team') == {doc.person.team}),
                                   'wrong_team_marker': float(bool(organization_answer(text, 'team')) and organization_answer(text, 'team') != {doc.person.team})})
                for knowledge in protocol['attackers']:
                    attacks = [attack_score(attack_candidates(text, people, knowledge), doc.person.pid, seed)
                               for doc, text in zip(docs, released, strict=True)]
                    by_stress = {stress: average([a for doc, a in zip(docs, attacks, strict=True) if doc.person.stress == stress])
                                 for stress in sorted({p.stress for p in people})}
                    by_size = {str(size): average([a for doc, a in zip(docs, attacks, strict=True) if doc.person.team_size == size])
                               for size in sorted({p.team_size for p in people})}
                    privacy[knowledge] = {'overall': average(attacks), 'by_stress': by_stress, 'by_team_size': by_size}
                conditions[policy] = {'retrieval': utility, 'extractive_qa': qa, 'privacy': privacy,
                                      'release': average(direct), 'replacement_counts': action_counts}
                print(f'{seed} {span_condition} {policy}: team MRR={utility["team"]["mrr"]:.3f} risk={privacy["directory_role_project"]["overall"]["expected_top1"]:.3f}', flush=True)
            world['conditions'][span_condition] = conditions
        report['worlds'].append(world)
        atomic_json(args.output / 'results.json', report)
    report['complete'] = True
    atomic_json(args.output / 'results.json', report)


if __name__ == '__main__':
    main()
