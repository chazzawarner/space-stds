import json
from pathlib import Path

import pytest

from space_stds.domain import IngestRequest, InvalidSourceError
from space_stds.service import StandardsService
from tests.pdf_factory import write_text_pdf


def test_manifest_rebuilds_searchable_corpus_atomically(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_text_pdf(corpus / "ccsds.pdf", [["2.1 Link", "The link shall report lock status."]])
    write_text_pdf(corpus / "ecss.pdf", [["4.1 Test", "The test shall record objective evidence."]])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "source": "CCSDS",
                        "document_id": "CCSDS 777.0-B-1",
                        "title": "Synthetic Link Standard",
                        "revision": "1",
                        "status": "active",
                        "official_url": "https://ccsds.org/example/777x0b1.pdf",
                        "file": "ccsds.pdf",
                    },
                    {
                        "source": "ECSS",
                        "document_id": "ECSS-E-ST-77C",
                        "title": "Synthetic Test Standard",
                        "revision": "1",
                        "status": "active",
                        "official_url": "https://ecss.nl/example/ecss-e-st-77c.pdf",
                        "file": "ecss.pdf",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    service = StandardsService(tmp_path / "index.db", corpus)

    outcome = service.ingest_manifest(manifest)

    assert outcome.indexed_documents == 2
    assert outcome.indexed_passages == 2
    assert service.search("lock status")[0].source == "CCSDS"
    assert service.search("objective evidence")[0].source == "ECSS"


def test_failed_manifest_keeps_previous_index_generation(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    original = corpus / "original.pdf"
    write_text_pdf(original, [["1.1 Baseline", "The baseline phrase shall remain searchable."]])
    malformed = corpus / "malformed.pdf"
    malformed.write_bytes(b"not a PDF")
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 100.0-B-1",
            title="Baseline",
            revision="1",
            status="active",
            official_url="https://ccsds.org/example/original.pdf",
            path=original,
        )
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "source": "CCSDS",
                        "document_id": "CCSDS 200.0-B-1",
                        "title": "Broken replacement",
                        "revision": "1",
                        "status": "active",
                        "official_url": "https://ccsds.org/example/malformed.pdf",
                        "file": "malformed.pdf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InvalidSourceError, match="Cannot read PDF"):
        service.ingest_manifest(manifest)

    assert service.search("baseline phrase")[0].document_id == "CCSDS 100.0-B-1"
