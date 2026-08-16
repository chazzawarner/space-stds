# Space standards MCP server: proposed plan

Date: 2026-08-16

## Recommendation

Build a local-first, read-only Python MCP server. Publish the source code, tests,
schemas, and non-copyright metadata on GitHub. Keep standards PDFs, extracted
text, indexes, credentials, and SANA personal data outside Git.

Use the official Python MCP SDK v2 and support both `stdio` and Streamable HTTP
from the same application core. Make `stdio` the first supported deployment:
clone the repository on the work laptop, ingest locally authorised documents,
and register one command with the MCP host. Add remote HTTP only if there is a
real multi-user requirement.

This design has four important properties:

1. Answers remain traceable to an exact document, edition, clause, page, and
   official source URL.
2. Copyrighted material and credentials do not enter the public repository.
3. Search works offline for CCSDS and ECSS documents already acquired.
4. SANA remains live data and is accessed through a replaceable, read-only
   adapter rather than copied into the document corpus.

## Current MCP baseline

Target the stable MCP revision `2026-07-28`. It replaced protocol sessions and
the required initial handshake with self-describing requests and optional
`server/discover`. Streamable HTTP now uses one POST per JSON-RPC request and
requires `Mcp-Method` and, where applicable, `Mcp-Name` headers. List and read
results can supply cache hints. Roots, sampling, protocol logging, and legacy
HTTP+SSE are deprecated, so this server should not depend on them.

The official Python SDK v2 is a Tier 1 SDK for this revision and also serves
older MCP clients. That compatibility is useful because the MCP host available
on the work laptop may lag the newest protocol revision.

The server needs only these MCP primitives:

- **Tools** for search, metadata lookup, passage retrieval, and live SANA
  queries.
- **Resources** for stable, addressable documents and passages.
- **No prompts initially.** Prompt templates do not improve the retrieval
  contract and add another interface to maintain.
- **No tasks, elicitation, sampling, or server-side session state.** The first
  release consists of bounded, read-only requests.

## Proposed interface

Keep the tool catalogue small and deterministic:

| Tool | Purpose |
| --- | --- |
| `search_standards` | Search CCSDS and/or ECSS with optional document, edition, status, book colour/branch, and result-count filters. |
| `get_passage` | Retrieve a cited passage plus bounded neighbouring clauses or pages. |
| `get_document` | Return canonical metadata, revision status, local availability, table of contents, and official links. |
| `list_sana_registries` | List readable registries and their update timestamps. |
| `search_sana` | Query one registry with registry-specific filters and cursor pagination. |
| `get_sana_record` | Retrieve one record by stable registry and record identifier. |

Return structured results as well as short text suitable for a model. Every
standards hit should contain:

- organisation, canonical document identifier, title, edition/revision, date,
  and active/superseded status;
- clause/section and PDF page where available;
- an exact, short excerpt;
- official source URL, local content hash, and ingestion timestamp;
- a stable resource URI such as
  `space-stds://documents/CCSDS-131.0-B-5/passages/<id>`.

Never present generated summaries as standards text. Label quotations and
derived summaries separately. A client should be able to retrieve the cited
passage without rerunning a fuzzy search.

## Repository and application shape

```text
space-stds/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── SECURITY.md
├── src/space_stds/
│   ├── server.py             # MCP registration and transports
│   ├── service.py            # transport-independent query API
│   ├── domain.py             # document, passage, citation, registry types
│   ├── search.py             # query parsing, ranking, pagination
│   ├── store.py              # SQLite repository boundary
│   ├── ingest/
│   │   ├── pipeline.py
│   │   ├── pdf.py
│   │   ├── ccsds.py
│   │   └── ecss.py
│   └── sana/
│       ├── client.py
│       └── models.py
├── tests/
│   ├── fixtures/             # synthetic/permitted excerpts only
│   ├── contract/
│   ├── integration/
│   └── unit/
└── docs/
    ├── proposal.md
    └── research/
```

Use SQLite with FTS5 for the first release. Space standards rely heavily on
exact identifiers, defined terms, requirement words, and clause references;
lexical search handles these well, remains deterministic, has no model cost,
and avoids sending standards text to an embedding provider. Add an optional
local embedding index only after evaluation demonstrates a material retrieval
gain.

Chunk by document structure, not fixed token count. Preserve clauses, headings,
numbered requirements, notes, tables, figure captions, and cross-references.
Store page boundaries and clause ancestry. PDF extraction must flag malformed or
image-only pages instead of silently indexing poor text; OCR can be an explicit
optional step.

## Source and rights strategy

### CCSDS

Treat the official CCSDS publications catalogue as the metadata authority and
official publication PDFs as acquisition targets. Store a local manifest with
document identifier, colour, status, edition, publication date, official URL,
hash, and retrieval time. Do not commit the PDFs or extracted text. Before a
public release, confirm the intended automated-download and local-indexing use
with CCSDS terms or the Secretariat; the current site footer states that rights
are reserved.

### ECSS

Do not automate around the ECSS acceptance/registration flow. ECSS states that
ESA holds copyright, restricts reproduction, and conditions downloads on its
licence. The program should ingest a user-supplied directory after the user has
obtained the documents under an applicable licence. The public repository may
contain only metadata and instructions. At startup and ingestion time, show the
configured corpus path and never copy source files into the repository.

