from pathlib import Path

import pytest

from space_stds.pdf import extract_pdf
from tests.pdf_factory import write_text_pdf


@pytest.mark.parametrize("backend", ["pypdf", "pdf-inspector"])
def test_pdf_backend_preserves_pages_and_numbered_sections(tmp_path: Path, backend: str) -> None:
    if backend == "pdf-inspector":
        pytest.importorskip("pdf_inspector")
    source = tmp_path / "standard.pdf"
    write_text_pdf(
        source,
        [
            ["4.1 Acquisition", "The receiver shall acquire the carrier."],
            ["4.2 Tracking", "The receiver shall track the carrier."],
        ],
    )

    result = extract_pdf(source, backend=backend)

    assert result.backend == backend
    assert result.page_count == 2
    assert [passage.page for passage in result.passages] == [1, 2]
    assert [passage.section for passage in result.passages] == [
        "4.1 Acquisition",
        "4.2 Tracking",
    ]
