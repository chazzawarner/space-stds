import sqlite3
from pathlib import Path

import pytest

from space_stds.domain import AmbiguousDocumentError, InvalidSourceError
from space_stds.service import IngestRequest, StandardsService
from tests.pdf_factory import write_text_pdf


def test_user_can_ingest_search_and_retrieve_a_cited_passage(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "131x0b5.pdf"
    write_text_pdf(
        source,
        [
            [
                "CCSDS 131.0-B-5",
                "4.2 Synchronization",
                "The transfer frame shall use an attached sync marker.",
            ],
            ["5.1 Coding", "The coding procedure shall preserve frame order."],
        ],
    )
    service = StandardsService(tmp_path / "index.db", corpus)

    outcome = service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 131.0-B-5",
            title="TM Synchronization and Channel Coding",
            revision="5",
            status="active",
            official_url="https://ccsds.org/example/131x0b5.pdf",
            path=source,
        )
    )
    hits = service.search("attached sync marker")
    passage = service.get_passage(hits[0].passage_id)

    assert outcome.indexed_passages == 2
    assert hits[0].document_id == "CCSDS 131.0-B-5"
    assert hits[0].revision == "5"
    assert hits[0].page == 1
    assert hits[0].section == "4.2 Synchronization"
    assert "attached sync marker" in hits[0].excerpt
    assert passage.official_url == "https://ccsds.org/example/131x0b5.pdf"
    assert passage.content_hash == outcome.content_hash


def test_search_accepts_a_natural_language_question(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "131x0b6.pdf"
    write_text_pdf(
        source,
        [["2.2.5 Synchronization", "A frame is synchronized using an attached sync marker."]],
    )
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 131.0-B-6",
            title="TM Synchronization and Channel Coding",
            revision="6",
            status="active",
            official_url="https://ccsds.org/example/131x0b6.pdf",
            path=source,
        )
    )

    hits = service.search("What is an attached sync marker?", source="CCSDS")

    assert hits[0].document_id == "CCSDS 131.0-B-6"


def test_search_ranks_a_partial_domain_match_when_one_question_term_is_absent(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "standard.pdf"
    write_text_pdf(
        source,
        [
            ["2.1 Synchronization", "The marker synchronizes a transfer frame."],
            ["2.2 Budget", "The downlink budget shall be recorded."],
        ],
    )
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 999.0-B-1",
            title="Synthetic Standard",
            revision="1",
            status="active",
            official_url="https://ccsds.org/example/999x0b1.pdf",
            path=source,
        )
    )

    hits = service.search("Which marker synchronizes a downlink transfer frame?")

    assert hits[0].section == "2.1 Synchronization"


