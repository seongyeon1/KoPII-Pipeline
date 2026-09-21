"""Run the frozen E2 development search and historical-test re-evaluation.

Run from the repository root. Raw offsets/checkpoints remain in ignored output/.
Only aggregate results and selected settings are intended for publication.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import json
import platform
import random
import time
from pathlib import Path
from typing import Any

from kopii.config import create_detector
from kopii.detectors.gliner import GlinerDetector
from kopii.research.data import file_hash, load_dataset
from kopii.research.experiment import atomic_json
from kopii.research.metrics import evaluate


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def filter_scores(predictions: dict, threshold: float) -> dict:
    return {key: [e for e in values if e['score'] >= threshold] for key, values in predictions.items()}


def prediction_keys(predictions: dict) -> dict:
    return {key: sorted((e['start'], e['end'], e['label']) for e in values)
            for key, values in predictions.items()}


def select(grid: list[dict]) -> dict:
    if not grid:
        raise ValueError('Empty search grid')
    return max(grid, key=lambda r: (r['metrics']['exact']['f1'], r['metrics']['exact']['recall']))


def infer(detector: Any, rows: list[dict], path: Path, identity: str) -> dict:
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['identity'] != identity:
            raise ValueError('Checkpoint identity changed: use a new output directory')
        predictions = saved['predictions']
    else:
        predictions = {}
    if not set(predictions) <= {r['id'] for r in rows}:
        raise ValueError('Unexpected checkpoint rows')
    remaining = [r for r in rows if r['id'] not in predictions]
    start = time.monotonic()
    for begin in range(0, len(remaining), 32):
        batch = remaining[begin:begin + 32]
        if isinstance(detector, GlinerDetector):
            outputs = detector.detect_many([r['text'] for r in batch])
        else:
            outputs = [detector.detect(r['text']) for r in batch]
        for row, entities in zip(batch, outputs, strict=True):
            predictions[row['id']] = [e.to_dict() for e in entities]
        atomic_json(path, {'identity': identity, 'predictions': predictions})
        print(f'{path.stem}: {len(predictions)}/{len(rows)} {time.monotonic()-start:.1f}s', flush=True)
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('data/ko_pii'))
    parser.add_argument('--output', type=Path, default=Path('output/korean-settings'))
    parser.add_argument('--models', nargs='+', choices=('nvidia', 'fastino', 'roberta'), default=['nvidia', 'fastino', 'roberta'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    protocol_path = Path('research/studies/korean-settings.json')
    protocol = json.loads(protocol_path.read_text())
    random.seed(protocol['seed'])
    import torch
    torch.manual_seed(protocol['seed'])
    valid = load_dataset(args.data / 'valid.jsonl')
    positives = load_dataset(args.data / 'test_kdpii.jsonl')
    negatives = [r for r in load_dataset(args.data / 'test.jsonl') if r['meta']['layer'] == 'L4']
    dev_negative = sorted((r for r in valid if r['meta']['layer'] == 'L4'),
                          key=lambda r: digest([protocol['seed'], r['id']]))[:200]
    dev = [r for r in valid if r['meta']['layer'] == 'L1'] + dev_negative
    for row in positives:
        row['group_id'] = row['meta']['conversation_id']
    test = positives + negatives
    dev_groups = {r['meta']['conversation_id'] for r in dev if 'conversation_id' in r['meta']}
    test_groups = {r['group_id'] for r in positives}
    overlap = {'conversation_groups': len(dev_groups & test_groups),
               'ids': len({r['id'] for r in dev} & {r['id'] for r in test}),
               'exact_texts': len({r['text'] for r in dev} & {r['text'] for r in test})}
    if any(overlap.values()):
        raise ValueError(f'Development/test overlap: {overlap}')
    tracked_sources = ['research/run_korean_study.py', 'src/kopii/detectors/gliner.py',
                       'src/kopii/detectors/huggingface.py', 'src/kopii/research/metrics.py',
                       'src/kopii/research/data.py', 'src/kopii/schemas.py']
    manifest = {'protocol': protocol, 'protocol_sha256': file_hash(protocol_path),
                'source_sha256': {p: file_hash(Path(p)) for p in tracked_sources},
                'data_sha256': {p: file_hash(args.data / p) for p in ('valid.jsonl', 'test.jsonl', 'test_kdpii.jsonl')},
                'selection_ids_sha256': digest([r['id'] for r in dev]),
                'development_records': len(dev), 'development_negative_records': len(dev_negative),
                'test_records': len(test), 'test_negative_records': len(negatives),
                'development_test_overlap': overlap, 'python': platform.python_version(),
                'platform': platform.platform(),
                'dependencies': {p: importlib.metadata.version(p) for p in ('torch', 'transformers', 'tokenizers', 'gliner', 'gliner2')}}
    for name in ('nvidia', 'fastino', 'roberta'):
        manifest[name] = json.loads(Path(f'configs/eval-{name}.json').read_text())
    manifest['execution_models'] = args.models
    identity = digest(manifest)
    manifest['run_id'] = identity
    destination = args.output / 'manifest.json'
    if destination.exists() and json.loads(destination.read_text()) != manifest:
        raise ValueError('Run identity changed; choose a new output directory')
    atomic_json(destination, manifest)
    report: dict[str, Any] = {'manifest': manifest, 'models': {}}
    for name in args.models:
        config = manifest[name]
        labels, mapping = set(config['labels']), config['label_map']
        detector_config = dict(config['detector'], device=protocol['device'], local_files_only=True)
        detector = create_detector(detector_config)
        model_result: dict[str, Any] = {'grid': [], 'evaluations': {}}
        conditions = []
        if isinstance(detector, GlinerDetector):
            if name == 'fastino' and getattr(detector.model, 'architecture', 'span') != 'span':
                raise ValueError('Threshold caching is only validated for the span architecture')
            for profile in protocol['profiles']:
                prompts = config['detector']['labels'] if profile == 'original' else dict(zip(protocol[profile], config['labels'], strict=True))
                detector.labels = prompts
                for boundary in protocol['boundaries']:
                    detector.set_boundary(boundary)
                    detector.threshold = min(protocol['thresholds'])
                    key = f'{name}-{profile}-{boundary}'
                    predictions = infer(detector, dev, args.output / f'{key}-dev.json', identity)
                    probe = dev[:12]
                    for threshold in (0.3, 0.7):
                        detector.threshold = threshold
                        native = {r['id']: [e.to_dict() for e in es] for r, es in zip(probe, detector.detect_many([r['text'] for r in probe]), strict=True)}
                        cached = filter_scores({r['id']: predictions[r['id']] for r in probe}, threshold)
                        if prediction_keys(native) != prediction_keys(cached):
                            raise ValueError(f'Native threshold equivalence failed: {key} {threshold}')
                    for threshold in protocol['thresholds']:
                        metrics = evaluate(dev, filter_scores(predictions, threshold), labels, mapping)
                        model_result['grid'].append({'profile': profile, 'boundary': boundary, 'threshold': threshold, 'metrics': metrics})
                    atomic_json(args.output / f'{name}-development-grid.json', model_result['grid'])
            baseline = {'profile': 'original', 'boundary': 'native', 'threshold': config['detector']['threshold']}
            groups = {
                'threshold_only': [r for r in model_result['grid'] if r['profile'] == 'original' and r['boundary'] == 'native'],
                'labels_threshold': [r for r in model_result['grid'] if r['boundary'] == 'native'],
                'boundary_threshold': [r for r in model_result['grid'] if r['profile'] == 'original'],
                'joint': model_result['grid'],
            }
            selected = {key: {k: v for k, v in select(grid).items() if k != 'metrics'} for key, grid in groups.items()}
            model_result['selection'] = selected
            model_result['native_threshold_checks'] = 12 * 2 * len(protocol['profiles']) * len(protocol['boundaries'])
            atomic_json(args.output / f'{name}-selection.json', selected)  # frozen before test inference
            conditions = [('baseline', baseline), *selected.items()]
        else:
            conditions = [('reference', {})]
        for condition, setting in conditions:
            if isinstance(detector, GlinerDetector):
                profile = setting['profile']
                detector.labels = config['detector']['labels'] if profile == 'original' else dict(zip(protocol[profile], config['labels'], strict=True))
                detector.set_boundary(setting['boundary'])
                detector.threshold = 0.1
                key = f"{name}-{profile}-{setting['boundary']}-test"
            else:
                key = f'{name}-test'
            predictions = infer(detector, test, args.output / f'{key}.json', identity)
            if setting:
                predictions = filter_scores(predictions, setting['threshold'])
            score = evaluate(positives, {r['id']: predictions[r['id']] for r in positives}, labels, mapping,
                             bootstrap_samples=protocol['bootstrap_samples'], seed=protocol['seed'])
            negative_score = evaluate(negatives, {r['id']: predictions[r['id']] for r in negatives}, labels, mapping)
            model_result['evaluations'][condition] = {'setting': setting, 'kdpii': score, 'negative': negative_score,
                                                    'combined': evaluate(test, predictions, labels, mapping)}
            print(f"SCORE {name} {condition}: F1={score['exact']['f1']:.4f} negFPR={negative_score['negative_document_fpr']:.4f}", flush=True)
        report['models'][name] = model_result
        atomic_json(args.output / 'results.json', report)
        del detector
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    report['complete'] = True
    atomic_json(args.output / 'results.json', report)


if __name__ == '__main__':
    main()
