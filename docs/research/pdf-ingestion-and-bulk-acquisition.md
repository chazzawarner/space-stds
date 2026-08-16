# PDF ingestion and standards acquisition

Research date: 16 August 2026

## Decision summary

Use PDF Inspector as an optional, pinned local extraction backend. It is a good fit for page-scoped Markdown, reading-order recovery, table/column detection, and extraction diagnostics. It must not replace the source PDF as the authoritative artefact, and its inferred headings must not be treated as normative clauses without the existing CCSDS/ECSS-specific parser and validation.

For acquisition:

- ECSS provides official bulk ZIP archives for active standards in PDF and Word format, plus a separate handbook ZIP. These are the preferred bootstrap source.
- ECSS does not expose one current bulk archive that covers standards, handbooks, and all Technical Memoranda (TMs). Current TMs still need to be enumerated from the official ECSS publication pages.
- CCSDS provides an official catalogue of all active and obsolete publications with stable per-publication URLs, explicitly intended for external websites. No documented machine API or official all-publications ZIP was found.
- An auto-downloader is technically feasible for both publishers, but it must distinguish supported bulk links and stable catalogue pages from undocumented website implementation details.
- Downloaded PDFs, archives, extracted text, and indexes must remain local. Bulk availability does not grant republication rights.

## 1. PDF Inspector

### What it is

