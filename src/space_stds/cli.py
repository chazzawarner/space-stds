from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from space_stds.config import Settings
from space_stds.corpus_setup import prepare_acquired_corpus
from space_stds.domain import Corpus, DocumentStatus, IngestRequest, SpaceStdsError
from space_stds.server import create_server
from space_stds.service import StandardsService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="space-stds",
        description=(
            "Local CCSDS and ECSS retrieval server. Source documents never leave this machine."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create the local corpus and index directories")

    ingest = subparsers.add_parser("ingest", help="Index one locally authorised PDF")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--source", choices=("CCSDS", "ECSS"), required=True)
    ingest.add_argument("--document-id", required=True)
    ingest.add_argument("--title", required=True)
    ingest.add_argument("--revision", required=True)
    ingest.add_argument(
        "--status", choices=("active", "superseded", "obsolete", "draft"), required=True
    )
    ingest.add_argument("--official-url", required=True)

    ingest_manifest = subparsers.add_parser(
        "ingest-manifest", help="Atomically rebuild the index from a JSON manifest"
    )
    ingest_manifest.add_argument("path", type=Path)

    prepare_corpus = subparsers.add_parser(
        "prepare-corpus",
        help=(
            "Verify an acquisition manifest, safely extract archives, "
            "and generate ingestion metadata"
        ),
    )
    prepare_corpus.add_argument("acquisition_manifest", type=Path)
    prepare_corpus.add_argument(
        "--output",
        type=Path,
        help="Output path; defaults to ingestion-manifest.generated.json in the corpus directory",
    )

    search = subparsers.add_parser("search", help="Run a local diagnostic search")
    search.add_argument("query")
    search.add_argument("--source", choices=("CCSDS", "ECSS"))
    search.add_argument("--document-id")
    search.add_argument("--revision")
    search.add_argument("--status", choices=("active", "superseded", "obsolete", "draft"))
    search.add_argument("--limit", type=int, default=10)

    document = subparsers.add_parser("document", help="Show one exact indexed document edition")
    document.add_argument("document_id")
    document.add_argument("--revision")
    document.add_argument("--source", choices=("CCSDS", "ECSS"))

    subparsers.add_parser("serve", help="Serve MCP over stdio")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_environment()
    settings.initialise()
    service = StandardsService(
        settings.database_path,
        settings.corpus_dir,
        pdf_backend=settings.pdf_backend,
    )

    try:
        if args.command == "init":
            _print_json(
                {
                    "database": str(settings.database_path),
                    "corpus": str(settings.corpus_dir),
                    "policy": "Keep this directory and all source documents outside Git.",
                }
            )
            return 0
        if args.command == "ingest":
            outcome = service.ingest(
                IngestRequest(
                    source=cast(Corpus, args.source),
                    document_id=args.document_id,
                    title=args.title,
                    revision=args.revision,
                    status=cast(DocumentStatus, args.status),
                    official_url=args.official_url,
                    path=args.path,
                )
            )
            _print_json(service.serialise(outcome))
            return 0
        if args.command == "ingest-manifest":
            _print_json(service.serialise(service.ingest_manifest(args.path)))
            return 0
        if args.command == "prepare-corpus":
            output = args.output or settings.corpus_dir / "ingestion-manifest.generated.json"
            preparation = prepare_acquired_corpus(
                args.acquisition_manifest,
                settings.corpus_dir,
                output,
            )
            _print_json(
                {
                    "documents": preparation.documents,
                    "inferred_metadata": preparation.inferred_metadata,
                    "manifest_path": str(preparation.manifest_path),
                    "ready_for_ingestion": preparation.ready_for_ingestion,
                }
            )
            return 0
        if args.command == "search":
            _print_json(
                [
                    service.serialise(hit)
                    for hit in service.search(
                        args.query,
                        source=cast(Corpus | None, args.source),
                        document_id=args.document_id,
                        revision=args.revision,
                        status=cast(DocumentStatus | None, args.status),
                        limit=args.limit,
                    )
                ]
            )
            return 0
        if args.command == "document":
            document = service.get_document(
                args.document_id,
                revision=args.revision,
                source=cast(Corpus | None, args.source),
            )
            _print_json(service.serialise(document))
            return 0
        if args.command == "serve":
            create_server(service).run(transport="stdio")
            return 0
    except (SpaceStdsError, ValueError) as exc:
        parser.error(str(exc))
    raise AssertionError(f"Unhandled command: {args.command}")


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
