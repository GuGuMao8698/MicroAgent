from __future__ import annotations

from ragflow_lite.application.services.retrieval_rewrite import (
    assess_post_rewrite,
    build_retrieval_rewrite_metadata,
    decide_grounding_gate,
)

from ragflow_lite.domain.models import (
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    InitialCandidateSnapshot,
    RetrievedChunk,
)


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc1",
        text=f"text {chunk_id}",
        score=1.0,
        metadata={},
    )


def _source(chunk_id: str, *, selected_for_answer: bool) -> GraphFirstSource:
    return GraphFirstSource(
        chunk_id=chunk_id,
        rank=0,
        score=1.0,
        score_components={"test": 1.0},
        supporting_entity_ids=[],
        supporting_relation_ids=[],
        supporting_path_ids=[],
        auxiliary_chunk_hit=False,
        selected_for_answer=selected_for_answer,
        selected_for_discourse=selected_for_answer,
        selection_reason="test",
    )


def _snapshot(selected_answer_count: int) -> InitialCandidateSnapshot:
    sources = [
        _source(f"chunk_{index}", selected_for_answer=index < selected_answer_count)
        for index in range(4)
    ]
    return InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=GroundedQuery(
            query="What improves MiniRAG recall?",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        candidates=[
            _chunk(source.chunk_id) for source in sources if source.selected_for_answer
        ],
        source_selection=GraphFirstSourceSelection(
            sources=sources,
            final_context_k=4,
            discourse_selection_k=8,
            context_token_budget=None,
            omitted_source_count=0,
        ),
    )


def test_gate_accepts_when_selected_answer_candidates_meet_threshold() -> None:
    decision = decide_grounding_gate(
        _snapshot(selected_answer_count=2), requested_top_n=4
    )

    assert decision.should_rewrite is False
    assert decision.route == "accept"
    assert decision.signals["selected_answer_candidate_count"] == 2
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_rewrites_when_selected_answer_candidates_are_below_threshold() -> None:
    decision = decide_grounding_gate(
        _snapshot(selected_answer_count=1), requested_top_n=4
    )

    assert decision.should_rewrite is True
    assert decision.route == "rewrite"
    assert decision.reason == "selected_answer_candidate_count_below_threshold"
    assert decision.signals["selected_answer_candidate_count"] == 1
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_uses_ceil_half_top_n_threshold() -> None:
    assert (
        decide_grounding_gate(_snapshot(1), requested_top_n=2).should_rewrite is False
    )
    assert decide_grounding_gate(_snapshot(1), requested_top_n=3).should_rewrite is True
    assert (
        decide_grounding_gate(_snapshot(2), requested_top_n=3).should_rewrite is False
    )
    assert (
        decide_grounding_gate(_snapshot(3), requested_top_n=5).should_rewrite is False
    )
    assert decide_grounding_gate(_snapshot(3), requested_top_n=8).should_rewrite is True


def test_post_rewrite_assessment_does_not_request_recursive_rewrite() -> None:
    assessment = assess_post_rewrite(
        _snapshot(selected_answer_count=1), requested_top_n=4
    )

    assert assessment.gate_passed is False
    assert assessment.reason == "selected_answer_candidate_count_below_threshold"


def test_retrieval_rewrite_metadata_records_failed_fallback() -> None:
    metadata = build_retrieval_rewrite_metadata(
        enabled=True,
        triggered=True,
        strategy="cot_grounding",
        status="failed",
        gate_reason="selected_answer_candidate_count_below_threshold",
        attempts=2,
        failure_reason="invalid structured output",
        fallback_source="initial_candidate_snapshot",
        initial_candidate_count=1,
        enriched_candidate_count=0,
        post_rewrite_gate_passed=None,
        post_rewrite_gate_reason=None,
        answer_notice_required=False,
    )

    assert metadata["retrieval_rewrite"]["status"] == "failed"
    assert (
        metadata["retrieval_rewrite"]["fallback_source"] == "initial_candidate_snapshot"
    )
