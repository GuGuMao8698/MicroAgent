from __future__ import annotations

from ragflow_lite.domain.models import GroundedAuxiliaryQuery
from ragflow_lite.infrastructure.retrievers.psi_source_chunk_narrower import (
    PsiSourceChunkNarrower,
    PsiSourceNarrowingConfig,
)


def _request() -> GroundedAuxiliaryQuery:
    return GroundedAuxiliaryQuery(
        query_text="Q",
        entities_from_query=[],
        answer_type_keywords=[],
        retrieval_pass_id="initial",
        rewrite_source="original",
        grounding_state="complete",
        grounding_fallback="none",
    )


def test_narrower_preserves_order_below_threshold() -> None:
    narrower = PsiSourceChunkNarrower(
        config=PsiSourceNarrowingConfig(
            max_source_chunks_without_narrowing=3, max_auxiliary_chunks=3
        )
    )
    assert narrower.narrow(_request(), ["chunk-b", "chunk-a"]) == (
        ["chunk-b", "chunk-a"],
        None,
    )


def test_narrower_records_unavailable_candidate_filtering() -> None:
    narrower = PsiSourceChunkNarrower(
        config=PsiSourceNarrowingConfig(
            max_source_chunks_without_narrowing=1, max_auxiliary_chunks=2
        )
    )
    assert narrower.narrow(_request(), ["chunk-c", "chunk-a", "chunk-b"]) == (
        ["chunk-c", "chunk-a"],
        "narrowing_unavailable",
    )
