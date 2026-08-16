from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from space_stds.domain import Corpus, SearchHit


@dataclass(frozen=True, slots=True)
class RelevantPassage:
    document_id: str
    revision: str
    page: int
    section_prefix: str | None
    relevance: int


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    question: str
    source: Corpus
    tags: tuple[str, ...]
    relevant: tuple[RelevantPassage, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    question: str
    tags: tuple[str, ...]
    first_relevant_rank: int | None
    reciprocal_rank: float
    ndcg: float
    relevance_grades: tuple[int, ...]
    returned: tuple[str, ...]
    complete_citations: int
    returned_hits: int
    expected_no_answer: bool
    no_answer_correct: bool

    @property
    def citation_fields_complete(self) -> bool:
        return self.returned_hits > 0 and self.complete_citations == self.returned_hits


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    cases: int
    positive_cases: int
    negative_cases: int
    top_k: int
    hit_rate_at_k: float
    top_1_accuracy: float
    mean_reciprocal_rank: float
    ndcg_at_k: float
    citation_field_completeness: float
    no_answer_accuracy: float
    tag_counts: dict[str, int]


def evaluate_case(case: BenchmarkCase, hits: list[SearchHit]) -> CaseResult:
    grades: list[int] = []
    used_labels: set[int] = set()
    for hit in hits:
        matches = [
            (index, item.relevance)
            for index, item in enumerate(case.relevant)
            if index not in used_labels and _matches(case, item, hit)
        ]
        if not matches:
            grades.append(0)
            continue
        label_index, grade = max(matches, key=lambda match: match[1])
        used_labels.add(label_index)
        grades.append(grade)
    relevance_grades = tuple(grades)
    first_rank = next((rank for rank, grade in enumerate(relevance_grades, start=1) if grade), None)
    complete = sum(_citation_fields_complete(hit) for hit in hits)
    ideal = sorted((item.relevance for item in case.relevant), reverse=True)[: len(hits)]
    return CaseResult(
        case_id=case.case_id,
        question=case.question,
        tags=case.tags,
        first_relevant_rank=first_rank,
        reciprocal_rank=1 / first_rank if first_rank is not None else 0.0,
        ndcg=_dcg(relevance_grades) / _dcg(ideal) if ideal else 0.0,
        relevance_grades=relevance_grades,
        returned=tuple(f"{hit.document_id} rev {hit.revision} p.{hit.page}" for hit in hits),
        complete_citations=complete,
        returned_hits=len(hits),
        expected_no_answer=not case.relevant,
        no_answer_correct=not case.relevant and not hits,
    )


def summarise(results: list[CaseResult], *, top_k: int) -> BenchmarkSummary:
    cases = len(results)
    positives = [result for result in results if not result.expected_no_answer]
    negatives = [result for result in results if result.expected_no_answer]
    returned_hits = sum(result.returned_hits for result in results)
    tags = Counter(tag for result in results for tag in result.tags)
    return BenchmarkSummary(
        cases=cases,
        positive_cases=len(positives),
        negative_cases=len(negatives),
        top_k=top_k,
        hit_rate_at_k=(
            sum(result.first_relevant_rank is not None for result in positives) / len(positives)
            if positives
            else 0.0
        ),
        top_1_accuracy=(
            sum(result.first_relevant_rank == 1 for result in positives) / len(positives)
            if positives
            else 0.0
        ),
        mean_reciprocal_rank=(
            sum(result.reciprocal_rank for result in positives) / len(positives)
            if positives
            else 0.0
        ),
        ndcg_at_k=(sum(result.ndcg for result in positives) / len(positives) if positives else 0.0),
        citation_field_completeness=(
            sum(result.complete_citations for result in results) / returned_hits
            if returned_hits
            else 0.0
        ),
        no_answer_accuracy=(
            sum(result.no_answer_correct for result in negatives) / len(negatives)
            if negatives
            else 0.0
        ),
        tag_counts=dict(sorted(tags.items())),
    )


def load_cases(path: Path) -> list[BenchmarkCase]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list) or not payload:
        raise ValueError("Benchmark cases must be a non-empty list")
    return [_parse_case(item, index) for index, item in enumerate(payload)]


