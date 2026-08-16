from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

from space_stds.domain import Corpus, DocumentStatus, IngestRequest, InvalidSourceError

_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_ROOT_KEYS = {"schema_version", "documents"}
_DOCUMENT_KEYS = {
    "source",
    "document_id",
    "title",
    "revision",
    "status",
    "official_url",
    "file",
}
_SOURCES = {"CCSDS", "ECSS"}
_STATUSES = {"active", "superseded", "obsolete", "draft"}


def load_manifest(path: Path, corpus_root: Path) -> tuple[list[IngestRequest], str]:
    resolved = path.expanduser().resolve()
    corpus_root = corpus_root.expanduser().resolve()
    if not resolved.is_file():
        raise InvalidSourceError(f"Manifest is not a file: {resolved}")
    payload = resolved.read_bytes()
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise InvalidSourceError(f"Manifest exceeds {_MAX_MANIFEST_BYTES} bytes")
    try:
        root = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidSourceError(f"Cannot parse manifest {resolved.name}: {exc}") from exc
    if not isinstance(root, dict) or set(root) != _ROOT_KEYS:
        raise InvalidSourceError("Manifest must contain exactly schema_version and documents")
    if root["schema_version"] != 1:
        raise InvalidSourceError("Unsupported manifest schema_version; expected 1")
    documents = root["documents"]
    if not isinstance(documents, list) or not documents:
        raise InvalidSourceError("Manifest documents must be a non-empty list")

    requests: list[IngestRequest] = []
    identities: set[tuple[str, str, str]] = set()
    for index, item in enumerate(documents):
        if not isinstance(item, dict) or set(item) != _DOCUMENT_KEYS:
            raise InvalidSourceError(
                f"Manifest document {index} must contain exactly: "
                f"{', '.join(sorted(_DOCUMENT_KEYS))}"
            )
        if any(not isinstance(item[key], str) or not item[key].strip() for key in _DOCUMENT_KEYS):
            raise InvalidSourceError(f"Manifest document {index} fields must be non-empty strings")
        if item["source"] not in _SOURCES:
            raise InvalidSourceError(f"Manifest document {index} has invalid source")
        if item["status"] not in _STATUSES:
            raise InvalidSourceError(f"Manifest document {index} has invalid status")
        relative_file = Path(item["file"])
        if relative_file.is_absolute():
            raise InvalidSourceError(f"Manifest document {index} file must be relative")
        if ".." in relative_file.parts:
            raise InvalidSourceError(
                f"Manifest document {index} file must not contain parent-directory segments"
            )
        resolved_file = (corpus_root / relative_file).resolve()
        try:
            resolved_file.relative_to(corpus_root)
        except ValueError as exc:
            raise InvalidSourceError(
                f"Manifest document {index} file must remain inside the corpus root"
            ) from exc
        identity = (
            item["source"],
            item["document_id"].strip().upper(),
            item["revision"].strip().upper(),
        )
        if identity in identities:
            raise InvalidSourceError(
                f"Manifest contains duplicate document edition: {item['document_id']} "
                f"revision {item['revision']}"
            )
        identities.add(identity)
        requests.append(
            IngestRequest(
                source=cast(Corpus, item["source"]),
                document_id=item["document_id"],
                title=item["title"],
                revision=item["revision"],
                status=cast(DocumentStatus, item["status"]),
                official_url=item["official_url"],
                path=resolved_file,
            )
        )
    return requests, hashlib.sha256(payload).hexdigest()
