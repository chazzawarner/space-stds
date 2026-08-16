# Research note: MCP server for CCSDS, ECSS and SANA

Checked: 2026-08-16. This note uses primary sources only. Statements labelled **Fact** report published requirements or observed official interfaces. Statements labelled **Design inference** are recommendations for this project, not requirements imposed by a source.

## Executive conclusion

**Design inference.** Build a local-first, read-only MCP knowledge server in Python using the official MCP SDK. Ship `stdio` first and keep the public GitHub repository free of standards PDFs, extracted text, embeddings and employer data. Index CCSDS publications and user-supplied ECSS files into a local, ignored data directory; query SANA live through its authenticated REST interface if an account is available, with a conservative cached/read-only fallback only after its reuse terms are confirmed. This boundary is the safest way to make the code portable to a work laptop without republishing protected material.

The current MCP revision is a material break from the 2025 generation. New code should target `2026-07-28`, but dual-era compatibility is useful because older clients cannot automatically adopt the modern protocol. The server needs tools and resources; prompts, elicitation, sampling and remote OAuth are not needed for the first release.

## Current MCP requirements

### Revision and protocol shape

- **Fact.** The latest stable specification is dated **2026-07-28**. It uses JSON-RPC 2.0, stateless self-contained requests and per-request capability/version metadata. The modern protocol has no `initialize` handshake; every request declares its version and client capabilities. Servers must implement `server/discover`. Unsupported versions produce `UnsupportedProtocolVersionError` (`-32022`) with supported versions. Optional extensions are negotiated through `capabilities.extensions`. See the [2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28), [release announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/) and [versioning rules](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning).
- **Fact.** `2026-07-28` and later are the “modern” era; `2025-11-25` and earlier use initialization-based sessions. A dual-era server may support both, but a legacy-only client cannot “fall forward” to a modern-only server. [Versioning and compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning) defines the detection and fallback matrix.
- **Design inference.** Target `2026-07-28`, then enable the official SDK's dual-era mode if it is stable. Test both a modern client and the actual agent/client used at work before calling compatibility complete.

### Transports

- **Fact.** The two standard bindings are `stdio` (newline-delimited JSON-RPC over a client-launched subprocess) and Streamable HTTP (one POST per message to a single endpoint; the response is JSON or a request-scoped SSE stream). Custom transports are allowed if they preserve the protocol semantics. See [transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports).
- **Fact.** Modern Streamable HTTP does not use the old long-lived GET stream or `Mcp-Session-Id`. It mirrors protocol metadata into HTTP headers and requires header/body agreement. Implementations must validate `Origin`; local HTTP servers should bind only to loopback. See [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http).
- **Design inference.** Use `stdio` for v1. It is easier to install from GitHub, requires no hosted infrastructure or OAuth, and keeps licensed content on the laptop. Add Streamable HTTP only for a defined multi-user or cross-machine need.

### Tools, resources and prompts

