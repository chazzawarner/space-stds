from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from space_stds.acquisition import extract_pdf_archive
from space_stds.domain import Corpus, DocumentStatus, InvalidSourceError
from space_stds.manifest import load_manifest

_MAX_ACQUISITION_MANIFEST_BYTES = 10 * 1024 * 1024
_EXTRACTION_RECEIPT = ".space-stds-extraction.json"
_ECSS_REVISION = re.compile(r"[-_ ]Rev\.?\s*(?P<revision>\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PreparationOutcome:
    documents: int
    inferred_metadata: int
    manifest_path: Path
    ready_for_ingestion: bool


def prepare_acquired_corpus(
    acquisition_manifest: Path,
    corpus_root: Path,
    output_manifest: Path,
) -> PreparationOutcome:
    """Verify acquired files, extract archives, and generate an ingestion manifest."""
    corpus_root = corpus_root.expanduser().resolve()
    acquisition_manifest = acquisition_manifest.expanduser().resolve()
    output_manifest = output_manifest.expanduser().resolve()
    payload = _read_acquisition_manifest(acquisition_manifest)
    records = payload.get("downloads")
    if not isinstance(records, list) or not records:
        raise InvalidSourceError("Acquisition manifest downloads must be a non-empty list")
    if payload.get("failures", 0) != 0:
        raise InvalidSourceError("Cannot prepare a corpus from a failed acquisition manifest")

    documents: list[dict[str, str]] = []
    inferred = 0
    for index, raw_record in enumerate(records):
        record = _validated_record(raw_record, index)
        local_path = _local_file(corpus_root, record["local_file"], index)
        expected_hash = record["sha256"]
        if _sha256_file(local_path) != expected_hash:
            raise InvalidSourceError(
                f"Acquisition file hash does not match manifest: {record['local_file']}"
            )
        if local_path.suffix.casefold() == ".pdf":
            document, was_inferred = _document_from_pdf(record, local_path, corpus_root)
            documents.append(document)
            inferred += int(was_inferred)
            continue
        if local_path.suffix.casefold() != ".zip":
            raise InvalidSourceError(f"Unsupported acquisition file: {record['local_file']}")

        extracted_root = (
            corpus_root
            / record["source"].casefold()
            / "extracted"
            / f"{local_path.stem}-{expected_hash[:12]}"
        )
        if extracted_root.exists():
            extracted = _existing_extracted_pdfs(extracted_root, expected_hash)
        else:
            extracted = extract_pdf_archive(local_path, extracted_root)
        for extracted_pdf in extracted:
            document, _ = _document_from_pdf(record, extracted_pdf, corpus_root, force_infer=True)
            documents.append(document)
            inferred += 1

    documents.sort(key=lambda item: (item["source"], item["document_id"], item["revision"]))
    identities: set[tuple[str, str, str]] = set()
    for document in documents:
        identity = (document["source"], document["document_id"], document["revision"])
        if identity in identities:
            raise InvalidSourceError(
                f"Generated manifest contains duplicate edition: {document['document_id']} "
                f"revision {document['revision']}"
            )
        identities.add(identity)

    generated: dict[str, object] = {"schema_version": 1, "documents": documents}
    if inferred:
        generated["metadata_review_required"] = True
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    partial = output_manifest.with_name(f"{output_manifest.name}.part")
    try:
        partial.write_text(json.dumps(generated, indent=2) + "\n")
        if not inferred:
            load_manifest(partial, corpus_root)
        os.replace(partial, output_manifest)
    finally:
        partial.unlink(missing_ok=True)
    return PreparationOutcome(len(documents), inferred, output_manifest, not inferred)


def _read_acquisition_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise InvalidSourceError(f"Acquisition manifest is not a file: {path}")
    payload = path.read_bytes()
    if len(payload) > _MAX_ACQUISITION_MANIFEST_BYTES:
        raise InvalidSourceError("Acquisition manifest exceeds size limit")
    try:
        root = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSourceError(f"Cannot parse acquisition manifest {path.name}: {exc}") from exc
    if not isinstance(root, dict) or root.get("mode") != "acquisition":
        raise InvalidSourceError("Expected an acquisition-mode manifest")
    return cast(dict[str, Any], root)


def _validated_record(value: object, index: int) -> dict[str, str]:
    if not isinstance(value, dict):
        raise InvalidSourceError(f"Acquisition record {index} must be an object")
    required = {
        "source",
        "document_id",
        "title",
        "revision",
        "status",
        "official_url",
        "local_file",
        "sha256",
    }
    if not required.issubset(value):
        raise InvalidSourceError(f"Acquisition record {index} is missing required fields")
    record = {key: value[key] for key in required}
    if any(not isinstance(item, str) for item in record.values()):
        raise InvalidSourceError(f"Acquisition record {index} fields must be strings")
    if record["source"] not in {"CCSDS", "ECSS"}:
        raise InvalidSourceError(f"Acquisition record {index} has invalid source")
    if record["status"] not in {"active", "superseded", "obsolete", "draft"}:
        raise InvalidSourceError(f"Acquisition record {index} has invalid status")
    if not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
        raise InvalidSourceError(f"Acquisition record {index} has invalid SHA-256")
    return cast(dict[str, str], record)


def _local_file(corpus_root: Path, value: str, index: int) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise InvalidSourceError(f"Acquisition record {index} local_file must be relative")
    resolved = (corpus_root / relative).resolve()
    try:
        resolved.relative_to(corpus_root)
    except ValueError as exc:
        raise InvalidSourceError(
            f"Acquisition record {index} local_file escapes the corpus root"
        ) from exc
    if not resolved.is_file():
        raise InvalidSourceError(f"Acquisition file is not present: {value}")
    return resolved


def _document_from_pdf(
    record: dict[str, str],
    pdf: Path,
    corpus_root: Path,
    *,
    force_infer: bool = False,
) -> tuple[dict[str, str], bool]:
    source = cast(Corpus, record["source"])
    was_inferred = (
        force_infer or not record["document_id"].strip() or not record["revision"].strip()
    )
    if was_inferred:
        if source != "ECSS":
            raise InvalidSourceError(f"Cannot infer CCSDS metadata from archive member {pdf.name}")
        document_id, revision = _infer_ecss_identity(pdf)
        title = document_id
    else:
        document_id = record["document_id"].strip()
        revision = record["revision"].strip()
        title = record["title"].strip() or document_id
    return (
        {
            "source": source,
            "document_id": document_id,
            "title": title,
            "revision": revision,
            "status": cast(DocumentStatus, record["status"]),
            "official_url": record["official_url"],
            "file": pdf.relative_to(corpus_root).as_posix(),
        },
        was_inferred,
    )


def _infer_ecss_identity(pdf: Path) -> tuple[str, str]:
    stem = re.sub(r"\([^)]*\)$", "", pdf.stem).strip()
    revision_match = _ECSS_REVISION.search(stem)
    revision = revision_match.group("revision") if revision_match else "0"
    if revision_match:
        stem = stem[: revision_match.start()]
    document_id = stem.replace("_Part", " Part ").replace("_", " ").strip(" -")
    if not re.fullmatch(r"ECSS-[A-Z]+-(?:AS|HB|ST|TM)-[A-Za-z0-9 .-]+", document_id):
        raise InvalidSourceError(f"Cannot infer ECSS document identity from {pdf.name}")
    return document_id, revision


def _existing_extracted_pdfs(root: Path, archive_hash: str) -> list[Path]:
    receipt_path = root / _EXTRACTION_RECEIPT
    try:
        receipt = json.loads(receipt_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSourceError(f"Existing extraction has no valid receipt: {root}") from exc
    if not isinstance(receipt, dict) or receipt.get("archive_sha256") != archive_hash:
        raise InvalidSourceError(f"Existing extraction does not match its archive: {root}")
    recorded = receipt.get("members")
    if not isinstance(recorded, dict) or not recorded:
        raise InvalidSourceError(f"Existing extraction receipt has no members: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file() and path != receipt_path)
    actual_names = {path.relative_to(root).as_posix() for path in files}
    if actual_names != set(recorded):
        raise InvalidSourceError(f"Existing extraction member set has changed: {root}")
    pdfs = files
    if not pdfs:
        raise InvalidSourceError(f"Existing extraction contains no files: {root}")
    for path in pdfs:
        with path.open("rb") as source:
            signature = source.read(5)
        if path.suffix.casefold() != ".pdf" or signature != b"%PDF-":
            raise InvalidSourceError(f"Existing extraction contains an invalid file: {path}")
        relative = path.relative_to(root).as_posix()
        if not isinstance(recorded[relative], str) or _sha256_file(path) != recorded[relative]:
            raise InvalidSourceError(f"Existing extraction member hash has changed: {path}")
    return pdfs


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
