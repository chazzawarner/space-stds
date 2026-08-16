# Corpus policy

## Repository boundary

This repository may contain source code, tests using synthetic fixtures,
document metadata that is independently public, and documentation.

It must not contain:

- CCSDS or ECSS source documents;
- extracted text, OCR output, search indexes, embeddings, or caches;
- authenticated SANA responses, credentials, contact data, or logs;
- employer documents, configuration, paths, hostnames, or internal questions.

The ignore rules are defence in depth, not permission to place protected data
inside the checkout. Configure corpus and data directories outside the checkout.

## CCSDS

Use official, published CCSDS sources. Preserve the document identifier, issue,
status, official URL, content hash, and ingestion time. Local short quotations
must retain attribution. Do not publish or distribute a full-text or derived
corpus without confirming permission with CCSDS.

## ECSS

Acquire documents through an authorised user or employer route. Do not automate
the ECSS registration or acceptance flow. Do not publish source documents or
derived full text. Confirm that the employer is an ECSS member, contractor,
subcontractor, or otherwise licensed before wider internal deployment.

## SANA

Use only an official, authenticated, read-only API after its terms, schema, and
rate limits have been reviewed. Keep credentials in the environment or an
approved credential store. Exclude personal fields by default. Do not scrape
undocumented HTML as a production interface.

## Removal

Stopping the server does not remove local source material. To remove the local
index, delete `index.sqlite3`, `index.sqlite3-shm`, and `index.sqlite3-wal` from
the configured data directory. Remove source documents according to employer
records policy.

