# Implementation status

Updated: 2026-08-16

## Complete

- Local Python package with locked dependencies and one-time bootstrap.
- Native MCP stdio server targeting protocol revision `2026-07-28` through the
  official Python SDK v2.
- Optional non-root Docker image with separate writable index and read-only
  corpus mounts.
- Authorised local PDF ingestion with path, file type, size, page count, and
  official-source host validation.
- Clause-aware extraction for multiple numbered sections on one page.
- SQLite FTS5 search with source, document, revision, and status filters.
- Exact document-edition metadata and stable document/passage resource URIs.
- Strict JSON manifest ingestion with duplicate detection, staged integrity
  checking, and atomic index replacement.
- Tests, linting, formatting, strict type checking, package builds, CI, and
  native/Docker smoke checks.
- Real-corpus validation against six current CCSDS Blue Books and five active
  ECSS standards: 1,180 PDF pages, 5,238 indexed passages, CLI retrieval, MCP
  tool calls, and MCP resource reads. Source files and the local manifest remain
  outside Git.
- User-level Codex MCP registration and discovery through a clean Codex client.
  End-to-end CCSDS and ECSS questions returned the correct document editions,
  pages, clauses, and official source URLs.
- A 60-query CCSDS/ECSS benchmark with 55 graded positive cases, five
  no-answer cases, multiple valid cross-standard passages, coverage tags, and
  passage-level MRR/nDCG. `pypdf` achieves 100% hit-rate@3, 80% top-1, 0.888
  MRR, 0.787 nDCG@3, 100% no-answer accuracy, and complete citation fields.
- A terms-aware official-source acquisition helper with discovery-only default,
  active and historical CCSDS catalogue filtering, ECSS bulk bootstrap sources,
  host-restricted redirects, bounded atomic downloads, signature validation,
  SHA-256 verification manifests, and source-specific local directories.
- Safe PDF-only ZIP extraction with traversal, symlink, encryption, duplicate,
  type, member-count, and decompressed-size checks; successful extraction is
  published atomically with a member-hash receipt that is verified on reuse.
  Acquisition records generate ingestion metadata. Any inferred ECSS archive
  metadata adds a blocking review marker, so it cannot be indexed by accident.
- An optional, exactly pinned PDF Inspector backend and isolated A/B benchmark.
  `pypdf` indexed 1,180/1,180 pages with 100% hit-rate@3 and 80% top-1 in 9.8
  seconds at a 144.6 MiB peak. PDF Inspector indexed 1,178/1,180 pages with
  63.6% hit-rate@3 and 50.9% top-1 in 45.9 seconds at a 219.5 MiB peak. Its two
  OCR-risk pages were visually confirmed as a vector-text cover and an ECSS
  change-log page. It remains experimental rather than the default.

## Awaiting user-controlled inputs

- Access to the authenticated SANA API documentation and a permitted read-only
  SANA account. Do not send credentials in chat; use an authenticated browser
  session or an approved local credential mechanism when integration starts.
- GitHub repository visibility and software licence selection before commit and
  publication.

## Next implementation stage

Inspect the authenticated SANA API documentation, record its contract and
terms, then implement a redacted-fixture-backed read-only provider. Until SANA
access is approved, prepare the GitHub repository metadata and repeat the Codex
registration and corpus bootstrap on the work laptop. Review the two pages
flagged by PDF Inspector and select an authorised local OCR backend only if the
source page images contain material that the current text layer omits.
