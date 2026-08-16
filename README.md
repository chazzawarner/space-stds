# space-stds

Local-first, read-only MCP retrieval for authorised CCSDS and ECSS standards.
The repository contains code only. Standards files, extracted text, indexes,
credentials, logs, and SANA personal data stay outside Git.

The first runnable slice supports:

- local PDF ingestion with source-path and official-host restrictions;
- idempotent SQLite FTS5 indexing;
- citation-rich standards search and passage retrieval;
- revision-aware metadata and corpus/status/document filters;
- atomic whole-corpus rebuilds from a validated JSON manifest;
- MCP `stdio` tools plus document and passage resources;
- native `uv` installation and an optional Docker image.

SANA is not yet connected. Its API requires authenticated documentation and a
confirmed reuse/rate-limit policy. The server does not scrape its HTML pages.

## Recommended native setup

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```sh
./scripts/bootstrap.sh
```

The script installs locked runtime dependencies and creates these local paths:

- `~/.local/share/space-stds/index.sqlite3`
- `~/.local/share/space-stds/corpus/`

Override them before setup if required by work policy:

```sh
export SPACE_STDS_DATA_DIR=/approved/private/index-directory
export SPACE_STDS_CORPUS_DIR=/approved/private/standards-directory
./scripts/bootstrap.sh
```

Place an authorised PDF beneath the corpus directory, then index it with
explicit provenance:

```sh
uv run space-stds ingest "$SPACE_STDS_CORPUS_DIR/131x0b6ec1.pdf" \
  --source CCSDS \
  --document-id "CCSDS 131.0-B-6" \
  --title "TM Synchronization and Channel Coding" \
  --revision "6" \
  --status active \
  --official-url "https://ccsds.org/.../131x0b6ec1.pdf"
```

The command rejects PDFs outside the configured corpus root. ECSS documents
must be acquired separately under an applicable ECSS licence.

## Official-source acquisition

The acquisition helper discovers files without downloading them by default:

```sh
uv run python scripts/download_official_sources.py --source all
```

To download the active CCSDS catalogue PDFs and the ECSS bulk archives/TM
snapshot into source-specific directories beneath the configured corpus:

```sh
uv run python scripts/download_official_sources.py \
  --source all \
  --download \
  --prepare \
  --accept-ccsds-reuse-terms \
  --accept-ecss-license
```

Use `--list` to inspect every discovered record first. Use `--manifest PATH` to
save a discovery plan. Repeat `--ccsds-book-type` or `--ecss-collection` to
select a subset; select `--ccsds-book-type "Silver Book"` explicitly for
historical/obsolete CCSDS publications. Downloads are bounded and atomic,
redirects remain on official hosts, existing files are revalidated, and the
resulting local manifest records source URLs, SHA-256 hashes, sizes, and
verification times. Keep the destination outside the repository.

Use `--refresh` on a later run to re-fetch existing filenames. The helper keeps
the existing file when its SHA-256 is unchanged and atomically replaces it when
the publisher content changed. A partial or failed run writes a separate
failed-attempt report and does not replace the last complete manifest.

With `--prepare`, ZIP members are validated before extraction, archive paths
and links are rejected, decompressed sizes are bounded, and the completed
archive is published atomically beneath the corpus directory. The command then
writes `ingestion-manifest.generated.json`. ECSS archive entries do not contain
complete catalogue metadata. When any values are inferred, the generated file
contains `"metadata_review_required": true`, which makes it invalid for
ingestion. Reconcile each ECSS title, identifier, revision, status, and
canonical document URL against the official catalogue. Then remove that review
marker before indexing:

```sh
uv run space-stds ingest-manifest \
  "$SPACE_STDS_CORPUS_DIR/ingestion-manifest.generated.json"
```

An existing acquisition manifest can be prepared separately:

```sh
uv run space-stds prepare-corpus \
  "$SPACE_STDS_CORPUS_DIR/acquisition-manifest.json"
```

The ECSS bulk PDF archive is a dated standards snapshot, and the handbook and
technical-memoranda sources are not complete current catalogues. The CCSDS
site provides no documented API or all-publications ZIP; the helper reads its
official active-and-obsolete catalogue and will fail if that page's embedded
data contract changes. Review [the acquisition research](docs/research/pdf-ingestion-and-bulk-acquisition.md)
before relying on bulk synchronisation.

## PDF extraction backends

`pypdf` remains the default. PDF Inspector is an optional, exactly pinned native
dependency. Install it before selecting that backend for a complete manifest
rebuild:

```sh
uv sync --extra pdf-inspector
export SPACE_STDS_PDF_BACKEND=pdf-inspector
uv run space-stds ingest-manifest /approved/private/manifest.json
```

