from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from space_stds.domain import (
    AmbiguousDocumentError,
    Corpus,
    Document,
    DocumentNotFoundError,
    DocumentStatus,
    IngestOutcome,
    IngestRequest,
    InvalidSourceError,
    ManifestOutcome,
    Passage,
    PassageNotFoundError,
    SearchHit,
)
from space_stds.manifest import load_manifest
from space_stds.pdf import PdfBackend, extract_pdf

_MAX_PDF_BYTES = 100 * 1024 * 1024
_QUERY_TOKEN = re.compile(r"[^\W_]+(?:[.-][^\W_]+)*", re.UNICODE)
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "must",
    "of",
    "on",
    "or",
    "shall",
    "should",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
_ALLOWED_HOSTS = {
    "CCSDS": {"ccsds.org", "www.ccsds.org", "public.ccsds.org"},
    "ECSS": {"ecss.nl", "www.ecss.nl", "escies.org", "www.escies.org"},
}


class StandardsService:
    """Deep boundary for authorised ingestion and citation-preserving retrieval."""

    def __init__(
        self,
        database_path: Path,
        corpus_root: Path,
        *,
        pdf_backend: PdfBackend = "pypdf",
    ) -> None:
        """Initialise local storage, the corpus boundary, and the search schema."""

        self.database_path = database_path.expanduser().resolve()
        self.corpus_root = corpus_root.expanduser().resolve()
        self.pdf_backend = pdf_backend
        self.corpus_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def ingest(self, request: IngestRequest) -> IngestOutcome:
        """Validate and atomically replace one indexed document edition."""

        source_path = self._validated_source_path(request.path)
        self._validate_metadata(request)
        size = source_path.stat().st_size
        if size > _MAX_PDF_BYTES:
            raise InvalidSourceError(
                f"PDF is {size} bytes; maximum accepted size is {_MAX_PDF_BYTES} bytes"
            )
        content_hash = _sha256_file(source_path)
        document_key = _document_key(request)

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT content_hash FROM documents WHERE document_key = ?", (document_key,)
            ).fetchone()
            if existing is not None and existing["content_hash"] == content_hash:
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM passages WHERE document_key = ?",
                    (document_key,),
                ).fetchone()["count"]
                return IngestOutcome(
                    document_key,
                    content_hash,
                    count,
                    True,
                    self.pdf_backend,
                    0,
                    0,
                    0,
                    0,
                )

        extracted = extract_pdf(source_path, backend=self.pdf_backend)
        ingested_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM documents WHERE document_key = ?", (document_key,))
            connection.execute(
                """
                INSERT INTO documents (
                    document_key, source, document_id, title, revision, status,
                    official_url, source_path, content_hash, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_key,
                    request.source,
                    request.document_id.strip(),
                    request.title.strip(),
                    request.revision.strip(),
                    request.status,
                    request.official_url,
                    str(source_path),
                    content_hash,
                    ingested_at,
                ),
            )
            for index, item in enumerate(extracted.passages):
                passage_id = hashlib.sha256(
                    f"{document_key}:{item.page}:{index}".encode()
                ).hexdigest()[:24]
                connection.execute(
                    """
                    INSERT INTO passages (
                        passage_id, document_key, document_id, document_title,
                        page, section, content
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        passage_id,
                        document_key,
                        request.document_id.strip(),
                        request.title.strip(),
                        item.page,
                        item.section,
                        item.content,
                    ),
                )
            connection.commit()
        return IngestOutcome(
            document_key,
            content_hash,
            len(extracted.passages),
            False,
            extracted.backend,
            extracted.page_count,
            len(extracted.pages_needing_ocr),
            len(extracted.pages_with_tables),
            len(extracted.pages_with_columns),
        )

    def ingest_manifest(self, manifest_path: Path) -> ManifestOutcome:
        """Build a complete staged index and replace the live database atomically."""

        requests, manifest_hash = load_manifest(manifest_path, self.corpus_root)
        with tempfile.TemporaryDirectory(
            prefix=".space-stds-stage-", dir=self.database_path.parent
        ) as stage_directory:
            staged_path = Path(stage_directory) / "index.sqlite3"
            staged_service = StandardsService(
                staged_path, self.corpus_root, pdf_backend=self.pdf_backend
            )
            outcomes = [staged_service.ingest(request) for request in requests]
            replacement_path = Path(stage_directory) / "replacement.sqlite3"
            with (
                _managed_connection(staged_path) as source_connection,
                _managed_connection(replacement_path) as replacement_connection,
            ):
                source_connection.backup(replacement_connection)
                integrity = replacement_connection.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise InvalidSourceError("Staged index failed SQLite integrity check")
            self._replace_database(replacement_path)
        return ManifestOutcome(
            indexed_documents=len(outcomes),
            indexed_passages=sum(outcome.indexed_passages for outcome in outcomes),
            manifest_hash=manifest_hash,
            extraction_backend=self.pdf_backend,
            pages=sum(outcome.pages for outcome in outcomes),
            pages_needing_ocr=sum(outcome.pages_needing_ocr for outcome in outcomes),
            pages_with_tables=sum(outcome.pages_with_tables for outcome in outcomes),
            pages_with_columns=sum(outcome.pages_with_columns for outcome in outcomes),
        )

    def search(
        self,
        query: str,
        *,
        source: Corpus | None = None,
        document_id: str | None = None,
        revision: str | None = None,
        status: DocumentStatus | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Return citation-rich passages ranked by lexical relevance and coverage."""

        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        match_query = _fts_query(query)
        conditions = ["passages_fts MATCH ?", "p.section IS NOT NULL"]
        parameters: list[object] = [match_query]
        if source is not None:
            conditions.append("d.source = ?")
            parameters.append(source)
        if document_id is not None:
            conditions.append("d.document_id = ? COLLATE NOCASE")
            parameters.append(document_id.strip())
        if revision is not None:
            conditions.append("d.revision = ? COLLATE NOCASE")
            parameters.append(revision.strip())
        if status is not None:
            conditions.append("d.status = ?")
            parameters.append(status)
        candidate_limit = limit if document_id is not None else min(max(limit * 20, 100), 500)
        parameters.append(candidate_limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    p.passage_id, p.page, p.section, p.content,
                    d.source, d.document_id, d.title, d.revision, d.status,
                    d.official_url,
                    bm25(passages_fts, 8.0, 5.0, 3.0, 1.0) AS lexical_rank
                FROM passages_fts AS f
                JOIN passages AS p ON p.rowid = f.rowid
                JOIN documents AS d ON d.document_key = p.document_key
                WHERE {" AND ".join(conditions)}
                ORDER BY lexical_rank, d.source, d.document_id, d.revision, p.page
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        rows = _rerank_rows(rows, query)
        rows = _diversify_documents(rows, limit) if document_id is None else rows[:limit]
        return [
            SearchHit(
                passage_id=row["passage_id"],
                source=row["source"],
                document_id=row["document_id"],
                title=row["title"],
                revision=row["revision"],
                status=row["status"],
                page=row["page"],
                section=row["section"],
                excerpt=_excerpt(row["content"], query),
                official_url=row["official_url"],
                resource_uri=_resource_uri(row["passage_id"]),
            )
            for row in rows
        ]

    def get_document(
        self, document_id: str, *, revision: str | None = None, source: Corpus | None = None
    ) -> Document:
        """Resolve one document edition, rejecting absent or ambiguous identifiers."""

        conditions = ["d.document_id = ? COLLATE NOCASE"]
        parameters: list[object] = [document_id.strip()]
        if revision is not None:
            conditions.append("d.revision = ? COLLATE NOCASE")
            parameters.append(revision.strip())
        if source is not None:
            conditions.append("d.source = ?")
            parameters.append(source)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    d.document_key, d.source, d.document_id, d.title, d.revision,
                    d.status, d.official_url, d.content_hash, d.ingested_at,
                    COUNT(p.passage_id) AS passages
                FROM documents AS d
                LEFT JOIN passages AS p ON p.document_key = d.document_key
                WHERE {" AND ".join(conditions)}
                GROUP BY d.document_key
                ORDER BY d.source, d.document_id, d.revision
                """,
                parameters,
            ).fetchall()
        if not rows:
            detail = f" revision {revision}" if revision is not None else ""
            raise DocumentNotFoundError(f"Document not found: {document_id}{detail}")
        if len(rows) > 1:
            revisions = ", ".join(row["revision"] for row in rows)
            raise AmbiguousDocumentError(
                f"Document {document_id} has multiple editions ({revisions}). Specify revision."
            )
        return _document_from_row(rows[0])

    def get_document_by_key(self, document_key: str) -> Document:
        """Return the exact document edition addressed by an opaque resource key."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    d.document_key, d.source, d.document_id, d.title, d.revision,
                    d.status, d.official_url, d.content_hash, d.ingested_at,
                    COUNT(p.passage_id) AS passages
                FROM documents AS d
                LEFT JOIN passages AS p ON p.document_key = d.document_key
                WHERE d.document_key = ?
                GROUP BY d.document_key
                """,
                (document_key,),
            ).fetchone()
        if row is None:
            raise DocumentNotFoundError(f"Document not found: {document_key}")
        return _document_from_row(row)

    def get_passage(self, passage_id: str) -> Passage:
        """Return complete passage content and immutable source provenance."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    p.passage_id, p.page, p.section, p.content,
                    d.source, d.document_id, d.title, d.revision, d.status,
                    d.official_url, d.content_hash, d.ingested_at
                FROM passages AS p
                JOIN documents AS d ON d.document_key = p.document_key
                WHERE p.passage_id = ?
                """,
                (passage_id,),
            ).fetchone()
        if row is None:
            raise PassageNotFoundError(f"Passage not found: {passage_id}")
        return Passage(
            passage_id=row["passage_id"],
            source=row["source"],
            document_id=row["document_id"],
            title=row["title"],
            revision=row["revision"],
            status=row["status"],
            page=row["page"],
            section=row["section"],
            content=row["content"],
            official_url=row["official_url"],
            content_hash=row["content_hash"],
            ingested_at=row["ingested_at"],
            resource_uri=_resource_uri(row["passage_id"]),
        )

    @staticmethod
    def serialise(
        value: IngestOutcome | ManifestOutcome | Document | SearchHit | Passage,
    ) -> dict[str, Any]:
        """Convert a supported immutable domain record to structured output."""

        return asdict(value)

    def _validated_source_path(self, candidate: Path) -> Path:
        """Resolve a PDF source and enforce the configured corpus boundary."""

        resolved = candidate.expanduser().resolve()
        try:
            resolved.relative_to(self.corpus_root)
        except ValueError as exc:
            raise InvalidSourceError(
                f"Source must be beneath configured corpus root {self.corpus_root}"
            ) from exc
        if not resolved.is_file():
            raise InvalidSourceError(f"Source is not a file: {resolved}")
        if resolved.suffix.lower() != ".pdf":
            raise InvalidSourceError("Only PDF source files are accepted")
        return resolved

    @staticmethod
    def _validate_metadata(request: IngestRequest) -> None:
        """Require complete identity fields and an official allowlisted HTTPS URL."""

        for name, value in (
            ("document_id", request.document_id),
            ("title", request.title),
            ("revision", request.revision),
        ):
            if not value.strip():
                raise InvalidSourceError(f"{name} must not be empty")
        parsed = urlparse(request.official_url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS[request.source]:
            hosts = ", ".join(sorted(_ALLOWED_HOSTS[request.source]))
            raise InvalidSourceError(
                f"official_url for {request.source} must use HTTPS on one of: {hosts}"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured transactional connection and always close it."""

        connection = sqlite3.connect(self.database_path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _replace_database(self, replacement_path: Path) -> None:
        """Checkpoint the live index before atomically installing a staged database."""

        with self._connect() as connection:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and checkpoint[0] != 0:
                raise InvalidSourceError(
                    "Index is busy; stop the MCP server before manifest ingestion"
                )
        for suffix in ("-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        os.replace(replacement_path, self.database_path)
        self._initialise()

    def _initialise(self) -> None:
        """Create or migrate the persistent tables, indexes, triggers, and FTS index."""

        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    document_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL CHECK (source IN ('CCSDS', 'ECSS')),
                    document_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'superseded', 'obsolete', 'draft')),
                    official_url TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS passages (
                    passage_id TEXT PRIMARY KEY,
                    document_key TEXT NOT NULL REFERENCES documents(document_key) ON DELETE CASCADE,
                    document_id TEXT NOT NULL,
                    document_title TEXT NOT NULL,
                    page INTEGER NOT NULL CHECK (page > 0),
                    section TEXT,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS passages_document_key_idx
                    ON passages(document_key);
                CREATE INDEX IF NOT EXISTS documents_document_id_idx
                    ON documents(document_id COLLATE NOCASE);
                """
            )
            _ensure_search_schema(connection)


def _document_key(request: IngestRequest) -> str:
    """Derive a stable opaque key from source, document identifier, and revision."""

    canonical = "|".join(
        (request.source, request.document_id.strip().upper(), request.revision.strip().upper())
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


@dataclass(frozen=True, order=True, slots=True)
class _RetrievalRank:
    """Define deterministic ordering signals for lexical retrieval candidates."""

    negative_bigrams: int
    negative_title_matches: int
    negative_coverage: int
    negative_section_matches: int
    lexical_rank: float
    source: str
    document_id: str
    revision: str
    page: int

    @property
    def coverage(self) -> int:
        """Expose positive query-term coverage from the sort-oriented stored value."""

        return -self.negative_coverage


def _diversify_documents(rows: list[sqlite3.Row], limit: int) -> list[sqlite3.Row]:
    """Reserve result capacity for distinct editions before adding repeat passages."""

    selected: list[sqlite3.Row] = []
    deferred: list[sqlite3.Row] = []
    documents: set[tuple[str, str, str]] = set()
    document_quota = limit if limit <= 2 else math.ceil(limit / 2)
    for row in rows:
        identity = (row["source"], row["document_id"], row["revision"])
        if identity in documents:
            continue
        documents.add(identity)
        selected.append(row)
        if len(selected) == document_quota:
            break
    selected_ids = {row["passage_id"] for row in selected}
    deferred.extend(row for row in rows if row["passage_id"] not in selected_ids)
    selected.extend(deferred[: limit - len(selected)])
    return selected


def _rerank_rows(rows: list[sqlite3.Row], query: str) -> list[sqlite3.Row]:
    """Rerank FTS candidates by phrase, title, term, and section coverage."""

    query_roots = _token_roots(query)
    query_bigrams = set(zip(query_roots, query_roots[1:], strict=False))

    def rank(row: sqlite3.Row) -> _RetrievalRank:
        """Calculate deterministic semantic and lexical signals for one candidate."""

        title_roots = _token_roots(row["title"])
        section_roots = _token_roots(row["section"] or "")
        combined_roots = _token_roots(
            f"{row['document_id']} {row['title']} {row['section'] or ''} {row['content']}"
        )
        combined = set(combined_roots)
        coverage = sum(root in combined for root in query_roots)
        adjacent = set(zip(combined_roots, combined_roots[1:], strict=False))
        bigrams = len(query_bigrams & adjacent)
        title_matches = sum(root in set(title_roots) for root in query_roots)
        section_matches = sum(root in set(section_roots) for root in query_roots)
        return _RetrievalRank(
            negative_bigrams=-bigrams,
            negative_title_matches=-title_matches,
            negative_coverage=-coverage,
            negative_section_matches=-section_matches,
            lexical_rank=float(row["lexical_rank"]),
            source=str(row["source"]),
            document_id=str(row["document_id"]),
            revision=str(row["revision"]),
            page=int(row["page"]),
        )

    minimum_coverage = 1 if len(query_roots) <= 2 else math.ceil(len(query_roots) * 0.6)
    ranked = [(rank(row), row) for row in rows]
    return [
        row
        for score, row in sorted(ranked, key=lambda item: item[0])
        if score.coverage >= minimum_coverage
    ]


def _ensure_search_schema(connection: sqlite3.Connection) -> None:
    """Migrate passage fields and rebuild FTS when its external-content schema changes."""

    passage_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(passages)").fetchall()
    }
    migrated = "document_id" not in passage_columns
    if migrated:
        connection.execute("ALTER TABLE passages ADD COLUMN document_id TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "ALTER TABLE passages ADD COLUMN document_title TEXT NOT NULL DEFAULT ''"
        )
        connection.execute(
            """
            UPDATE passages
            SET
                document_id = (
                    SELECT document_id FROM documents
                    WHERE documents.document_key = passages.document_key
                ),
                document_title = (
                    SELECT title FROM documents
                    WHERE documents.document_key = passages.document_key
                )
            """
        )

    fts_columns = [
        row[1] for row in connection.execute("PRAGMA table_info(passages_fts)").fetchall()
    ]
    expected = ["document_id", "document_title", "section", "content"]
    recreated = bool(fts_columns) and fts_columns != expected
    if recreated:
        connection.executescript(
            """
            DROP TRIGGER IF EXISTS passages_insert;
            DROP TRIGGER IF EXISTS passages_delete;
            DROP TRIGGER IF EXISTS passages_update;
            DROP TABLE passages_fts;
            """
        )

    connection.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
            document_id,
            document_title,
            section,
            content,
            content='passages',
            content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS passages_insert AFTER INSERT ON passages BEGIN
            INSERT INTO passages_fts(
                rowid, document_id, document_title, section, content
            ) VALUES (
                new.rowid, new.document_id, new.document_title, new.section, new.content
            );
        END;
        CREATE TRIGGER IF NOT EXISTS passages_delete AFTER DELETE ON passages BEGIN
            INSERT INTO passages_fts(
                passages_fts, rowid, document_id, document_title, section, content
            ) VALUES (
                'delete', old.rowid, old.document_id, old.document_title,
                old.section, old.content
            );
        END;
        CREATE TRIGGER IF NOT EXISTS passages_update AFTER UPDATE ON passages BEGIN
            INSERT INTO passages_fts(
                passages_fts, rowid, document_id, document_title, section, content
            ) VALUES (
                'delete', old.rowid, old.document_id, old.document_title,
                old.section, old.content
            );
            INSERT INTO passages_fts(
                rowid, document_id, document_title, section, content
            ) VALUES (
                new.rowid, new.document_id, new.document_title, new.section, new.content
            );
        END;
        """
    )
    if migrated or recreated or not fts_columns:
        connection.execute("INSERT INTO passages_fts(passages_fts) VALUES ('rebuild')")


@contextmanager
def _managed_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a transactional SQLite connection and close it on every exit path."""

    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _sha256_file(path: Path) -> str:
    """Calculate a streaming SHA-256 digest for an authorised source PDF."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fts_query(query: str) -> str:
    """Translate meaningful query terms into a bounded FTS any-term expression."""

    tokens = _query_tokens(query)
    if not tokens:
        raise ValueError("query must contain at least one searchable term")
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens[:20])


def _excerpt(content: str, query: str, *, width: int = 600) -> str:
    """Select a bounded excerpt around the earliest matching meaningful term."""

    lowered = content.casefold()
    positions = [lowered.find(token.casefold()) for token in _query_tokens(query)]
    starts = [position for position in positions if position >= 0]
    centre = min(starts) if starts else 0
    start = max(0, centre - width // 3)
    end = min(len(content), start + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end].strip()}{suffix}"


def _query_tokens(query: str) -> list[str]:
    """Return unique case-folded query tokens, preferring non-stopwords."""

    tokens = _QUERY_TOKEN.findall(query)
    meaningful = [token for token in tokens if token.casefold() not in _QUERY_STOPWORDS]
    selected = meaningful or tokens
    return list(dict.fromkeys(token.casefold() for token in selected))


def _token_roots(text: str) -> list[str]:
    """Reduce searchable tokens to lightweight roots used by the reranker."""

    return [_light_stem(token) for token in _query_tokens(text)]


def _light_stem(token: str) -> str:
    """Remove a small set of English suffixes without an external stemmer."""

    if len(token) > 5 and token.endswith("ies"):
        return f"{token[:-3]}y"
    for suffix in ("able", "ible", "ing", "ed", "es", "s"):
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _resource_uri(passage_id: str) -> str:
    """Build the canonical MCP resource URI for an indexed passage."""

    return f"space-stds://passages/{passage_id}"


def _document_resource_uri(document_key: str) -> str:
    """Build the canonical MCP resource URI for one document edition."""

    return f"space-stds://documents/{document_key}"


def _document_from_row(row: sqlite3.Row) -> Document:
    """Map a document query row to the public immutable domain record."""

    return Document(
        document_key=row["document_key"],
        source=row["source"],
        document_id=row["document_id"],
        title=row["title"],
        revision=row["revision"],
        status=row["status"],
        official_url=row["official_url"],
        content_hash=row["content_hash"],
        ingested_at=row["ingested_at"],
        passages=row["passages"],
        resource_uri=_document_resource_uri(row["document_key"]),
    )


__all__ = ["IngestRequest", "StandardsService"]
