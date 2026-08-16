from __future__ import annotations

import hashlib
import html
import json
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile, ZipInfo

from space_stds.domain import Corpus, DocumentStatus, InvalidSourceError

_CCSDS_CATALOGUE_BASE = "https://ccsds.org/publications/ccsdsallpubs/"
_EXTRACTION_RECEIPT = ".space-stds-extraction.json"


@dataclass(frozen=True)
class OfficialDownload:
    source: Corpus
    document_id: str
    title: str
    kind: str
    revision: str
    published: str
    status: DocumentStatus
    official_url: str
    url: str

    @property
    def filename(self) -> str:
        return _safe_filename(self.url)


@dataclass(frozen=True)
class DownloadOutcome:
    path: Path
    unchanged: bool
    sha256: str
    size: int


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        self._href = next((value for name, value in attrs if name == "href"), None)
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


class _RestrictedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        super().__init__()
        self._hosts = {host, f"www.{host}"}

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in self._hosts:
            raise HTTPError(newurl, code, "Redirect left the official host", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_official(request: Request) -> Any:
    hostname = urlparse(request.full_url).hostname
    if hostname is None:
        raise ValueError(f"Official download URL has no host: {request.full_url}")
    canonical_host = hostname.removeprefix("www.")
    opener = build_opener(_RestrictedRedirectHandler(canonical_host))
    return opener.open(request, timeout=120)


def discover_ccsds_publications(
    page: str, *, book_types: set[str] | None = None
) -> list[OfficialDownload]:
    """Read the official catalogue data embedded in the CCSDS publications page."""
    marker = "const config ="
    start = page.find(marker)
    if start < 0:
        raise ValueError("CCSDS catalogue data was not found")
    object_start = page.find("{", start + len(marker))
    if object_start < 0:
        raise ValueError("CCSDS catalogue configuration was malformed")
    config, _ = json.JSONDecoder().raw_decode(page[object_start:])
    rows = config.get("data")
    if not isinstance(rows, list):
        raise ValueError("CCSDS catalogue did not contain publication rows")

    publications: list[OfficialDownload] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7 or not row[1]:
            continue
        kind = _plain_text(row[4])
        if book_types is not None and kind not in book_types:
            continue
        download_url = _first_link(row[1])
        if download_url is None or not _is_allowed_download(download_url, "ccsds.org", ".pdf"):
            continue
        detail_link = _first_link(row[2])
        official_url = urljoin(_CCSDS_CATALOGUE_BASE, detail_link or "")
        if not _is_ccsds_detail_url(official_url):
            continue
        publications.append(
            OfficialDownload(
                source="CCSDS",
                document_id=_plain_text(row[2]),
                title=_plain_text(row[3]),
                kind=kind,
                revision=_plain_text(row[5]),
                published=_plain_text(row[6]),
                status="obsolete" if kind == "Silver Book" else "active",
                official_url=official_url,
                url=download_url,
            )
        )
    return sorted(publications, key=lambda item: (item.document_id, item.url))


def discover_directory_downloads(
    page: str,
    *,
    base_url: str,
    suffixes: tuple[str, ...] = (".pdf", ".zip"),
) -> list[OfficialDownload]:
    """Read PDF or ZIP links from an official, simple directory index."""
    parser = _LinkParser()
    parser.feed(page)
    downloads: list[OfficialDownload] = []
    for href, label in parser.links:
        url = urljoin(base_url, href)
        path = urlparse(url).path
        suffix = next((value for value in suffixes if path.casefold().endswith(value)), None)
        if suffix is None or not _is_allowed_download(url, "escies.org", suffix):
            continue
        filename = unquote(html.unescape(path.rsplit("/", 1)[-1]))
        downloads.append(
            OfficialDownload(
                source="ECSS",
                document_id=filename.removesuffix(suffix),
                title=label or filename,
                kind="archive" if suffix == ".zip" else "document",
                revision="",
                published="",
                status="active",
                official_url=url,
                url=url,
            )
        )
    return sorted(downloads, key=lambda item: item.url)


def download_official(
    item: OfficialDownload,
    destination: Path,
    *,
    opener: Callable[[Request], Any] = _open_official,
    max_bytes: int = 1024 * 1024 * 1024,
    replace_existing: bool = False,
) -> DownloadOutcome:
    """Download one allowlisted official file through an atomic partial file."""
    suffix = Path(urlparse(item.url).path).suffix.casefold()
    expected_host = "ccsds.org" if item.source == "CCSDS" else "escies.org"
    if suffix not in {".pdf", ".zip"} or not _is_allowed_download(item.url, expected_host, suffix):
        raise ValueError(f"Unsupported official download URL: {item.url}")
    filename = item.filename
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    existing_digest: str | None = None
    if target.exists():
        existing_digest, size = _fingerprint(target, suffix=suffix, max_bytes=max_bytes)
        if not replace_existing:
            return DownloadOutcome(target, True, existing_digest, size)

    partial = destination / f"{filename}.part"
    request = Request(item.url, headers={"User-Agent": "space-stds/0.1 (+local corpus setup)"})
    try:
        with opener(request) as response, partial.open("wb") as output:
            final_url = response.geturl()
            if not _is_allowed_download(final_url, expected_host, suffix):
                raise ValueError(f"Official download redirected to an unsupported URL: {final_url}")
            content_type = response.headers.get_content_type()
            allowed_types = {
                ".pdf": {"application/pdf", "application/octet-stream"},
                ".zip": {
                    "application/zip",
                    "application/x-zip-compressed",
                    "application/octet-stream",
                },
            }
            if content_type not in allowed_types[suffix]:
                raise ValueError(f"Unexpected content type {content_type!r} for {item.url}")
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise ValueError(f"Download exceeds {max_bytes} bytes: {item.url}")
                output.write(block)
        digest, size = _fingerprint(partial, suffix=suffix, max_bytes=max_bytes)
        if existing_digest == digest:
            return DownloadOutcome(target, True, digest, size)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return DownloadOutcome(target, False, digest, size)


def extract_pdf_archive(
    archive: Path,
    destination: Path,
    *,
    max_members: int = 2_000,
    max_member_bytes: int = 250 * 1024 * 1024,
    max_total_bytes: int = 2 * 1024 * 1024 * 1024,
) -> list[Path]:
    """Validate and atomically extract a PDF-only ZIP archive."""
    archive = archive.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not archive.is_file():
        raise InvalidSourceError(f"Archive is not a file: {archive}")
    if destination.exists():
        raise InvalidSourceError(f"Extraction destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(archive) as bundle:
            members = _validated_pdf_members(
                bundle,
                max_members=max_members,
                max_member_bytes=max_member_bytes,
                max_total_bytes=max_total_bytes,
            )
            with tempfile.TemporaryDirectory(
                prefix=".space-stds-extract-", dir=destination.parent
            ) as stage_directory:
                stage_root = Path(stage_directory) / destination.name
                stage_root.mkdir()
                extracted_relatives: list[Path] = []
                extracted_hashes: dict[str, str] = {}
                total_extracted = 0
                for info, relative in members:
                    target = stage_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    size = 0
                    signature = b""
                    digest = hashlib.sha256()
                    with bundle.open(info) as source, target.open("wb") as output:
                        while block := source.read(1024 * 1024):
                            if not signature:
                                signature = block[:5]
                            size += len(block)
                            if size > max_member_bytes:
                                raise InvalidSourceError(
                                    f"Archive member exceeds size limit: {info.filename}"
                                )
                            output.write(block)
                            digest.update(block)
                    if signature != b"%PDF-":
                        raise InvalidSourceError(f"Archive member is not a PDF: {info.filename}")
                    total_extracted += size
                    if total_extracted > max_total_bytes:
                        raise InvalidSourceError(
                            f"Archive exceeds {max_total_bytes} uncompressed bytes"
                        )
                    extracted_relatives.append(relative)
                    extracted_hashes[relative.as_posix()] = digest.hexdigest()
                receipt = {
                    "schema_version": 1,
                    "archive_sha256": _hash_file(archive),
                    "members": extracted_hashes,
                }
                (stage_root / _EXTRACTION_RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n")
                os.replace(stage_root, destination)
    except BadZipFile as exc:
        raise InvalidSourceError(f"Cannot read ZIP archive {archive.name}: {exc}") from exc
    return [destination / relative for relative in extracted_relatives]


def _validated_pdf_members(
    bundle: ZipFile,
    *,
    max_members: int,
    max_member_bytes: int,
    max_total_bytes: int,
) -> list[tuple[ZipInfo, Path]]:
    entries = bundle.infolist()
    for info in entries:
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidSourceError(f"Archive member is a symbolic link: {info.filename}")
    files = [info for info in entries if not info.is_dir()]
    if not files:
        raise InvalidSourceError("Archive contains no files")
    if len(files) > max_members:
        raise InvalidSourceError(f"Archive contains more than {max_members} files")
    total_bytes = 0
    seen: set[str] = set()
    validated: list[tuple[ZipInfo, Path]] = []
    for info in files:
        if info.flag_bits & 0x1:
            raise InvalidSourceError(f"Encrypted archive member is not supported: {info.filename}")
        if "\\" in info.filename:
            raise InvalidSourceError(f"Archive member has an unsafe path: {info.filename}")
        member = PurePosixPath(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise InvalidSourceError(f"Archive member has an unsafe path: {info.filename}")
        if member.suffix.casefold() != ".pdf":
            raise InvalidSourceError(f"Archive member is not a PDF: {info.filename}")
        if info.file_size > max_member_bytes:
            raise InvalidSourceError(f"Archive member exceeds size limit: {info.filename}")
        total_bytes += info.file_size
        if total_bytes > max_total_bytes:
            raise InvalidSourceError(f"Archive exceeds {max_total_bytes} uncompressed bytes")
        relative = Path(*member.parts)
        identity = relative.as_posix().casefold()
        if identity in seen:
            raise InvalidSourceError(f"Archive contains a duplicate path: {info.filename}")
        seen.add(identity)
        validated.append((info, relative))
    return validated


def _fingerprint(path: Path, *, suffix: str, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    signature = b""
    with path.open("rb") as downloaded:
        while block := downloaded.read(1024 * 1024):
            if not signature:
                signature = block[:5]
            size += len(block)
            if size > max_bytes:
                raise ValueError(f"File exceeds {max_bytes} bytes: {path}")
            digest.update(block)
    if suffix == ".pdf" and signature != b"%PDF-":
        raise ValueError(f"File is not a PDF: {path}")
    if suffix == ".zip" and not signature.startswith(b"PK"):
        raise ValueError(f"File is not a ZIP archive: {path}")
    return digest.hexdigest(), size


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _first_link(fragment: object) -> str | None:
    fragment = _catalogue_cell(fragment)
    parser = _LinkParser()
    parser.feed(html.unescape(fragment))
    return parser.links[0][0] if parser.links else None


def _plain_text(fragment: object) -> str:
    fragment = _catalogue_cell(fragment)
    parser = _LinkParser()
    parser.feed(html.unescape(fragment))
    linked_text = " ".join(text for _, text in parser.links if text)
    if linked_text:
        return linked_text.strip()
    return html.unescape(fragment).strip()


def _catalogue_cell(value: object) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _is_allowed_download(url: str, host: str, suffix: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {host, f"www.{host}"}
        and parsed.path.casefold().endswith(suffix)
    )


def _safe_filename(url: str) -> str:
    filename = unquote(Path(urlparse(url).path).name)
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ValueError(f"Download URL has an unsafe filename: {url}")
    return filename


def _is_ccsds_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"ccsds.org", "www.ccsds.org"}
        and parsed.path.startswith("/publications/ccsdsallpubs/entry/")
    )
