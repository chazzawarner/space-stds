#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from space_stds.config import Settings
from space_stds.evaluation import BenchmarkCase, evaluate_case, load_cases, summarise
from space_stds.pdf import PdfBackend
from space_stds.service import StandardsService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare pypdf and PDF Inspector extraction on a local standards corpus"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/retrieval.json"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/extractor-results.json"))
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--worker-backend", choices=("pypdf", "pdf-inspector"), help=argparse.SUPPRESS
    )
    parser.add_argument("--corpus-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not 1 <= args.top_k <= 10:
        parser.error("--top-k must be between 1 and 10")
    cases = load_cases(args.cases)
    if args.worker_backend:
        if args.corpus_root is None:
            parser.error("worker mode requires --corpus-root")
        result = _benchmark_backend(
            cast(PdfBackend, args.worker_backend),
            manifest=args.manifest,
            corpus_root=args.corpus_root,
            cases=cases,
            top_k=args.top_k,
        )
        result["peak_memory_mib"] = _peak_memory_mib()
        print(json.dumps(result))
        return 0
    settings = Settings.from_environment()
    backends: tuple[PdfBackend, ...] = ("pypdf", "pdf-inspector")
    results = [
        _run_worker(
            backend,
            manifest=args.manifest,
            corpus_root=settings.corpus_dir,
            cases_path=args.cases,
            top_k=args.top_k,
        )
        for backend in backends
    ]
    by_backend = {result["backend"]: result for result in results}
    baseline = by_backend["pypdf"]
    candidate = by_backend["pdf-inspector"]
    candidate_passes = (
        candidate["hit_rate_at_k"] >= baseline["hit_rate_at_k"]
        and candidate["top_1_accuracy"] >= baseline["top_1_accuracy"]
        and candidate["ndcg_at_k"] >= baseline["ndcg_at_k"]
        and candidate["page_text_coverage"] >= baseline["page_text_coverage"]
        and candidate["citation_field_completeness"] >= baseline["citation_field_completeness"]
        and candidate["pages"] == baseline["pages"]
    )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": args.manifest.name,
        "cases": len(cases),
        "top_k": args.top_k,
        "recommended_default": "pypdf",
        "pdf_inspector_passes_automated_gate": candidate_passes,
        "selection_rule": (
            "PDF Inspector must match or exceed pypdf passage hit-rate, top-1 accuracy, "
            "nDCG, page text coverage, and citation-field completeness. Manual sampled "
            "review of page fidelity, structures, tables, symbols, and page furniture is "
            "still required."
        ),
        "manual_extraction_review_required": True,
        "manual_review_criteria": [
            "page-number fidelity",
            "clause and annex boundaries",
            "numbered requirements",
            "table reading order",
            "equations, units, symbols, and special characters",
            "headers and footers",
            "native-text, scanned, and mixed-page detection",
        ],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


def _benchmark_backend(
    backend: PdfBackend,
    *,
    manifest: Path,
    corpus_root: Path,
    cases: list[BenchmarkCase],
    top_k: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"space-stds-{backend}-") as temporary:
        database = Path(temporary) / "index.sqlite3"
        service = StandardsService(database, corpus_root, pdf_backend=backend)
        started = time.perf_counter()
        ingestion = service.ingest_manifest(manifest)
        elapsed = time.perf_counter() - started
        with sqlite3.connect(database) as connection:
            indexed_pages, sectioned, requirements, characters = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT document_key || ':' || page),
                    SUM(section IS NOT NULL),
                    SUM(INSTR(LOWER(content), ' shall ') > 0),
                    SUM(LENGTH(content))
                FROM passages
                """
            ).fetchone()

        case_results = []
        for case in cases:
            hits = service.search(
                case.question,
                source=case.source,
                status="active",
                limit=top_k,
            )
            case_results.append(evaluate_case(case, hits))

        retrieval = summarise(case_results, top_k=top_k)
        return {
            "backend": backend,
            "ingestion_seconds": round(elapsed, 3),
            **asdict(ingestion),
            "indexed_pages": indexed_pages,
            "page_text_coverage": indexed_pages / ingestion.pages if ingestion.pages else 0,
            "sectioned_passages": sectioned,
            "requirement_passages": requirements,
            "extracted_characters": characters,
            **asdict(retrieval),
            "case_results": [asdict(result) for result in case_results],
        }


def _run_worker(
    backend: PdfBackend,
    *,
    manifest: Path,
    corpus_root: Path,
    cases_path: Path,
    top_k: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--manifest",
        str(manifest.resolve()),
        "--cases",
        str(cases_path.resolve()),
        "--top-k",
        str(top_k),
        "--worker-backend",
        backend,
        "--corpus-root",
        str(corpus_root.resolve()),
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=15 * 60,
    )
    return cast(dict[str, Any], json.loads(completed.stdout))


def _peak_memory_mib() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(peak / divisor, 1)


if __name__ == "__main__":
    raise SystemExit(main())
