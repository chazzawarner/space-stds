#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from space_stds.config import Settings
from space_stds.evaluation import evaluate_case, load_cases, summarise
from space_stds.service import StandardsService

_MINIMUM_TOP_1 = 0.75
_MINIMUM_MRR = 0.85
_MINIMUM_NDCG = 0.75


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against the local corpus")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("benchmarks/retrieval.json"),
        help="JSON benchmark case file",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 10:
        parser.error("--top-k must be between 1 and 10")

    cases = load_cases(args.cases)
    settings = Settings.from_environment()
    service = StandardsService(settings.database_path, settings.corpus_dir)
    results = [
        evaluate_case(
            case,
            service.search(
                case.question,
                source=case.source,
                status="active",
                limit=args.top_k,
            ),
        )
        for case in cases
    ]
    summary = summarise(results, top_k=args.top_k)
    gates = {
        "hit_rate_at_k": summary.hit_rate_at_k == 1.0,
        "top_1_accuracy": summary.top_1_accuracy >= _MINIMUM_TOP_1,
        "mean_reciprocal_rank": summary.mean_reciprocal_rank >= _MINIMUM_MRR,
        "ndcg_at_k": summary.ndcg_at_k >= _MINIMUM_NDCG,
        "citation_field_completeness": summary.citation_field_completeness == 1.0,
        "no_answer_accuracy": summary.no_answer_accuracy == 1.0,
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cases_file": args.cases.name,
        **asdict(summary),
        "quality_gates": gates,
        "passed": all(gates.values()),
        "results": [asdict(result) for result in results],
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
