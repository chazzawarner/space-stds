import json
from pathlib import Path

import pytest

from space_stds.cli import main
from tests.pdf_factory import write_text_pdf


def test_cli_ingests_manifest_and_filters_diagnostic_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_text_pdf(corpus / "active.pdf", [["2.1 Rule", "Shared term active wording."]])
    write_text_pdf(corpus / "old.pdf", [["2.1 Rule", "Shared term superseded wording."]])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "source": "CCSDS",
                        "document_id": "CCSDS 300.0-B-2",
                        "title": "Active",
                        "revision": "2",
                        "status": "active",
                        "official_url": "https://ccsds.org/example/active.pdf",
                        "file": "active.pdf",
                    },
                    {
                        "source": "CCSDS",
                        "document_id": "CCSDS 300.0-B-2",
                        "title": "Old",
                        "revision": "1",
                        "status": "superseded",
                        "official_url": "https://ccsds.org/example/old.pdf",
                        "file": "old.pdf",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SPACE_STDS_DATA_DIR", str(data))
    monkeypatch.setenv("SPACE_STDS_CORPUS_DIR", str(corpus))

    assert main(["ingest-manifest", str(manifest)]) == 0
    ingest_output = json.loads(capsys.readouterr().out)
    assert ingest_output["indexed_documents"] == 2

    assert main(["search", "shared term", "--status", "active"]) == 0
    search_output = json.loads(capsys.readouterr().out)
    assert [hit["revision"] for hit in search_output] == ["2"]

    assert main(["document", "CCSDS 300.0-B-2", "--revision", "2"]) == 0
    document_output = json.loads(capsys.readouterr().out)
    assert document_output["status"] == "active"
    assert document_output["passages"] == 1
