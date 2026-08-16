import hashlib
import json
import stat
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from space_stds.acquisition import extract_pdf_archive
from space_stds.corpus_setup import prepare_acquired_corpus
from space_stds.domain import InvalidSourceError
from space_stds.manifest import load_manifest


def test_user_can_extract_a_pdf_archive_beneath_a_new_destination(tmp_path: Path) -> None:
    archive = tmp_path / "standards.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("standards/ECSS-E-ST-10C-Rev1.pdf", b"%PDF-synthetic")
        bundle.writestr("standards/ECSS-Q-ST-80C-Rev2.pdf", b"%PDF-synthetic")

    extracted = extract_pdf_archive(archive, tmp_path / "extracted")

    assert [path.relative_to(tmp_path / "extracted").as_posix() for path in extracted] == [
        "standards/ECSS-E-ST-10C-Rev1.pdf",
        "standards/ECSS-Q-ST-80C-Rev2.pdf",
    ]


def test_archive_path_traversal_is_rejected_before_any_file_is_extracted(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.pdf", b"%PDF-synthetic")

    destination = tmp_path / "extracted"
    with pytest.raises(InvalidSourceError, match="unsafe path"):
        extract_pdf_archive(archive, destination)

    assert not destination.exists()
    assert not (tmp_path / "escape.pdf").exists()


def test_archive_directory_shaped_symbolic_link_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe-link.zip"
    link = ZipInfo("linked-directory/")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(link, "target")

    with pytest.raises(InvalidSourceError, match="symbolic link"):
        extract_pdf_archive(archive, tmp_path / "extracted")


def test_acquisition_manifest_can_prepare_archives_and_generate_ingestion_manifest(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    ccsds_dir = corpus / "ccsds"
    ecss_dir = corpus / "ecss"
    ccsds_dir.mkdir(parents=True)
    ecss_dir.mkdir()
    ccsds_pdf = ccsds_dir / "131x0b6.pdf"
    ccsds_pdf.write_bytes(b"%PDF-synthetic")
    archive = ecss_dir / "active.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("ECSS-E-ST-10C-Rev.1(15February2017).pdf", b"%PDF-synthetic")

    acquisition = corpus / "acquisition-manifest.json"
    acquisition.write_text(
        json.dumps(
            {
                "mode": "acquisition",
                "downloads": [
                    {
                        "source": "CCSDS",
                        "document_id": "CCSDS 131.0-B-6",
                        "title": "TM Synchronization and Channel Coding",
                        "kind": "Blue Book",
                        "revision": "6",
                        "published": "October 2023",
                        "status": "active",
                        "official_url": "https://ccsds.org/publications/ccsdsallpubs/entry/1/",
                        "url": "https://ccsds.org/files/131x0b6.pdf",
                        "local_file": "ccsds/131x0b6.pdf",
                        "sha256": hashlib.sha256(ccsds_pdf.read_bytes()).hexdigest(),
                        "size": ccsds_pdf.stat().st_size,
                    },
                    {
                        "source": "ECSS",
                        "document_id": "active",
                        "title": "Active standards",
                        "kind": "archive",
                        "revision": "",
                        "published": "",
                        "status": "active",
                        "official_url": "https://escies.org/ftp/ecss.nl/ECSS/active.zip",
                        "url": "https://escies.org/ftp/ecss.nl/ECSS/active.zip",
                        "local_file": "ecss/active.zip",
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "size": archive.stat().st_size,
                    },
                ],
            }
        )
    )
    output = corpus / "ingestion-manifest.generated.json"

    outcome = prepare_acquired_corpus(acquisition, corpus, output)
    generated = json.loads(output.read_text())

    assert outcome.documents == 2
    assert outcome.inferred_metadata == 1
    assert not outcome.ready_for_ingestion
    assert generated["metadata_review_required"] is True
    assert [item["document_id"] for item in generated["documents"]] == [
        "CCSDS 131.0-B-6",
        "ECSS-E-ST-10C",
    ]
    assert generated["documents"][1]["revision"] == "1"
    assert (corpus / generated["documents"][1]["file"]).is_file()
    with pytest.raises(InvalidSourceError, match="exactly schema_version and documents"):
        load_manifest(output, corpus)

    second = prepare_acquired_corpus(acquisition, corpus, output)
    assert second == outcome

    extracted_pdf = corpus / generated["documents"][1]["file"]
    extracted_pdf.write_bytes(b"%PDF-tampered")
    with pytest.raises(InvalidSourceError, match="member hash has changed"):
        prepare_acquired_corpus(acquisition, corpus, output)
