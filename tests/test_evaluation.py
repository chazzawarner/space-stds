from space_stds.domain import SearchHit
from space_stds.evaluation import BenchmarkCase, RelevantPassage, evaluate_case, summarise


def _hit(document_id: str, page: int, section: str = "4.1 Scope") -> SearchHit:
    return SearchHit(
        passage_id=f"{document_id}-{page}",
        source="CCSDS",
        document_id=document_id,
        title="Synthetic standard",
        revision="1",
        status="active",
        page=page,
        section=section,
        excerpt="Relevant source text.",
        official_url="https://ccsds.org/example.pdf",
        resource_uri=f"space-stds://passages/{document_id}-{page}",
    )


def test_benchmark_accepts_multiple_graded_relevant_passages() -> None:
    case = BenchmarkCase(
        case_id="cross-standard-answer",
        question="Where is the shared concept defined?",
        source="CCSDS",
        tags=("cross-standard",),
        relevant=(
            RelevantPassage("CCSDS A", "1", 10, "4.1", 3),
            RelevantPassage("CCSDS B", "1", 20, "5.2", 2),
        ),
    )

    result = evaluate_case(case, [_hit("CCSDS B", 20, "5.2 Definition"), _hit("CCSDS A", 10)])

    assert result.first_relevant_rank == 1
    assert result.reciprocal_rank == 1.0
    assert 0 < result.ndcg < 1
    assert result.relevance_grades == (2, 3)
    assert result.citation_fields_complete


def test_one_relevance_label_cannot_score_multiple_returned_passages() -> None:
    case = BenchmarkCase(
        case_id="one-label",
        question="Which passage is relevant?",
        source="CCSDS",
        tags=("definition",),
        relevant=(RelevantPassage("CCSDS A", "1", 10, "4.1", 3),),
    )

    result = evaluate_case(case, [_hit("CCSDS A", 10), _hit("CCSDS A", 10)])

    assert result.relevance_grades == (3, 0)
    assert result.ndcg == 1.0


def test_benchmark_summary_reports_ranking_and_citation_metrics() -> None:
    first = evaluate_case(
        BenchmarkCase(
            case_id="first",
            question="First",
            source="CCSDS",
            tags=("definition",),
            relevant=(RelevantPassage("CCSDS A", "1", 1, None, 3),),
        ),
        [_hit("CCSDS A", 1)],
    )
    second = evaluate_case(
        BenchmarkCase(
            case_id="second",
            question="Second",
            source="CCSDS",
            tags=("requirement",),
            relevant=(RelevantPassage("CCSDS B", "1", 2, None, 3),),
        ),
        [_hit("CCSDS X", 9), _hit("CCSDS B", 2)],
    )

    summary = summarise([first, second], top_k=3)

    assert summary.cases == 2
    assert summary.hit_rate_at_k == 1.0
    assert summary.top_1_accuracy == 0.5
    assert summary.mean_reciprocal_rank == 0.75
    assert 0 < summary.ndcg_at_k < 1
    assert summary.citation_field_completeness == 1.0
    assert summary.tag_counts == {"definition": 1, "requirement": 1}


def test_benchmark_scores_a_no_answer_case_separately() -> None:
    case = BenchmarkCase(
        case_id="no-answer",
        question="What is the lunar catering packet format?",
        source="CCSDS",
        tags=("no-answer",),
        relevant=(),
    )

    result = evaluate_case(case, [])
    summary = summarise([result], top_k=3)

    assert result.no_answer_correct
    assert summary.positive_cases == 0
    assert summary.negative_cases == 1
    assert summary.no_answer_accuracy == 1.0