def _parse_case(value: object, index: int) -> BenchmarkCase:
    if not isinstance(value, dict):
        raise ValueError(f"Benchmark case {index} must be an object")
    case = cast(dict[str, Any], value)
    required = {"id", "question", "source", "tags", "relevant"}
    if set(case) != required:
        raise ValueError(
            f"Benchmark case {index} must contain exactly: {', '.join(sorted(required))}"
        )
    if case["source"] not in {"CCSDS", "ECSS"}:
        raise ValueError(f"Benchmark case {index} has invalid source")
    if not isinstance(case["tags"], list) or not case["tags"]:
        raise ValueError(f"Benchmark case {index} must have tags")
    relevant = case["relevant"]
    if not isinstance(relevant, list):
        raise ValueError(f"Benchmark case {index} relevant must be a list")
    if not relevant and "no-answer" not in case["tags"]:
        raise ValueError(f"Benchmark case {index} needs relevant passages unless tagged no-answer")
    if relevant and "no-answer" in case["tags"]:
        raise ValueError(f"Benchmark case {index} cannot have relevant passages and no-answer")
    return BenchmarkCase(
        case_id=_nonempty_string(case["id"], f"Benchmark case {index} id"),
        question=_nonempty_string(case["question"], f"Benchmark case {index} question"),
        source=cast(Corpus, case["source"]),
        tags=tuple(_nonempty_string(tag, f"Benchmark case {index} tag") for tag in case["tags"]),
        relevant=tuple(_parse_relevant(item, index) for item in relevant),
    )


def _parse_relevant(value: object, case_index: int) -> RelevantPassage:
    if not isinstance(value, dict):
        raise ValueError(f"Benchmark case {case_index} relevant passage must be an object")
    item = cast(dict[str, Any], value)
    required = {"document_id", "revision", "page", "section_prefix", "relevance"}
    if set(item) != required:
        raise ValueError(
            f"Benchmark case {case_index} relevant passage must contain exactly: "
            f"{', '.join(sorted(required))}"
        )
    if isinstance(item["page"], bool) or not isinstance(item["page"], int) or item["page"] < 1:
        raise ValueError(f"Benchmark case {case_index} relevant page must be positive")
    if item["section_prefix"] is not None and not isinstance(item["section_prefix"], str):
        raise ValueError(f"Benchmark case {case_index} section_prefix must be a string or null")
    if (
        isinstance(item["relevance"], bool)
        or not isinstance(item["relevance"], int)
        or item["relevance"] not in {1, 2, 3}
    ):
        raise ValueError(f"Benchmark case {case_index} relevance must be 1, 2, or 3")
    return RelevantPassage(
        document_id=_nonempty_string(
            item["document_id"], f"Benchmark case {case_index} document_id"
        ),
        revision=_nonempty_string(item["revision"], f"Benchmark case {case_index} revision"),
        page=item["page"],
        section_prefix=item["section_prefix"],
        relevance=item["relevance"],
    )


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _matches(case: BenchmarkCase, item: RelevantPassage, hit: SearchHit) -> bool:
    section_matches = item.section_prefix is None or (
        hit.section is not None and hit.section.startswith(item.section_prefix)
    )
    return (
        hit.source == case.source
        and hit.document_id == item.document_id
        and hit.revision == item.revision
        and hit.page == item.page
        and section_matches
    )


def _citation_fields_complete(hit: SearchHit) -> bool:
    return (
        hit.page > 0
        and bool(hit.section)
        and hit.official_url.startswith("https://")
        and hit.resource_uri.startswith("space-stds://passages/")
    )


def _dcg(grades: tuple[int, ...] | list[int]) -> float:
    return float(
        sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))
    )
