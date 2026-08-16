from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from space_stds.pdf import PdfBackend, parse_backend


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    corpus_dir: Path
    pdf_backend: PdfBackend = "pypdf"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "index.sqlite3"

    @classmethod
    def from_environment(cls) -> Settings:
        default_data = Path.home() / ".local" / "share" / "space-stds"
        data_dir = Path(os.environ.get("SPACE_STDS_DATA_DIR", default_data)).expanduser()
        corpus_dir = Path(os.environ.get("SPACE_STDS_CORPUS_DIR", data_dir / "corpus")).expanduser()
        pdf_backend = parse_backend(os.environ.get("SPACE_STDS_PDF_BACKEND", "pypdf"))
        return cls(
            data_dir=data_dir.resolve(),
            corpus_dir=corpus_dir.resolve(),
            pdf_backend=pdf_backend,
        )

    def initialise(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
