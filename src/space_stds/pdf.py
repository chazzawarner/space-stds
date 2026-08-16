from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from space_stds.domain import InvalidSourceError

_SECTION = re.compile(r"^(?P<number>\d+(?:\.\d+)+)\s+(?P<title>\S.*)$")
_SPACE = re.compile(r"[ \t]+")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+")
_INLINE_SECTION_BODY = re.compile(
    r"^(?P<section>\d+(?:\.\d+)+\s+.+?)\s+"
    r"(?P<body>(?:The|A|An)\s+.+\bshall\b.*)$"
)

PdfBackend = Literal["pypdf", "pdf-inspector"]


@dataclass(frozen=True, slots=True)
class ExtractedPassage:
    page: int
    section: str | None
    content: str


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    passages: tuple[ExtractedPassage, ...]
    backend: PdfBackend
    page_count: int
    pages_needing_ocr: tuple[int, ...]
    pages_with_tables: tuple[int, ...] = ()
    pages_with_columns: tuple[int, ...] = ()


def extract_pdf(
    path: Path,
    *,
    backend: PdfBackend | str = "pypdf",
    max_pages: int = 5_000,
) -> ExtractionResult:
    if backend == "pypdf":
        return _extract_with_pypdf(path, max_pages=max_pages)
    if backend == "pdf-inspector":
        return _extract_with_pdf_inspector(path, max_pages=max_pages)
    raise InvalidSourceError(f"Unsupported PDF backend: {backend}")


def _extract_with_pypdf(path: Path, *, max_pages: int) -> ExtractionResult:
    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError, ValueError) as exc:
        raise InvalidSourceError(f"Cannot read PDF {path.name}: {exc}") from exc

    if len(reader.pages) > max_pages:
        raise InvalidSourceError(f"PDF has {len(reader.pages)} pages; limit is {max_pages}")

    passages: list[ExtractedPassage] = []
    pages_needing_ocr: list[int] = []
    current_section: str | None = None
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:  # pypdf plugins can surface several parser-specific errors
            message = f"Cannot extract page {page_number} from {path.name}: {exc}"
            raise InvalidSourceError(message) from exc
        lines = [_SPACE.sub(" ", line).strip() for line in raw_text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            pages_needing_ocr.append(page_number)
            continue
        current_section = _append_page_passages(passages, page_number, lines, current_section)

    if not passages:
        raise InvalidSourceError(
            f"PDF {path.name} contains no extractable text; run an authorised OCR step first"
        )
    return ExtractionResult(
        passages=tuple(passages),
        backend="pypdf",
        page_count=len(reader.pages),
        pages_needing_ocr=tuple(pages_needing_ocr),
    )


def _extract_with_pdf_inspector(path: Path, *, max_pages: int) -> ExtractionResult:
    try:
        import pdf_inspector
    except ImportError as exc:
        raise InvalidSourceError(
            "PDF Inspector is not installed; sync the pdf-inspector project extra"
        ) from exc
    try:
        extracted = pdf_inspector.extract_pages_markdown(str(path))
    except Exception as exc:
        raise InvalidSourceError(f"Cannot inspect PDF {path.name}: {exc}") from exc
    if len(extracted.pages) > max_pages:
        raise InvalidSourceError(f"PDF has {len(extracted.pages)} pages; limit is {max_pages}")

    passages: list[ExtractedPassage] = []
    current_section: str | None = None
    for page in extracted.pages:
        if page.needs_ocr:
            continue
        lines = _normalise_markdown_lines(page.markdown)
        if lines:
            current_section = _append_page_passages(passages, page.page + 1, lines, current_section)
    if not passages:
        raise InvalidSourceError(
            f"PDF {path.name} contains no reliable extractable text; "
            "run an authorised OCR step first"
        )
    return ExtractionResult(
        passages=tuple(passages),
        backend="pdf-inspector",
        page_count=len(extracted.pages),
        pages_needing_ocr=tuple(extracted.pages_needing_ocr),
        pages_with_tables=tuple(extracted.pages_with_tables),
        pages_with_columns=tuple(extracted.pages_with_columns),
    )


def _normalise_markdown_lines(markdown: str) -> list[str]:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = _MARKDOWN_HEADING.sub("", raw_line.strip())
        line = _SPACE.sub(" ", line).strip()
        if not line:
            continue
        inline = _INLINE_SECTION_BODY.match(line)
        if inline:
            lines.extend((inline.group("section"), inline.group("body")))
        else:
            lines.append(line)
    return lines


def _append_page_passages(
    passages: list[ExtractedPassage],
    page_number: int,
    lines: list[str],
    current_section: str | None,
) -> str | None:
    chunk_lines: list[str] = []
    chunk_section = current_section
    found_heading = False
    for line in lines:
        if _SECTION.match(line):
            if chunk_lines and (found_heading or current_section is not None):
                passages.append(
                    ExtractedPassage(
                        page=page_number,
                        section=chunk_section,
                        content="\n".join(chunk_lines),
                    )
                )
                chunk_lines = []
            current_section = line
            chunk_section = line
            found_heading = True
        chunk_lines.append(line)
    if chunk_lines:
        passages.append(
            ExtractedPassage(
                page=page_number,
                section=chunk_section,
                content="\n".join(chunk_lines),
            )
        )
    return current_section


def parse_backend(value: str) -> PdfBackend:
    if value not in {"pypdf", "pdf-inspector"}:
        raise ValueError("PDF backend must be pypdf or pdf-inspector")
    return cast(PdfBackend, value)