### SANA

Use the official REST API where authorised. The API link currently redirects an
anonymous user to login, while most registry pages remain publicly browsable.
Start by obtaining/using a SANA account, recording the official API contract,
authentication mechanism, rate limits, and reuse terms. Implement a typed API
adapter against recorded, redacted fixtures. Do not fall back to undocumented
HTML scraping unless SANA explicitly permits it.

Exclude contact names, email addresses, and other personal fields by default.
Expose them only when the selected registry genuinely requires them and the
local policy permits it.

## Security and trust boundary

The first release is read-only, but it still processes untrusted PDFs, remote
registry values, and model-supplied arguments.

- Validate all tool inputs and resource URIs with closed schemas.
- Resolve corpus paths beneath an explicit configured root; reject traversal
  and symbolic-link escape.
- Allow outbound requests only to configured CCSDS, ECSS, and SANA hosts.
- Set download size, page count, redirect, response time, and concurrency
  limits.
- Treat document text as data, never as instructions. Delimit and label all
  excerpts returned to the model.
- Redact secrets and personal fields from logs, fixtures, errors, and tool
  results.
- Use environment variables or the operating-system credential store for SANA
  credentials; never accept downstream tokens from the MCP client or commit
  secrets.
- Hash source files and make ingestion idempotent. Build a new index in a
  temporary database, validate it, then atomically replace the active index.
- For a future HTTP deployment, use HTTPS and the MCP OAuth requirements. Do
  not invent API-key-in-query-string authentication or pass MCP tokens through
  to SANA.

## Delivery plan

### Phase 0: rights and access spike

Deliverables:

- written corpus policy for public GitHub versus local work data;
- confirmed ECSS entitlement/use route for the user's employer;
- confirmed CCSDS automated retrieval/local indexing position;
- working, read-only SANA API request and redacted response fixture;
- a five-document evaluation set and 20 representative questions.

Exit criterion: each source has a lawful, repeatable acquisition path. If SANA
API access cannot be confirmed, defer SANA live querying rather than shipping a
brittle scraper.

### Phase 1: vertical slice

Implement Python packaging, configuration, SQLite schema, one CCSDS document
ingester, clause-aware extraction, `search_standards`, `get_passage`, and stdio.
Add exact-reference, phrase, no-result, malformed-PDF, and path-boundary tests.

Exit criterion: from a fresh clone, one documented command builds an index and
an MCP client can find and retrieve a known clause with a valid citation.

### Phase 2: complete local corpus support

Add CCSDS catalogue metadata, user-supplied ECSS ingestion, revision/status
handling, tables of contents, atomic incremental re-indexing, and
`get_document`. Evaluate search against the 60-query graded set and record
passage hit-rate, reciprocal rank, nDCG, no-answer accuracy, citation-field
completeness, and extraction failures.

Exit criterion: at least one graded relevant passage for every positive case
appears in the first five results, and every returned excerpt resolves to the
correct local source, edition, clause, and page.

### Phase 3: SANA integration

Implement the typed read-only client, registry discovery, registry-specific
filter schemas, pagination, caching based on update times, rate limiting, and
personal-field policy. Use contract tests against redacted fixtures and a
manually enabled live smoke test.

Exit criterion: the three SANA tools query at least two materially different
registries, paginate correctly, and fail clearly on authentication, rate-limit,
schema-change, and network errors.

### Phase 4: portability and release

Add GitHub Actions for linting, typing, tests, dependency review, and secret
scanning. Document installation with `uv`, corpus setup, MCP-host configuration,
corporate proxy/custom CA settings, update and rollback procedures, and licence
boundaries. Tag a versioned release; do not publish corpus artefacts in release
assets or CI caches.

Exit criterion: a clean work-laptop clone can install from the lockfile, ingest
locally supplied material, pass a smoke test, and connect over stdio without
developer-only paths.

### Phase 5: optional shared service

Only if several colleagues need the same index, add Streamable HTTP, HTTPS,
MCP-compliant OAuth, per-user authorisation, audit events, deployment manifests,
and a licence review for centrally stored documents. Keep the local stdio mode.

## Decisions deliberately deferred

- **Hosted service:** unnecessary until more than one user needs it.
- **Vector database/RAG framework:** add only after measured lexical-search
  failures justify the dependency and data-governance cost.
- **LLM-generated answers inside the server:** the MCP host already provides
  synthesis; the server should retrieve authoritative evidence.
- **Automatic ECSS download:** licence and registration constraints make local
  user-supplied ingestion the safer contract.
- **Write operations against SANA:** out of scope for a standards reference
  server and would require a much stronger authorisation and confirmation model.

## Primary references

- [MCP 2026-07-28 stable release](https://github.com/modelcontextprotocol/modelcontextprotocol/releases/tag/2026-07-28)
- [MCP 2026-07-28 overview](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)
- [Official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [CCSDS publications catalogue](https://ccsds.org/publications/)
- [ECSS active standards](https://ecss.nl/standards/active-standards/)
- [ECSS licence agreement](https://ecss.nl/license-agreement-disclaimer/)
- [SANA registry](https://www.sanaregistry.org/)
