#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from space_stds.acquisition import (
    OfficialDownload,
    discover_ccsds_publications,
    discover_directory_downloads,
    download_official,
)
from space_stds.corpus_setup import prepare_acquired_corpus

CCSDS_CATALOGUE = "https://ccsds.org/publications/ccsdsallpubs/"
ECSS_ARCHIVES = "https://escies.org/ftp/ecss.nl/ECSS/"
ECSS_TECHNICAL_MEMORANDA = "https://escies.org/ftp/ecss.nl/TMs/"
CCSDS_BOOK_TYPES = (
    "Blue Book",
    "Magenta Book",
    "Green Book",
    "Orange Book",
    "Yellow Book",
    "Silver Book",
)
CCSDS_ACTIVE_BOOK_TYPES = tuple(kind for kind in CCSDS_BOOK_TYPES if kind != "Silver Book")
ECSS_COLLECTIONS = ("standards", "handbooks", "technical-memoranda")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover or download official CCSDS and ECSS publication files"
    )
    parser.add_argument("--source", choices=("all", "CCSDS", "ECSS"), default="all")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(
            os.environ.get("SPACE_STDS_CORPUS_DIR", "~/.local/share/space-stds/corpus")
        ).expanduser(),
    )
    parser.add_argument(
        "--ccsds-book-type",
        action="append",
        choices=CCSDS_BOOK_TYPES,
        help="Repeat to select book types; defaults to every active catalogue type",
    )
    parser.add_argument(
        "--ecss-collection",
        action="append",
        choices=ECSS_COLLECTIONS,
        help="Repeat to select collections; defaults to all three",
    )
    parser.add_argument("--list", action="store_true", help="Print discovered records as JSON")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Write the discovery plan or acquisition manifest to this local path",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download files; without this flag the command performs discovery only",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch valid existing files and replace them only when their SHA-256 changes",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="After a successful download, safely extract archives and generate ingestion metadata",
    )
    parser.add_argument(
        "--ingestion-manifest",
        type=Path,
        help="Generated ingestion manifest path used with --prepare",
    )
    parser.add_argument(
        "--accept-ecss-license",
        action="store_true",
        help="Confirm that the ECSS licence applies to this local use",
    )
    parser.add_argument(
        "--accept-ccsds-reuse-terms",
        action="store_true",
        help="Confirm review of the CCSDS reproduction statement for this local use",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between individual downloads in seconds (default: 0.25)",
    )
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()

    if args.delay < 0:
        parser.error("--delay must not be negative")
    if args.prepare and not args.download:
        parser.error("--prepare requires --download")
    if args.download and args.source in {"all", "ECSS"} and not args.accept_ecss_license:
        parser.error("ECSS downloads require --accept-ecss-license")
    if args.download and args.source in {"all", "CCSDS"} and not args.accept_ccsds_reuse_terms:
        parser.error("CCSDS downloads require --accept-ccsds-reuse-terms")

    downloads: list[OfficialDownload] = []
    if args.source in {"all", "CCSDS"}:
        downloads.extend(_discover_ccsds(set(args.ccsds_book_type or CCSDS_ACTIVE_BOOK_TYPES)))
    if args.source in {"all", "ECSS"}:
        downloads.extend(_discover_ecss(set(args.ecss_collection or ECSS_COLLECTIONS)))

    counts = Counter((item.source, item.kind) for item in downloads)
    print(f"Discovered {len(downloads)} official files")
    for (source, kind), count in sorted(counts.items()):
        print(f"  {source} / {kind}: {count}")
    existing_count = sum(
        (destination / item.source.casefold() / item.filename).exists() for item in downloads
    )
    print(f"Plan: {len(downloads) - existing_count} new, {existing_count} already present")
    if args.list:
        print(json.dumps([asdict(item) for item in downloads], indent=2))
    if not args.download:
        if args.manifest is not None:
            _write_manifest(
                args.manifest,
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "mode": "discovery",
                    "downloads": [
                        {
                            **asdict(item),
                            "plan": (
                                "existing-unverified"
                                if (destination / item.source.casefold() / item.filename).exists()
                                else "new"
                            ),
                        }
                        for item in downloads
                    ],
                },
            )
        print("Discovery only; add --download and the applicable acceptance flags to fetch files.")
        return 0

    failures = 0
    acquired: list[dict[str, object]] = []
    for index, item in enumerate(downloads):
        try:
            source_destination = destination / item.source.casefold()
            outcome = download_official(
                item,
                source_destination,
                replace_existing=args.refresh,
            )
            state = "verified existing" if outcome.unchanged else "downloaded"
            print(f"{state}: {outcome.path}")
            acquired.append(
                {
                    **asdict(item),
                    "local_file": str(outcome.path.relative_to(destination)),
                    "sha256": outcome.sha256,
                    "size": outcome.size,
                    "downloaded": not outcome.unchanged,
                    "verified_at": datetime.now(UTC).isoformat(),
                }
            )
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"failed: {item.url}: {exc}")
        if index + 1 < len(downloads) and args.delay:
            time.sleep(args.delay)
    manifest_path = args.manifest or destination / "acquisition-manifest.json"
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "acquisition",
        "downloads": acquired,
        "failures": failures,
    }
    if failures:
        failed_path = manifest_path.with_name(f"{manifest_path.name}.failed")
        _write_manifest(failed_path, manifest)
        print(f"Failed-attempt report: {failed_path.expanduser().resolve()}")
        print("The authoritative acquisition manifest was not replaced.")
    else:
        _write_manifest(manifest_path, manifest)
        print(f"Manifest: {manifest_path.expanduser().resolve()}")
        if args.prepare:
            ingestion_manifest = (
                args.ingestion_manifest or destination / "ingestion-manifest.generated.json"
            )
            preparation = prepare_acquired_corpus(
                manifest_path,
                destination,
                ingestion_manifest,
            )
            print(
                f"Prepared {preparation.documents} documents; "
                f"inferred metadata for {preparation.inferred_metadata}."
            )
            print(f"Ingestion manifest: {preparation.manifest_path}")
            if not preparation.ready_for_ingestion:
                print(
                    "Metadata review required: reconcile inferred ECSS records with the "
                    "official catalogue, then remove metadata_review_required."
                )
    print(f"Completed with {failures} failure(s)")
    return 1 if failures else 0


def _discover_ccsds(book_types: set[str]) -> list[OfficialDownload]:
    return discover_ccsds_publications(_read_text(CCSDS_CATALOGUE), book_types=book_types)


def _discover_ecss(collections: set[str]) -> list[OfficialDownload]:
    downloads: list[OfficialDownload] = []
    if collections & {"standards", "handbooks"}:
        archives = discover_directory_downloads(
            _read_text(ECSS_ARCHIVES),
            base_url=ECSS_ARCHIVES,
            suffixes=(".zip",),
        )
        if "standards" in collections:
            downloads.extend(
                item
                for item in archives
                if item.document_id.startswith("Active ECSS Standards_PDF-files")
            )
        if "handbooks" in collections:
            downloads.extend(
                item for item in archives if item.document_id.startswith("ECSS-Handbooks_")
            )
    if "technical-memoranda" in collections:
        downloads.extend(
            discover_directory_downloads(
                _read_text(ECSS_TECHNICAL_MEMORANDA),
                base_url=ECSS_TECHNICAL_MEMORANDA,
                suffixes=(".pdf",),
            )
        )
    return downloads


def _read_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "space-stds/0.1 (+local corpus setup)"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    try:
        partial.write_text(json.dumps(manifest, indent=2) + "\n")
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
