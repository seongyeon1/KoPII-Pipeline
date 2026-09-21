"""Portable CLI for document processing and research workflows."""

import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Optional

from kopii.config import create_context_pipeline, create_embedder, create_pipeline, load_config


def main(argv: Optional[list[str]] = None) -> int:
    """Execute an explicit command; failures never print raw input or exception text."""
    parser = argparse.ArgumentParser(prog="kopii")
    commands = parser.add_subparsers(dest="command", required=True)
    process = commands.add_parser("process", help="Process UTF-8 input file or stdin")
    process.add_argument("--config", type=Path, required=True)
    process.add_argument("--input", type=Path)
    process.add_argument("--document-id", default="")
    process.add_argument("--output", type=Path)
    prepare = commands.add_parser(
        "prepare", help="Mask JSONL documents into a private search index"
    )
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    search = commands.add_parser("search", help="Search released text with explicit document scope")
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--query", required=True)
    search.add_argument(
        "--scope", type=Path, required=True, help="JSON array of authorized document IDs"
    )
    search.add_argument("--filters", type=Path, help="JSON object mapping fields to allowed values")
    search.add_argument("--embedding-config", type=Path)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument(
        "--include-metadata", action="store_true", help="Explicitly expose result attributes"
    )
    retrieval_eval = commands.add_parser(
        "evaluate-search", help="Evaluate explicit retrieval judgments"
    )
    retrieval_eval.add_argument("--index", type=Path, required=True)
    retrieval_eval.add_argument("--queries", type=Path, required=True)
    retrieval_eval.add_argument("--embedding-config", type=Path)
    retrieval_eval.add_argument("--limit", type=int, default=5)
    evaluate = commands.add_parser("evaluate", help="Run a versioned detection experiment")
    evaluate.add_argument("--config", type=Path, required=True)
    evaluate.add_argument("--data", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    synthetic = commands.add_parser(
        "synthesize", help="Generate fixture data, not the historical corpus"
    )
    synthetic.add_argument("--output", type=Path, required=True)
    synthetic.add_argument("--seed", type=int, default=42)
    synthetic.add_argument("--per-template", type=int, default=12)
    audit = commands.add_parser("audit-splits", help="Check train/dev/test exact and group overlap")
    audit.add_argument("--train", type=Path, required=True)
    audit.add_argument("--dev", type=Path, required=True)
    audit.add_argument("--test", type=Path)
    training = commands.add_parser("train", help="Train a new cross-entropy baseline")
    training.add_argument("--config", type=Path, required=True)
    training.add_argument("--train", type=Path, required=True)
    training.add_argument("--dev", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result: dict[str, Any]
        if args.command == "process":
            text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
            with redirect_stdout(sys.stderr):
                pipeline = create_pipeline(load_config(args.config), args.config.resolve().parent)
                result = pipeline.process(text, args.document_id).to_dict()
        elif args.command == "prepare":
            from kopii.documents import prepare_index

            with redirect_stdout(sys.stderr):
                processor = create_context_pipeline(
                    load_config(args.config), args.config.resolve().parent
                )
                result = prepare_index(processor, args.input, args.output)
        elif args.command in {"search", "evaluate-search"}:
            from kopii.documents import read_records
            from kopii.embeddings import VectorRanker
            from kopii.retrieval import SearchIndex

            with redirect_stdout(sys.stderr):
                ranker = (
                    VectorRanker(create_embedder(load_config(args.embedding_config)))
                    if args.embedding_config
                    else None
                )
                index = SearchIndex(read_records(args.index, allow_metadata=True), ranker)
                if args.command == "evaluate-search":
                    from kopii.research.data import file_hash
                    from kopii.research.search import evaluate_search

                    result = evaluate_search(index, args.queries, args.limit)
                    result["index_sha256"] = file_hash(args.index)
                    result["ranker"] = "http_cosine" if args.embedding_config else "bm25"
                    result["embedding_config_sha256"] = (
                        file_hash(args.embedding_config) if args.embedding_config else None
                    )
                else:
                    scope = json.loads(args.scope.read_text(encoding="utf-8"))
                    if not isinstance(scope, list):
                        raise ValueError("Document scope must be a JSON array")
                    filters = load_config(args.filters) if args.filters else None
                    hits = index.search(
                        args.query, allowed_ids=scope, filters=filters, k=args.limit
                    )
                    result = {
                        "hits": [
                            hit.to_dict(include_metadata=args.include_metadata) for hit in hits
                        ]
                    }
        elif args.command == "evaluate":
            from kopii.research.experiment import run_experiment

            with redirect_stdout(sys.stderr):
                result = run_experiment(load_config(args.config), args.data, args.output)
        elif args.command == "synthesize":
            from kopii.research.synthetic import generate

            result = generate(args.output, args.seed, args.per_template)
        elif args.command == "audit-splits":
            from kopii.research.data import audit_splits

            paths = {"train": args.train, "dev": args.dev}
            if args.test:
                paths["test"] = args.test
            result = audit_splits(paths)
            if any(
                any(r[key] for key in ("ids", "groups", "exact_texts")) for r in result["overlaps"]
            ):
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
        else:
            from kopii.research.training import train

            with redirect_stdout(sys.stderr):
                result = train(load_config(args.config), args.train, args.dev, args.output)
        content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.command == "process" and args.output:
            args.output.write_text(content, encoding="utf-8")
        else:
            print(content, end="")
        return 0
    except Exception as exc:
        print(
            f"kopii failed ({type(exc).__name__}); no successful result was returned. "
            "Check configuration, dependencies, dataset schema, and output run identity.",
            file=sys.stderr,
        )
        return 1
