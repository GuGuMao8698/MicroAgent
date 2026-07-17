from __future__ import annotations

from ragflow_lite.domain.models import (
    GroundedAuxiliaryQuery,
    GroundedAuxiliaryResult,
    PsiRetrievalStatus,
    RetrievedChunk,
)


def test_grounded_auxiliary_models_carry_pass_grounding_and_status() -> None:
    request = GroundedAuxiliaryQuery(
        query_text="What uses the latency budget?",
        entities_from_query=["latency budget"],
        answer_type_keywords=["uses"],
        retrieval_pass_id="initial",
        rewrite_source="original",
        grounding_state="complete",
        grounding_fallback="none",
    )
    status = PsiRetrievalStatus(
        retrieval_pass_id="initial",
        rewrite_source="original",
        state="fallback",
        stop_reason="legacy_auxiliary_used",
        fallback_source="legacy_string_retriever",
        returned_chunk_count=1,
    )
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        document_id="doc-1",
        text="source text",
        score=0.7,
    )

    result = GroundedAuxiliaryResult(chunks=[chunk], status=status)

    assert request.retrieval_pass_id == "initial"
    assert result.chunks == [chunk]
    assert result.status.returned_chunk_count == 1
