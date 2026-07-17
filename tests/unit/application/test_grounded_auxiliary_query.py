from __future__ import annotations

from ragflow_lite.application.services.grounded_auxiliary_query import (
    build_grounded_auxiliary_query,
    render_legacy_auxiliary_query,
)
from ragflow_lite.domain.models import GroundedQuery


def test_builder_reuses_grounder_output_without_llm_prose() -> None:
    request = build_grounded_auxiliary_query(
        query_text="How does it manage latency?",
        grounded_query=GroundedQuery(
            query="How does it manage latency?",
            entities_from_query=["Latency Budget", "Latency Budget"],
            answer_type_keywords=["manage", "latency"],
        ),
        retrieval_pass_id="initial",
        rewrite_source="original",
    )

    assert request.entities_from_query == ["Latency Budget"]
    assert request.answer_type_keywords == ["manage", "latency"]
    assert request.grounding_state == "complete"
    assert request.grounding_fallback == "none"


def test_empty_grounder_result_is_complete_but_explicit_failure_uses_raw_query() -> (
    None
):
    empty = build_grounded_auxiliary_query(
        query_text="Q",
        grounded_query=GroundedQuery(
            query="Q", entities_from_query=[], answer_type_keywords=[]
        ),
        retrieval_pass_id="initial",
        rewrite_source="original",
    )
    failed = build_grounded_auxiliary_query(
        query_text="Q",
        grounded_query=GroundedQuery(
            query="Q",
            entities_from_query=[],
            answer_type_keywords=[],
            metadata={
                "grounding_state": "failed",
                "grounding_failure_code": "provider_failed",
            },
        ),
        retrieval_pass_id="rewrite-1",
        rewrite_source="enriched",
    )

    assert empty.grounding_state == "complete"
    assert failed.grounding_fallback == "raw_query_only"
    assert failed.grounding_failure_code == "provider_failed"


def test_legacy_rendering_is_bounded_deduplicated_and_deterministic() -> None:
    request = build_grounded_auxiliary_query(
        query_text="Q",
        grounded_query=GroundedQuery(
            query="Q",
            entities_from_query=["Entity B", "Entity A", "Entity B"],
            answer_type_keywords=["answer"],
        ),
        retrieval_pass_id="initial",
        rewrite_source="original",
    )

    assert render_legacy_auxiliary_query(request) == "Q Entity B Entity A answer"