- **Fact.** Tools are model-controlled functions (`tools/list`, `tools/call`). Servers declare the `tools` capability. Tool inputs are JSON Schema objects; the 2026 revision defaults to JSON Schema 2020-12 and permits an optional output schema and structured content. Expected domain/validation failures belong in a successful tool result with `isError: true`; protocol, malformed-request and unknown-method failures use JSON-RPC errors. See [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
- **Fact.** Resources are application-controlled, URI-addressed context (`resources/list`, `resources/read`, resource templates). Servers declare `resources`, optionally with list-change and subscription support. A missing resource is an invalid-parameters error, not an empty successful response. See [Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources).
- **Fact.** Prompts are user-controlled reusable templates (`prompts/list`, `prompts/get`) and require an explicit `prompts` capability. See [Prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts).
- **Design inference.** The smallest useful surface is:

  - `search_standards(query, corpus?, status?, limit?, cursor?)` — ranked metadata/full-text hits with document number, revision, publication date, status, page/section and source URL;
  - `get_document(document_id)` — authoritative metadata and availability, never silently choosing an obsolete issue;
  - `read_section(document_id, locator)` — bounded text from a locally authorised copy, with citation coordinates;
  - `search_sana(query, registry?, status?, limit?, cursor?)` and `get_sana_record(registry, record_id)` — structured registry results;
  - resources such as `ccsds://document/{id}`, `ecss://document/{id}` and `sana://registry/{registry}/record/{id}`.

  Prompts such as “compare revisions” can wait. Keep tools narrow and return structured results as well as short text summaries.

### Capabilities, pagination, caching and errors

- **Fact.** A server must advertise only the capabilities it implements. Tool/resource/prompt lists can vary by per-request authorisation, not by incidental connection state. Deterministic list ordering enables caching. See [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), [Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources) and [Prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts).
- **Fact.** `resources/list`, `resources/templates/list`, `prompts/list` and `tools/list` use server-sized pages and opaque cursors. Clients must not parse cursors or treat an empty string as end-of-results. An invalid cursor should return `-32602`. Modern list/read results can include `ttlMs` and `cacheScope`. See [Pagination](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/pagination).
- **Design inference.** Use stable keyset cursors over `(corpus, canonical_id, revision)` rather than offsets. Bind each cursor to a normalised query and index generation, and reject mismatches. Put source/revision/page in every hit so the agent can verify claims.

### Authentication and security

- **Fact.** MCP authorisation is optional. HTTP implementations that use it should follow the MCP OAuth profile; `stdio` should obtain credentials from the environment instead. A protected HTTP server acts as an OAuth 2.1 resource server. It must publish RFC 9728 protected-resource metadata; its authorisation server uses RFC 8414 or OpenID Connect discovery. The profile requires resource indicators/audience binding, bearer tokens in headers rather than query strings, token validation, and appropriate `401`/`403` challenges. Dynamic Client Registration remains only for backwards compatibility; Client ID Metadata Documents or pre-registration are preferred. See [Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) and [security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations).
- **Fact.** MCP's general security principles require user consent/control, data protection and treating tool metadata as untrusted. See [specification security principles](https://modelcontextprotocol.io/specification/2026-07-28#security-and-trust--safety).
- **Design inference.** Treat PDFs, extracted text, web pages and registry fields as untrusted content. Separate ingestion from query serving; reject path traversal and arbitrary URLs; enforce source allowlists, content types, byte/page/chunk/output limits and timeouts; never execute embedded content; record hashes and provenance. Do not log document text or credentials. A read-only server should expose no download, write, update or registry-assignment tools.

### Elicitation, sampling and SDKs

- **Fact.** Elicitation remains available through multi-round-trip `input_required` results, but form mode must not request secrets; URL mode covers sensitive external interaction. See [Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation). Sampling, roots and protocol logging are deprecated in this revision, with a minimum deprecation window; see [Sampling](https://modelcontextprotocol.io/specification/2026-07-28/client/sampling) and the [release announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/).
- **Design inference.** This read-only server needs none of elicitation, sampling, roots or protocol logging. Use ordinary configuration, `stderr` or OpenTelemetry for diagnostics.
- **Fact.** MCP now publishes SDK tiers. Tier 1 requires a stable release, 100% applicable conformance, comprehensive documentation and defined maintenance/security response; Tier 2 requires at least 80% conformance and active progress. See the [SDK tiering system](https://modelcontextprotocol.io/community/sdk-tiers) and [official conformance suite](https://github.com/modelcontextprotocol/conformance).
- **Fact.** At this revision, official Tier 1 SDKs for TypeScript, Python, Go and C# support `2026-07-28`; Rust support is still maturing. Python v2 is the stable `mcp` package line and supports both protocol eras by default. See the [official SDK repositories](https://github.com/modelcontextprotocol), [Python SDK release notes](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md), [TypeScript migration notes](https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28) and [Go releases](https://github.com/modelcontextprotocol/go-sdk/releases).
- **Design inference.** Prefer Python v2 for PDF ingestion, text processing and local search ergonomics. Pin the SDK and all parsing dependencies with a lockfile. Run the official conformance suite plus MCP Inspector smoke tests in CI.

## Official corpus access and constraints

### CCSDS publications

- **Fact.** CCSDS provides a public publications catalogue organised by book colour and technical area. Blue Books are Recommended Standards, Magenta Books Recommended Practices, Green Books Informational Reports, Orange Books Experimental, Yellow Books Records and Silver Books historical/obsolete. The site exposes both active-only and active-plus-obsolete catalogues and direct publication files. See [CCSDS Publications](https://ccsds.org/publications/).
- **Fact.** The official publication search exposes document number, title, book type, issue, publication date, description, working group, ISO equivalent, patent licensing and extra information. Individual entries link the PDF and identify status/type. See [Search CCSDS Publications](https://ccsds.org/searchpubs/) and an [example publication entry](https://ccsds.org/publications/allpubs/entry/3211/).
- **Fact.** CCSDS states that “reasonable reuse” of published material is generally permitted with attribution; organisations needing formal reprint permission can request it from the CCSDS Secretariat. Individual entries can also flag patent-licensing information. See the reproduction-permission statement on [CCSDS Publications](https://ccsds.org/publications/).
- **Design inference.** It is reasonable to ingest publicly released CCSDS PDFs locally and return short, attributed excerpts with exact publication identity and page/section. Do not assume that “reasonable reuse” permits republishing the full corpus, extracted text or embeddings on GitHub. Seek written permission before distributing any substantial derived corpus, and preserve patent notices as metadata.
- **Finding from official-source search.** No documented public CCSDS catalogue API was located. The interactive catalogue and direct file links are official access mechanisms, but automated harvesting limits are not stated on the reviewed pages. Prefer a manifest-driven importer with rate limiting, conditional requests and a contact/permission step before bulk mirroring.

### ECSS standards and handbooks

- **Fact.** ECSS publishes active and superseded standards by branch. Its pages list document number/revision, title and publication date and provide PDF or Word downloads; ECSS also links complete active/superseded ZIP sets. See [Standards](https://ecss.nl/standards/), [Space engineering](https://ecss.nl/standards/active-standards/engineering/) and [complete-set downloads](https://ecss.nl/standards/downloads__trashed/ecss-cd-download/).
- **Fact.** Access is subject to the ECSS licence/disclaimer. ESA, on behalf of participating members, holds copyright in all ECSS documents. The published policy says no ECSS document may be reproduced without explicit ESA consent, while ECSS members have consent for their own use and for their contractors/subcontractors. It requires acknowledgement and exact reference/version for authorised quotations or derived documents. See the [ECSS licence agreement](https://ecss.nl/license-agreement-disclaimer/), sourced there to ECSS-P-00C clause 5.8.
- **Fact.** ECSS asks users to register to use the website, and an older official help page states that only registered users may download published standards and that downloading accepts the licence. See [How can I download ECSS Standards?](https://ecss.nl/helpdesk/how-can-i-download-ecss-standards/). Current catalogue pages are visible publicly, but that does not override the licence.
- **Design inference.** Do not download, bundle, commit, publish or centrally cache ECSS full text in the public project. Make ECSS ingestion an explicit local command over files the work user is authorised to possess. Store only a public metadata manifest in Git; put extracted text/indexes under an ignored data path. Before deploying to colleagues or returning more than minimal quotations, have the employer confirm ECSS-member/contractor status or obtain ESA permission. The server should always label ECSS output with exact number, revision and locator and should prefer the active revision unless the caller explicitly requests superseded material.
- **Finding from official-source search.** No documented public ECSS API was located. Treat the branch catalogues and authorised download bundles as the supported interfaces; do not automate authenticated website access without permission.

### SANA registries

- **Fact.** SANA is the CCSDS registrar for protocol registries. Its site exposes approved, candidate and obsolete registries; public search and browsing; an OID-tree browser; file-bearing registries; and a “Discover the REST API” link. Most registries can be browsed without an account, but some, including Service Sites and Apertures and SCID management, require one. See [SANA home](https://sanaregistry.org/) and [account guidance](https://sanaregistry.org/howto/accounts/).
- **Fact.** The generic registry model includes registry status/title, creation/update dates, policy, authority, OID, notes/files and heterogeneous record fields. Records commonly include status, identifiers/OIDs and references. Registry pages support filtering, sorting and page-size/page query parameters. See [registry guidance](https://sanaregistry.org/howto/registries/) and the [CCSDS Terms registry](https://sanaregistry.org/r/terms/).
- **Fact.** In an unauthenticated check on 2026-08-16, the official `/api/` link redirected to login. Official search results also expose CSV-export URLs that redirect to login. The public documentation reviewed does not describe anonymous API credentials, endpoint schemas, rate limits or a general data-reuse licence. The site directs questions to `info@sanaregistry.org`. See the [REST API entry point](https://sanaregistry.org/api/) and [SANA home](https://sanaregistry.org/).
- **Design inference.** Use the official REST API only with a user-provided SANA account and after reviewing its authenticated API documentation. Keep credentials in the environment/keychain, never in the repository. If anonymous live HTML reads are used for a prototype, constrain them to public registry URLs, cache briefly, identify the client, rate-limit heavily and do not treat undocumented HTML as a stable API. Before bulk caching or redistribution, ask SANA to confirm permitted use and rate limits. Prefer live record URLs and identifiers over republishing registry datasets.

## Recommended delivery plan

1. **Confirm legal and client boundaries.** Identify the exact work agent/client and supported MCP eras. Ask the employer whether it is an ECSS member/authorised contractor. Ask CCSDS/SANA about bulk access and derived-index redistribution if needed. Record the decision; do not block a local metadata-only prototype.
2. **Scaffold a public code-only repository.** Use Python v2, `src/` packaging, locked dependencies, tests, CI, licence, security policy and setup instructions for `uvx`/`pipx` or a virtual environment. Add strong ignore rules for `data/`, PDFs, extracted text, indexes, caches, credentials and logs. Provide a local configuration example with no secrets.
3. **Define the canonical domain model.** Represent `Corpus`, `Document`, `Edition`, `Locator`, `SourceFile`, `Registry`, `RegistryRecord` and `Citation`. Preserve canonical ID, revision/issue, active/superseded status, publication date, source URL, checksum, ingestion time and rights/access class. Never merge editions into one text record.
4. **Implement authorised ingestion.** Add a manifest-based CCSDS metadata/PDF importer with conservative networking. Add an ECSS local-file importer only. Parse PDFs defensively, retain page boundaries and record extraction failures. Build a deterministic SQLite FTS5 index first; evaluate embeddings only after lexical retrieval and citation quality are measured.
5. **Implement the MCP read surface.** Start with the five tools and three resource URI families proposed above. Advertise only tools/resources. Add opaque keyset pagination, bounded results, structured schemas, deterministic ordering and actionable errors. Every textual claim returned from a document must carry corpus, document number, exact edition and page/section.
6. **Integrate SANA separately.** Build a provider interface, then implement authenticated official REST access from the documentation visible after login. Add small TTL caches and map heterogeneous records without discarding original fields. Keep a disabled or metadata-only provider when credentials are absent.
7. **Verify end to end.** Unit-test ID normalisation, revision precedence, pagination/cursor tampering, locators, permissions and malicious PDFs/HTML. Add golden retrieval tests for known clauses and SANA records. Run MCP conformance tests and Inspector smoke tests over `stdio`; then exercise the real work-agent flow from a clean checkout with locally supplied documents.
8. **Release conservatively.** Tag a private or public GitHub release containing code only. Document exactly what the installer must download or supply, which content never leaves the laptop, and how to remove the local index. Add remote HTTP/OAuth, prompts, embeddings or shared hosting only in separate, justified increments.

## Decisions still requiring confirmation

- Which MCP client/agent will run on the work laptop, and does it support `2026-07-28` or require dual-era compatibility?
- Is the employer an ECSS member, an authorised contractor/subcontractor, or otherwise licensed to reproduce/index ECSS text?
- Does the work environment permit public GitHub, Python package installation and local SQLite indexes?
- Can a SANA account be used for API access, and what terms/rate limits does the authenticated documentation specify?
- Must search work offline, or is live CCSDS/SANA access acceptable?

