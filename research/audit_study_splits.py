"""Audit explicit source conversations and exact text overlap for the E2 subsets."""

import hashlib
import json
from pathlib import Path

from kopii.research.data import file_hash, load_dataset
from kopii.research.experiment import atomic_json


def compare(first, second):
    texts = {r['text'] for r in first}
    groups = {r['meta']['conversation_id'] for r in first if 'conversation_id' in r['meta']}
    return {
        'exact_text_overlap_unique': len(texts & {r['text'] for r in second}),
        'overlapping_rows_in_second': sum(r['text'] in texts for r in second),
        'conversation_groups_overlap': len(groups & {r['meta']['conversation_id'] for r in second if 'conversation_id' in r['meta']}),
    }


def main():
    root = Path('data/ko_pii')
    train, valid, test = [load_dataset(root / p) for p in ('train.jsonl', 'valid.jsonl', 'test_kdpii.jsonl')]
    protocol = json.loads(Path('research/studies/korean-settings.json').read_text())
    def order(row):
        value = json.dumps([protocol['seed'], row['id']], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()
    dev = [r for r in valid if r['meta']['layer'] == 'L1'] + sorted(
        [r for r in valid if r['meta']['layer'] == 'L4'], key=order)[:protocol['development']['negative_limit']]
    result = {
        'dataset_revision': protocol['dataset_revision'],
        'file_sha256': {p: file_hash(root / p) for p in ('train.jsonl', 'valid.jsonl', 'test_kdpii.jsonl', 'test.jsonl')},
        'train_records': len(train), 'selected_development_records': len(dev),
        'train_vs_selected_development': compare(train, dev),
        'train_vs_historical_test': compare(train, test),
        'selected_development_vs_historical_test': compare(dev, test),
        'scope': 'Exact text and explicit conversation metadata only; no semantic near-duplicate or template-family independence certification.',
    }
    atomic_json(Path('research/results/split-audit.json'), result)


if __name__ == '__main__':
    main()