[PDF Inspector](https://github.com/firecrawl/pdf-inspector) is a pure-Rust PDF analysis and text extraction library published by Firecrawl. The project states that it uses no machine-learning models or external services. It offers Rust, Python, Node, WebAssembly, and command-line interfaces and is licensed under the [MIT licence](https://github.com/firecrawl/pdf-inspector/blob/main/LICENSE).

The documented Python package is `pdf-inspector`, supports CPython 3.8 and later, and provides pre-built wheels for common Linux, macOS, and Windows targets. Other targets require a Rust toolchain and `maturin`. See the project's [Python API documentation](https://github.com/firecrawl/pdf-inspector/blob/main/docs/python.md).

Relevant Python interfaces include:

- `process_pdf` for document analysis;
- `extract_text` for plain text;
- positioned text-item extraction;
- `extract_pages_markdown` for per-page Markdown;
- tagged-PDF structure-tree extraction.

The analysis result reports page count, pages that probably need OCR, reasons for the OCR decision, encoding warnings, and page-layout signals such as columns and tables. The CLI exposes the same general capabilities through `pdf2md` and `detect-pdf`, including JSON, text-item, raw, compact, page-range, and selected-page output. These interfaces are documented in the [repository README](https://github.com/firecrawl/pdf-inspector) and [Python API guide](https://github.com/firecrawl/pdf-inspector/blob/main/docs/python.md).

### What it does not guarantee

PDF Inspector does not currently perform OCR. It identifies pages that should be sent to another OCR backend. This is useful for mixed native-text/scanned standards, but it does not remove the need for a separately approved local OCR tool.

Its Markdown structure is heuristic. Heading levels are inferred from font sizes; tables are inferred from drawing rectangles and text alignment; reading order is reconstructed from PDF geometry. These are valuable signals, not a guarantee that a Markdown heading is the publisher's normative clause boundary. Equations, symbols, multi-column layouts, page furniture, tables, and individually numbered requirements still need corpus-specific validation.

### Maintenance and trust boundary

The project is active and rapidly changing. Its [release tags](https://github.com/firecrawl/pdf-inspector/tags) show version 1.14.2 dated 13 August 2026, and the repository's [package metadata](https://github.com/firecrawl/pdf-inspector/blob/main/pyproject.toml) reports the same version.

PDF parsing processes complex, potentially hostile input. The project's [security policy](https://github.com/firecrawl/pdf-inspector/blob/main/SECURITY.md) explicitly treats crafted-PDF memory-safety failures, out-of-bounds behaviour, undefined behaviour, and denial-of-service defects as in scope. It excludes vulnerabilities that are solely in the upstream `lopdf` dependency. The Python package also introduces platform-specific native wheels into the dependency chain.

For this MCP server:

- pin the exact package version and retain lock-file hashes;
- run ingestion without network access;
- enforce PDF size, page count, processing-time, memory, and output-size limits;
- prefer a short-lived constrained subprocess or container for parsing;
- keep PDF Inspector behind an extractor adapter rather than calling it throughout the service;
- preserve the original PDF and SHA-256 digest;
- record parser name, version, options, ingestion time, and per-page warnings with the derived text.

### Recommended ingestion pipeline

```text
authorised source PDF
  -> SHA-256 and file validation
  -> PDF Inspector page analysis
  -> per-page Markdown and positioned text
  -> optional local OCR for flagged pages only
  -> CCSDS/ECSS clause and requirement parser
  -> extraction validation and sampled page comparison
  -> local search index
```

`extract_pages_markdown` is the best initial integration point because the server's citations depend on stable page attribution. Keep the current extractor available during evaluation.

Before changing the default, compare both extractors on representative CCSDS and ECSS documents. Measure:

- text completeness by page;
- page-number fidelity;
- clause and annex boundaries;
- numbered requirement recognition;
- table reading order;
- equations, units, mathematical symbols, and special characters;
- headers and footers incorrectly retained;
- native-text, scanned, and mixed-page detection;
- ingestion time and peak memory.

## 2. CCSDS acquisition

### Officially supported publication surfaces

The [CCSDS publications overview](https://ccsds.org/publications/) groups documents by book colour and technical area. The [all-active catalogue](https://ccsds.org/publications/allpubs/) covers Blue, Magenta, Green, Orange, and Yellow books. Silver books are deliberately excluded from that active-only view.

The better synchronisation source is the official [All Active and Obsolete Publications](https://ccsds.org/publications/ccsdsallpubs/) catalogue. CCSDS says that this view:

- contains active and obsolete publications;
- is intended for external websites that link to CCSDS publications;
- gives each publication a permanent, stable URL;
- exposes detailed metadata and the publication through the stable document page.

That is an official and expressly supported discovery/linking surface. It is suitable as the catalogue authority for a local downloader.

The catalogue and detail pages expose document number, title, book type, issue number, publication date, description, working group, ISO equivalence, patent information, and a direct PDF download where available. For example, the official entry for [CCSDS 912.1-B-5](https://ccsds.org/publications/allpubs/entry/3003/) identifies the file and its metadata.

CCSDS also states that reasonable reuse of publication material is generally permitted with attribution and that formal reprint permission can be requested from its Secretariat. See the official [reproduction statement on the publication catalogue](https://ccsds.org/publications/allpubs/). This does not justify committing the complete downloaded corpus to this project's GitHub repository.

### What was not found

No official CCSDS page, documented API, RSS/JSON catalogue, or ZIP containing all publications was found in the official publication navigation, search, active catalogue, active-and-obsolete catalogue, or official-site search results.

The current catalogue page embeds the complete table data in the page's JavaScript and also references WordPress/GravityView endpoints. Those details make automated enumeration technically possible, but they are website implementation details, not a published API contract. The old predictable `public.ccsds.org/Pubs/<filename>.pdf` pattern is also not a sufficient catalogue: the legacy directory now redirects to the main CCSDS site, and current PDFs are served from publisher-managed upload paths.

### Recommended CCSDS downloader behaviour

Build a conservative catalogue synchroniser rather than guessing filenames:

1. Fetch the official active-and-obsolete catalogue page.
2. Extract stable document-detail URLs and metadata.
3. Follow each stable detail URL to the publisher-provided PDF URL.
4. Download only PDFs selected by policy: active only by default; obsolete and corrigenda through explicit flags.
5. Store the stable detail URL as `official_url` and the current PDF URL as acquisition metadata.
6. Verify content type, PDF signature, size limit, and SHA-256 before accepting a file.
7. Use conditional HTTP requests where the server supports them; otherwise compare the catalogue metadata and local digest.
8. Apply a descriptive user agent, bounded concurrency, retry limits, and a delay between requests.
9. Produce a manifest and a dry-run diff before downloading or replacing anything.

If CCSDS changes its HTML shape, fail closed and retain the last valid manifest. Do not silently derive filenames or scrape review/working-document areas as though they were approved publications.

## 3. ECSS acquisition

### Official bulk archives

The official [Active Standards](https://ecss.nl/standards/active-standards/) page explicitly links a “Zip-file with all ECSS Standards for download”. The link points to the ESA-hosted ESCIES directory. The official [ESCIES ECSS archive index](https://escies.org/ftp/ecss.nl/ECSS/) currently exposes:

- `Active ECSS Standards_PDF-files (10Oct2025).zip`, 131 MB;
- `Active ECSS Standards_MS Word-files (10Oct2025).zip`, 229 MB;
- `ECSS-Handbooks_(zip-file_October2023).zip`, 358 MB.

Use the PDF ZIP as the normal active-standards bootstrap. Use the handbook ZIP as a bootstrap only: its filename identifies an October 2023 snapshot, while the official [active handbook catalogue](https://ecss.nl/hbs/active-handbooks/) contains later publications, including a handbook dated November 2024. The handbook archive must therefore be followed by a catalogue synchronisation.

ECSS also provides its standards as DOORS modules. The official [DOORS database download](https://ecss.nl/doors-download/) page points to the latest archive and release note and states that the release note contains the extraction password. It also links an EARM Excel export but warns that the Excel file omits figures and tables. DOORS/EARM may later provide useful requirement structure, but neither is a substitute for page-verifiable PDF citations.

### Handbooks and Technical Memoranda

The official [active handbook catalogue](https://ecss.nl/hbs/active-handbooks/) enumerates published handbooks, and individual publication pages provide PDF or Word attachments. Some multi-part handbooks have their own convenience ZIP; for example, the [thermal-design handbook page](https://ecss.nl/hbstms/ecss-e-hb-31-01-part-2a-thermal-design-handbook-part-2-holes-grooves-and-cavities-5-december-2011/) links a PDF ZIP containing all 16 parts.

ECSS publishes TMs through the official [Technical Memoranda catalogue](https://ecss.nl/hbs/tms/) and its Engineering and Product Assurance sub-catalogues. ECSS defines TMs as non-normative information and warns that they are not suitable for direct use in invitations to tender or business agreements, even if they use requirements-style language.

An ESA-hosted [ESCIES TMs directory](https://escies.org/ftp/ecss.nl/TMs/) is technically enumerable, but its visible files are dated April 2012 and do not cover every TM currently listed on ECSS. It is not evidence of a current all-TMs bundle. No official single ZIP covering all current standards, handbooks, and TMs was found.

### Login and licence conditions

ECSS pages and files are technically accessible without an authenticated session at the time of this research, but technical accessibility is not the permission boundary.

The official [ECSS licence agreement](https://ecss.nl/license-agreement-disclaimer/) states that ESA, on behalf of participating members, owns copyright in ECSS documents and that reproduction requires explicit consent, with consent granted to ECSS members for their own use and for their contractors and subcontractors. It also specifies attribution and exact reference/version requirements when ECSS text is used. ECSS pages ask users to register before making use of the website; MyTeams is separately restricted to working-group and task-force members.

The official ESCIES component information page also says that users may download all ECSS standards through the ECSS website “after registration”: [Component Related ECSS and ESA PSS Standards](https://escies.org/webdocument/showArticle?id=167).

Therefore the downloader should:

- require an explicit acknowledgement of the ECSS licence before the first ECSS bulk download;
- support an optional authenticated session if ECSS enforces login;
- never attempt to bypass login, MyTeams, access controls, or download conditions;
- keep the archives, documents, extracted text, and index outside Git;
- retain document version and copyright provenance;
- stop with an actionable error if authentication or licence acceptance becomes necessary.

### Documented interface versus discoverable interface

The ECSS bulk ZIP links and publication pages are official supported download surfaces. The website also exposes public WordPress REST routes. A search request can return ECSS publication records, and individual post records can expose attachment URLs and checksums. This is technically useful, but ECSS does not document that WordPress interface as a standards API or promise its stability.

Use the supported bulk archives and publication pages as the authority. If the WordPress endpoint is used for discovery, isolate it behind a versioned adapter, validate all returned URLs against approved ECSS/ESCIES hosts, and fail closed when its schema changes.

### Recommended ECSS downloader behaviour

1. Require a one-time local licence acknowledgement.
2. Download the official active-standards PDF ZIP and handbook ZIP with size limits and redirects restricted to ECSS/ESCIES hosts.
3. Record archive URL, retrieval time, ETag/Last-Modified where available, size, and SHA-256.
4. Extract into a staging directory and reject path traversal, links, unexpected file types, and duplicate output paths.
5. Enumerate the official active standards, active handbooks, and TM catalogues.
6. Compare catalogue entries with files extracted from the archives.
7. Download missing or newer publisher attachments individually.
8. Exclude superseded material by default but support an explicit archival mode.
9. Produce a manifest and reviewable dry-run report before replacing the active corpus.

## 4. Proposed implementation boundary

The acquisition code should model publisher capability explicitly:

```text
CCSDS
  authority: stable active-and-obsolete HTML catalogue
  bulk archive: none found
  sync: stable detail pages -> current PDF attachments

ECSS
  authority: active standards / handbooks / TM catalogues
  bulk archive: active standards PDF ZIP + handbook snapshot ZIP
  sync: catalogue reconciliation -> missing/newer attachments
```

Keep acquisition separate from ingestion:

```text
discover -> plan/dry-run -> download -> verify -> stage -> approve manifest
                                                       |
                                                       v
                                  extract -> validate -> index
```

This separation permits a user to inspect licences and the exact file set before download, and permits ingestion to remain fully offline after acquisition.

## 5. Recommendation

Implement the work in this order:

1. Add a PDF Inspector extractor adapter and corpus benchmark; do not change the default extractor until the benchmark passes.
2. Add an ECSS bulk bootstrap command using the official standards and handbook archives, with licence acknowledgement and safe ZIP extraction.
3. Add ECSS catalogue reconciliation for newer handbooks and current TMs.
4. Add a CCSDS catalogue synchroniser based on the officially supported stable publication catalogue and detail URLs.
5. Add scheduled or manual `--check` mode that reports upstream changes without downloading them.

Do not add a generic “crawl everything” mode. Publisher-specific adapters make the supported source, access rules, metadata, and failure conditions reviewable.