def test_search_uses_document_title_to_disambiguate_shared_protocol_terms(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    service = StandardsService(tmp_path / "index.db", corpus)
    documents = (
        (
            "aos.pdf",
            "CCSDS 732.0-B-5",
            "AOS Space Data Link Protocol",
            "The master channel identifier contains the channel address.",
        ),
        (
            "tm.pdf",
            "CCSDS 132.0-B-3",
            "TM Space Data Link Protocol",
            "The master channel identifier contains the master channel identifier fields.",
        ),
    )
    for filename, document_id, title, content in documents:
        source = corpus / filename
        write_text_pdf(source, [["3.1 Master Channel Identifier", content]])
        service.ingest(
            IngestRequest(
                source="CCSDS",
                document_id=document_id,
                title=title,
                revision="1",
                status="active",
                official_url=f"https://ccsds.org/example/{filename}",
                path=source,
            )
        )

    hits = service.search("What does the AOS master channel identifier contain?")

    assert hits[0].document_id == "CCSDS 732.0-B-5"


def test_search_prefers_passage_covering_more_distinct_question_terms(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    service = StandardsService(tmp_path / "index.db", corpus)
    documents = (
        (
            "tc.pdf",
            "CCSDS 232.0-B-4",
            "TC Space Data Link Protocol",
            "TC transfer frames transfer TC frames through the TC service.",
        ),
        (
            "tm.pdf",
            "CCSDS 132.0-B-3",
            "TM Space Data Link Protocol",
            "TM and TC transfer frames are distinguishable by their synchronization markers.",
        ),
    )
    for filename, document_id, title, content in documents:
        source = corpus / filename
        write_text_pdf(source, [["4.1 Transfer Frames", content]])
        service.ingest(
            IngestRequest(
                source="CCSDS",
                document_id=document_id,
                title=title,
                revision="1",
                status="active",
                official_url=f"https://ccsds.org/example/{filename}",
                path=source,
            )
        )

    hits = service.search("How are TM transfer frames distinguished from TC transfer frames?")

    assert hits[0].document_id == "CCSDS 132.0-B-3"


def test_broad_search_diversifies_initial_results_across_documents(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    service = StandardsService(tmp_path / "index.db", corpus)
    for filename, document_id, pages in (
        (
            "primary.pdf",
            "CCSDS 100.0-B-1",
            [
                ["2.1 Alpha", "Shared transfer frame service alpha."],
                ["2.2 Beta", "Shared transfer frame service beta."],
                ["2.3 Gamma", "Shared transfer frame service gamma."],
            ],
        ),
        (
            "related.pdf",
            "CCSDS 200.0-B-1",
            [["3.1 Related", "A related transfer frame service."]],
        ),
    ):
        source = corpus / filename
        write_text_pdf(source, pages)
        service.ingest(
            IngestRequest(
                source="CCSDS",
                document_id=document_id,
                title="Transfer Frame Standard",
                revision="1",
                status="active",
                official_url=f"https://ccsds.org/example/{filename}",
                path=source,
            )
        )

    hits = service.search("shared transfer frame service", limit=2)

    assert {hit.document_id for hit in hits} == {"CCSDS 100.0-B-1", "CCSDS 200.0-B-1"}


def test_search_abstains_when_only_generic_question_terms_match(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "standard.pdf"
    write_text_pdf(source, [["2.1 Requirements", "Protocol requirements are specified here."]])
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 999.0-B-1",
            title="Synthetic protocol",
            revision="1",
            status="active",
            official_url="https://ccsds.org/example/standard.pdf",
            path=source,
        )
    )

    assert service.search("What astronaut nutrition requirements are specified?") == []


def test_search_returns_only_passages_with_a_citable_section(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "standard.pdf"
    write_text_pdf(
        source,
        [
            ["Interface requirements and architecture"],
            ["4.2 Interface requirements", "The customer shall define each interface."],
        ],
    )
    service = StandardsService(tmp_path / "index.db", corpus)
    service.ingest(
        IngestRequest(
            source="ECSS",
            document_id="ECSS-E-ST-00C",
            title="Interface requirements",
            revision="1",
            status="active",
            official_url="https://ecss.nl/example.pdf",
            path=source,
        )
    )

    hits = service.search("interface requirements")

    assert [hit.section for hit in hits] == ["4.2 Interface requirements"]


def test_opening_an_earlier_index_migrates_search_metadata_without_data_loss(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    database = tmp_path / "index.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                document_key TEXT PRIMARY KEY, source TEXT NOT NULL,
                document_id TEXT NOT NULL, title TEXT NOT NULL, revision TEXT NOT NULL,
                status TEXT NOT NULL, official_url TEXT NOT NULL, source_path TEXT NOT NULL,
                content_hash TEXT NOT NULL, ingested_at TEXT NOT NULL
            );
            CREATE TABLE passages (
                passage_id TEXT PRIMARY KEY, document_key TEXT NOT NULL,
                page INTEGER NOT NULL, section TEXT, content TEXT NOT NULL
            );
            INSERT INTO documents VALUES (
                'document-key', 'CCSDS', 'CCSDS 999.0-B-1', 'Legacy Search Standard',
                '1', 'active', 'https://ccsds.org/example.pdf', '/local/example.pdf',
                'hash', '2026-08-16T00:00:00+00:00'
            );
            INSERT INTO passages VALUES (
                'passage-id', 'document-key', 4, '2.1 Legacy search',
                'The migrated index shall preserve searchable passages.'
            );
            """
        )

    service = StandardsService(database, corpus)

    hits = service.search("migrated searchable passages")
    assert [(hit.document_id, hit.page) for hit in hits] == [("CCSDS 999.0-B-1", 4)]


def test_reingesting_unchanged_document_is_idempotent(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "standard.pdf"
    write_text_pdf(source, [["2.1 Scope", "The service shall preserve ordering."]])
    service = StandardsService(tmp_path / "index.db", corpus)
    request = IngestRequest(
        source="CCSDS",
        document_id="CCSDS 999.0-B-1",
        title="Synthetic Standard",
        revision="1",
        status="active",
        official_url="https://ccsds.org/example/999x0b1.pdf",
        path=source,
    )

    first = service.ingest(request)
    second = service.ingest(request)

    assert first.unchanged is False
    assert second.unchanged is True
    assert second.indexed_passages == first.indexed_passages
    assert len(service.search("preserve ordering")) == 1


def test_ingest_rejects_file_outside_authorised_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    outside = tmp_path / "outside.pdf"
    write_text_pdf(outside, [["1.1 Scope", "This file is not authorised."]])
    service = StandardsService(tmp_path / "index.db", corpus)

    with pytest.raises(InvalidSourceError, match="beneath configured corpus root"):
        service.ingest(
            IngestRequest(
                source="ECSS",
                document_id="ECSS-E-ST-00C",
                title="Outside",
                revision="1",
                status="active",
                official_url="https://ecss.nl/example.pdf",
                path=outside,
            )
        )


def test_ingest_reports_malformed_pdf_without_modifying_index(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    malformed = corpus / "malformed.pdf"
    malformed.write_bytes(b"not a PDF")
    service = StandardsService(tmp_path / "index.db", corpus)

    with pytest.raises(InvalidSourceError, match="Cannot read PDF"):
        service.ingest(
            IngestRequest(
                source="CCSDS",
                document_id="CCSDS 000.0-B-0",
                title="Malformed",
                revision="0",
                status="draft",
                official_url="https://ccsds.org/example/malformed.pdf",
                path=malformed,
            )
        )

    assert service.search("malformed") == []


def test_document_lookup_requires_revision_when_multiple_editions_exist(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    service = StandardsService(tmp_path / "index.db", corpus)
    for revision, status in (("1", "superseded"), ("2", "active")):
        source = corpus / f"standard-r{revision}.pdf"
        write_text_pdf(source, [["3.1 Requirement", f"Revision {revision} common phrase."]])
        service.ingest(
            IngestRequest(
                source="ECSS",
                document_id="ECSS-E-ST-99C",
                title="Synthetic Editions",
                revision=revision,
                status=status,
                official_url=f"https://ecss.nl/standard-r{revision}.pdf",
                path=source,
            )
        )

    with pytest.raises(AmbiguousDocumentError, match="Specify revision"):
        service.get_document("ECSS-E-ST-99C")

    document = service.get_document("ECSS-E-ST-99C", revision="2")
    assert document.revision == "2"
    assert document.status == "active"
    assert document.passages == 1

    active_hits = service.search("common phrase", source="ECSS", status="active")
    assert [hit.revision for hit in active_hits] == ["2"]


def test_numbered_sections_on_same_page_are_indexed_separately(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "sections.pdf"
    write_text_pdf(
        source,
        [
            [
                "4.1 Acquisition",
                "The receiver shall acquire the carrier.",
                "4.2 Tracking",
                "The receiver shall track the carrier.",
            ]
        ],
    )
    service = StandardsService(tmp_path / "index.db", corpus)

    outcome = service.ingest(
        IngestRequest(
            source="CCSDS",
            document_id="CCSDS 400.0-B-1",
            title="Section extraction",
            revision="1",
            status="active",
            official_url="https://ccsds.org/example/sections.pdf",
            path=source,
        )
    )

    assert outcome.indexed_passages == 2
    assert service.search("acquire carrier")[0].section == "4.1 Acquisition"
    assert service.search("track carrier")[0].section == "4.2 Tracking"
