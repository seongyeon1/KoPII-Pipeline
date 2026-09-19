"""Download pinned public evaluation data and model snapshots; verify data hashes."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

from huggingface_hub import hf_hub_download, snapshot_download
from compare import MODELS, ROOT

DATASET = 'seongyeon1/ko-pii-ner-100k'
DATASET_REVISION = '660e03a454f7934261be41390744796565550ce2'
DATA_HASHES = {
    'test_kdpii.jsonl': '2bde2d83474a2d43aef33eef0b606b0acf3ac9270e6e67bc56e13b19c17ca379',
    'test.jsonl': '2ca9f92cee0c2ce1cd15fee9993584d927c6e533ba66f941d8b1d72ff800c87c',
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT.parents[1] / 'data' / 'ko_pii')
    parser.add_argument('--models', nargs='+', choices=tuple(MODELS), default=list(MODELS))
    parser.add_argument('--skip-models', action='store_true', help='Download evaluation data only')
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    for filename, expected in DATA_HASHES.items():
        path = Path(hf_hub_download(
            DATASET, filename, repo_type='dataset', revision=DATASET_REVISION,
            local_dir=args.data,
        ))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Evaluation data differs from the recorded benchmark: {filename}')
        print(f'Verified {filename}: {actual}', flush=True)
    if not args.skip_models:
        for name in args.models:
            repo, revision = MODELS[name]
            snapshot_download(repo, revision=revision)
            print(f'Cached {repo} at {revision}', flush=True)


if __name__ == '__main__':
    main()
