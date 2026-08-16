from io import BytesIO
from pathlib import Path

import pytest

from space_stds.acquisition import (
    OfficialDownload,
    discover_ccsds_publications,
    discover_directory_downloads,
    download_official,
)


class _Headers:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _Response(BytesIO):
    def __init__(self, body: bytes, *, url: str, content_type: str) -> None:
        super().__init__(body)
        self._url = url
        self.headers = _Headers(content_type)

    def geturl(self) -> str:
        return self._url


def test_user_can_discover_ccsds_publications_and_filter_book_types() -> None:
    page = r"""
    <script>
    const config = {"data":[
      ["","<a href=\"https:\/\/ccsds.org\/files\/131x0b6.pdf\">PDF<\/a>",
       "<a href=\"\/publications\/ccsdsallpubs\/entry\/1\/\">CCSDS 131.0-B-6<\/a>",
       "TM Synchronization","Blue Book","6","October 2023"],
      ["","<a href=\"https:\/\/ccsds.org\/files\/130x0g4.pdf\">PDF<\/a>",
       "<a href=\"\/publications\/ccsdsallpubs\/entry\/2\/\">CCSDS 130.0-G-4<\/a>",
       "Overview","Green Book","4","April 2023"]
    ]};
    </script>
    """

    publications = discover_ccsds_publications(page, book_types={"Blue Book"})

    assert len(publications) == 1
    assert publications[0].document_id == "CCSDS 131.0-B-6"
    assert publications[0].title == "TM Synchronization"
    assert publications[0].published == "October 2023"
    assert publications[0].status == "active"
    assert publications[0].official_url.endswith("/ccsdsallpubs/entry/1/")
    assert publications[0].url == "https://ccsds.org/files/131x0b6.pdf"


def test_ccsds_catalogue_parser_tolerates_non_string_metadata_cells() -> None:
    page = r"""
    <script>
    const config = {"data":[
      ["","<a href=\"https:\/\/ccsds.org\/files\/131x0b6.pdf\">PDF<\/a>",
       "<a href=\"\/publications\/ccsdsallpubs\/entry\/1\/\">CCSDS 131.0-B-6<\/a>",
       131,"Blue Book",6,2026]
    ]};
    </script>
    """

    publications = discover_ccsds_publications(page)

    assert publications[0].title == "131"
    assert publications[0].revision == "6"
    assert publications[0].published == "2026"


def test_user_can_discover_only_supported_files_from_an_official_directory() -> None:
    page = """
    <a href="/ftp/ecss.nl/">Parent Directory</a>
    <a href="Active%20ECSS%20Standards_PDF-files.zip">Standards PDF archive</a>
    <a href="ECSS-E-TM-10-10A.pdf">Technical memorandum</a>
    <a href="ECSS-E-TM-10-10A.doc">Word file</a>
    <a href="https://example.com/untrusted.pdf">Other host</a>
    """

    downloads = discover_directory_downloads(
        page,
        base_url="https://escies.org/ftp/ecss.nl/ECSS/",
    )

    assert [item.document_id for item in downloads] == [
        "Active ECSS Standards_PDF-files",
        "ECSS-E-TM-10-10A",
    ]


def test_user_can_download_a_valid_pdf_atomically(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="CCSDS",
        document_id="CCSDS 131.0-B-6",
        title="TM Synchronization",
        kind="Blue Book",
        revision="6",
        published="October 2023",
        status="active",
        official_url="https://ccsds.org/publications/ccsdsallpubs/entry/1/",
        url="https://ccsds.org/files/131x0b6.pdf",
    )

    outcome = download_official(
        item,
        tmp_path,
        opener=lambda _request: _Response(
            b"%PDF-1.7\nsynthetic",
            url=item.url,
            content_type="application/pdf",
        ),
    )

    assert outcome.path == tmp_path / "131x0b6.pdf"
    assert outcome.path.read_bytes().startswith(b"%PDF-")
    assert outcome.sha256
    assert outcome.size == len(b"%PDF-1.7\nsynthetic")
    assert not (tmp_path / "131x0b6.pdf.part").exists()


def test_invalid_download_is_rejected_without_leaving_a_partial_file(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="ECSS",
        document_id="ECSS archive",
        title="Active standards",
        kind="archive",
        revision="",
        published="",
        status="active",
        official_url="https://escies.org/files/active.zip",
        url="https://escies.org/files/active.zip",
    )

    with pytest.raises(ValueError, match="not a ZIP"):
        download_official(
            item,
            tmp_path,
            opener=lambda _request: _Response(
                b"not a zip",
                url=item.url,
                content_type="application/zip",
            ),
        )

    assert not (tmp_path / "active.zip").exists()
    assert not (tmp_path / "active.zip.part").exists()


def test_encoded_path_separator_cannot_escape_the_destination(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="CCSDS",
        document_id="CCSDS 131.0-B-6",
        title="TM Synchronization",
        kind="Blue Book",
        revision="6",
        published="October 2023",
        status="active",
        official_url="https://ccsds.org/publications/ccsdsallpubs/entry/1/",
        url="https://ccsds.org/files/nested%2Fescape.pdf",
    )

    with pytest.raises(ValueError, match="filename"):
        download_official(item, tmp_path, opener=lambda _request: BytesIO(b"%PDF-test"))


def test_cross_host_redirect_is_rejected(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="CCSDS",
        document_id="CCSDS 131.0-B-6",
        title="TM Synchronization",
        kind="Blue Book",
        revision="6",
        published="October 2023",
        status="active",
        official_url="https://ccsds.org/publications/ccsdsallpubs/entry/1/",
        url="https://ccsds.org/files/131x0b6.pdf",
    )

    with pytest.raises(ValueError, match="redirected"):
        download_official(
            item,
            tmp_path,
            opener=lambda _request: _Response(
                b"%PDF-test",
                url="https://example.com/131x0b6.pdf",
                content_type="application/pdf",
            ),
        )


def test_corrupt_existing_file_is_not_reported_as_unchanged(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="CCSDS",
        document_id="CCSDS 131.0-B-6",
        title="TM Synchronization",
        kind="Blue Book",
        revision="6",
        published="October 2023",
        status="active",
        official_url="https://ccsds.org/publications/ccsdsallpubs/entry/1/",
        url="https://ccsds.org/files/131x0b6.pdf",
    )
    (tmp_path / item.filename).write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="not a PDF"):
        download_official(item, tmp_path)


def test_refresh_replaces_an_existing_file_only_when_content_changes(tmp_path: Path) -> None:
    item = OfficialDownload(
        source="CCSDS",
        document_id="CCSDS 131.0-B-6",
        title="TM Synchronization",
        kind="Blue Book",
        revision="6",
        published="October 2023",
        status="active",
        official_url="https://ccsds.org/publications/ccsdsallpubs/entry/1/",
        url="https://ccsds.org/files/131x0b6.pdf",
    )
    target = tmp_path / item.filename
    target.write_bytes(b"%PDF-old")

    outcome = download_official(
        item,
        tmp_path,
        replace_existing=True,
        opener=lambda _request: _Response(
            b"%PDF-new",
            url=item.url,
            content_type="application/pdf",
        ),
    )

    assert outcome.unchanged is False
    assert target.read_bytes() == b"%PDF-new"
