from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from space_stds.pdf import PdfBackend, parse_backend


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved local storage and extraction settings for one server process."""

    data_dir: Path
    corpus_dir: Path
    pdf_backend: PdfBackend = "pypdf"

    @property
    def database_path(self) -> Path:
        """Return the SQLite index location beneath the configured data directory."""

        return self.data_dir / "index.sqlite3"

    @classmethod
    def from_environment(cls) -> Settings:
        """Resolve settings from environment overrides and local-first defaults."""

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
        """Create the private local directories required by the service."""

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
