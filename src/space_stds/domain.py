from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Corpus = Literal["CCSDS", "ECSS"]
DocumentStatus = Literal["active", "superseded", "obsolete", "draft"]


class SpaceStdsError(Exception):
    """Base class for actionable domain failures."""


class InvalidSourceError(SpaceStdsError):
    """The selected source file or metadata is outside the authorised boundary."""


class PassageNotFoundError(SpaceStdsError):
    """The requested passage does not exist in this index generation."""


class DocumentNotFoundError(SpaceStdsError):
    """The requested document edition is not present in the local index."""


class AmbiguousDocumentError(SpaceStdsError):
    """A document identifier matched more than one indexed edition."""


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """Describe one authorised document edition to validate and index."""

    source: Corpus
    document_id: str
    title: str
    revision: str
    status: DocumentStatus
    official_url: str
    path: Path


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """Report index and extraction diagnostics for one document ingestion."""

    document_key: str
    content_hash: str
    indexed_passages: int
    unchanged: bool
    extraction_backend: str
    pages: int
    pages_needing_ocr: int
    pages_with_tables: int
    pages_with_columns: int


@dataclass(frozen=True, slots=True)
class ManifestOutcome:
    """Report aggregate diagnostics for an atomic manifest ingestion."""

    indexed_documents: int
    indexed_passages: int
    manifest_hash: str
    extraction_backend: str
    pages: int
    pages_needing_ocr: int
    pages_with_tables: int
    pages_with_columns: int


@dataclass(frozen=True, slots=True)
class Document:
    """Expose edition-specific document metadata and immutable provenance."""

    document_key: str
    source: Corpus
    document_id: str
    title: str
    revision: str
    status: DocumentStatus
    official_url: str
    content_hash: str
    ingested_at: str
    passages: int
    resource_uri: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Represent a ranked passage excerpt with the fields needed for citation."""

    passage_id: str
    source: Corpus
    document_id: str
    title: str
    revision: str
    status: DocumentStatus
    page: int
    section: str | None
    excerpt: str
    official_url: str
    resource_uri: str


@dataclass(frozen=True, slots=True)
class Passage:
    """Represent complete indexed passage content with edition provenance."""

    passage_id: str
    source: Corpus
    document_id: str
    title: str
    revision: str
    status: DocumentStatus
    page: int
    section: str | None
    content: str
    official_url: str
    content_hash: str
    ingested_at: str
    resource_uri: str