PDF Inspector runs locally and reports OCR-risk, table, and multi-column pages.
It does not perform OCR. The automated 11-document, 60-query A/B benchmark
retained `pypdf` as the default. `pypdf` indexed all 1,180 pages, achieved 100%
passage hit-rate@3, 80% top-1, 0.787 nDCG@3, and took 9.7 seconds with a
131.5 MiB peak. PDF Inspector indexed 1,178 pages, achieved 63.6% hit-rate@3,
50.9% top-1, 0.515 nDCG@3, and took 45.8 seconds with a 210.8 MiB peak. Both
achieved 100% no-answer accuracy and citation-field completeness. PDF Inspector
identified a vector-text CCSDS cover and an ECSS change-log page as OCR risks.
A visual check confirmed those classifications, but broader sampled review of
clause boundaries, tables, symbols, and page furniture remains required.

Re-run the benchmark after changing the corpus or either parser:

```sh
uv run --extra pdf-inspector python scripts/benchmark_extractors.py \
  --manifest /approved/private/manifest.json
```

Aggregate results are recorded in
[`benchmarks/extractor-results.json`](benchmarks/extractor-results.json); no
standards text is written to that file.

For repeatable whole-corpus setup, copy
[`examples/manifest.example.json`](examples/manifest.example.json) outside the
repository, edit it, and run:

```sh
uv run space-stds ingest-manifest /approved/private/manifest.json
```

Each `file` is relative to `SPACE_STDS_CORPUS_DIR`. Manifest ingestion builds
and validates a complete staged database before replacing the current index. If
any document fails, the previous index remains available. Stop the MCP server
before rebuilding the index.

Run a diagnostic query:

```sh
uv run space-stds search "attached sync marker"
uv run space-stds search "interface requirement" --source ECSS --status active
uv run space-stds document "CCSDS 131.0-B-6" --revision 6
```

## MCP client configuration

Use the installed executable directly. Replace `/absolute/path/to/space-stds`
and the data paths with real absolute paths:

```json
{
  "mcpServers": {
    "space-stds": {
      "command": "/absolute/path/to/space-stds/.venv/bin/space-stds",
      "args": ["serve"],
      "env": {
        "SPACE_STDS_DATA_DIR": "/approved/private/index-directory",
        "SPACE_STDS_CORPUS_DIR": "/approved/private/standards-directory"
      }
    }
  }
}
```

The exact configuration file depends on the MCP host used at work. The server
writes protocol messages only to stdout; diagnostics from the SDK use stderr.

For Codex, register the native server with the CLI. Use absolute paths:

```sh
codex mcp add space-stds \
  --env SPACE_STDS_DATA_DIR=/approved/private/index-directory \
  --env SPACE_STDS_CORPUS_DIR=/approved/private/standards-directory \
  -- /absolute/path/to/space-stds/.venv/bin/space-stds serve
codex mcp get space-stds
```

Codex stores this user-level configuration in `~/.codex/config.toml`. Restart
Codex after adding the server, then use `/mcp` to confirm that its tools are
available. See the [official Codex MCP configuration guide](https://developers.openai.com/codex/extend/mcp).

The MCP surface is:

- `search_standards(query, source?, document_id?, revision?, status?, limit?)`
- `get_document(document_id, revision?, source?)`
- `get_passage(passage_id)`
- `space-stds://documents/{document_key}`
- `space-stds://passages/{passage_id}`

## Optional Docker setup

Docker is supported but is not required. Native execution is usually simpler
for a desktop MCP client. Build the image once:

```sh
docker build -t space-stds:local .
docker volume create space-stds-data
```

Initialise it, mounting the authorised corpus read-only:

```sh
docker run --rm \
  --mount source=space-stds-data,target=/data \
  --mount type=bind,source=/approved/private/standards-directory,target=/corpus,readonly \
  space-stds:local ingest-manifest /corpus/manifest.json
```

For MCP stdio, retain stdin with `-i`:

```sh
docker run --rm -i \
  --mount source=space-stds-data,target=/data \
  --mount type=bind,source=/approved/private/standards-directory,target=/corpus,readonly \
  space-stds:local serve
```

Use that `docker run` command and arguments in the MCP host if native execution
is prohibited.

## Development checks

```sh
UV_CACHE_DIR=/tmp/space-stds-uv-cache uv sync --frozen --extra dev
UV_CACHE_DIR=/tmp/space-stds-uv-cache uv run pytest
UV_CACHE_DIR=/tmp/space-stds-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/space-stds-uv-cache uv run mypy
```

Run the local-corpus retrieval benchmark after ingestion:

```sh
uv run python scripts/evaluate_retrieval.py \
  --output benchmarks/retrieval-results.json
```

The checked corpus passes all 55 graded positive questions at passage
hit-rate@3 and correctly abstains on all five no-answer questions. Passage-level
top-1 accuracy is 80%, MRR is 0.888, nDCG@3 is 0.787, and every returned result
has a page, section, official source URL, and stable MCP resource URI. The cases
support multiple graded passages for valid cross-standard answers. See
[`benchmarks/retrieval.json`](benchmarks/retrieval.json),
[`benchmarks/retrieval-results.json`](benchmarks/retrieval-results.json), and
[`benchmarks/coverage-gaps.json`](benchmarks/coverage-gaps.json).

See [the proposal](docs/proposal.md), [corpus policy](docs/corpus-policy.md),
[MCP research](docs/research/mcp-standards-server-research.md), and
[acquisition research](docs/research/pdf-ingestion-and-bulk-acquisition.md).
