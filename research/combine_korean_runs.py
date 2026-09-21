"""Combine completed model components after a Fastino-only offset correction.

No checkpoint identity is rewritten. Preserve both manifests and original source
snapshots; verify that the NVIDIA path is structurally unchanged before reuse.
Normal fresh replication runs all three models and needs no combination step.
"""

import ast
import hashlib
import json
from pathlib import Path

from kopii.research.data import file_hash
from kopii.research.experiment import atomic_json


def nvidia_ast(path):
    tree = ast.parse(path.read_text())
    target = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'GlinerDetector')
    # Only the version-2 branch was repaired. Keep and compare every other class node.
    for node in ast.walk(target):
        if isinstance(node, ast.If) and ast.unparse(node.test) == 'self.version == 1':
            node.orelse = []
    supporting = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                  and node.name in {'character_windows', 'KoreanSyllableSplitter'}]
    return ast.dump(ast.Module(body=[target, *supporting], type_ignores=[]), include_attributes=False)


def main():
    old = json.loads(Path('output/korean-settings-before-fix/results.json').read_text())
    current = json.loads(Path('output/korean-settings/results.json').read_text())
    if not current.get('complete') or set(current['models']) != {'fastino', 'roberta'}:
        raise ValueError('Require completed Fastino and RoBERTa component run')
    nvidia = old['models']['nvidia']
    if set(nvidia['evaluations']) != {'baseline', 'threshold_only', 'labels_threshold', 'boundary_threshold', 'joint'}:
        raise ValueError('NVIDIA component is incomplete')
    for evaluation in nvidia['evaluations'].values():
        if evaluation['kdpii']['records'] != 2006 or evaluation['negative']['records'] != 580:
            raise ValueError('NVIDIA component has incomplete data coverage')
    for key in ('protocol', 'protocol_sha256', 'data_sha256', 'selection_ids_sha256', 'nvidia', 'fastino', 'roberta'):
        if old['manifest'][key] != current['manifest'][key]:
            raise ValueError(f'Component protocols disagree: {key}')
    snapshot = Path('research/studies/snapshots/gliner-before-suffix-fix.py.txt')
    runner_snapshot = Path('research/studies/snapshots/runner-before-suffix-fix.py.txt')
    original_sources = old['manifest']['source_sha256']
    if file_hash(snapshot) != original_sources['src/kopii/detectors/gliner.py']:
        raise ValueError('Original adapter snapshot hash mismatch')
    if file_hash(runner_snapshot) != original_sources['research/run_korean_study.py']:
        raise ValueError('Original runner snapshot hash mismatch')
    if nvidia_ast(snapshot) != nvidia_ast(Path('src/kopii/detectors/gliner.py')):
        raise ValueError('NVIDIA implementation changed; cannot reuse the original measurement')
    for source, expected in original_sources.items():
        if source not in {'src/kopii/detectors/gliner.py', 'research/run_korean_study.py'} and file_hash(Path(source)) != expected:
            raise ValueError(f'Shared scoring/data code changed: {source}')
    manifest = {key: value for key, value in current['manifest'].items()
                if key not in {'run_id', 'source_sha256', 'execution_models'}}
    manifest['component_runs'] = {'nvidia': old['manifest'], 'fastino_roberta': current['manifest']}
    manifest['correction'] = {
        'reason': 'GLiNER2 appends terminal punctuation; explicitly augment and invert only that known suffix',
        'nvidia_path_ast_unchanged': True,
        'original_source_snapshots': [str(snapshot), str(runner_snapshot)],
        'failed_fastino_development_records_completed': 96,
        'failed_fastino_predictions_reused': False,
        'combiner_sha256': file_hash(Path(__file__)),
    }
    manifest['run_id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {'manifest': manifest, 'models': {'nvidia': nvidia, **current['models']}, 'complete': True}
    destination = Path('output/korean-settings-combined')
    destination.mkdir(exist_ok=True)
    atomic_json(destination / 'results.json', result)
    print('Combined completed components with original identities and verified NVIDIA path equivalence.')


if __name__ == '__main__':
    main()
