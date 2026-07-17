from __future__ import annotations

from ragflow_lite.domain.models import GroundedAuxiliaryQuery, RetrievedChunk
from ragflow_lite.infrastructure.retrievers.legacy_grounded_auxiliary_adapter import (
    LegacyGroundedAuxiliaryAdapter,
)


class _LegacyRetriever:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        if self.fail:
            raise RuntimeError("legacy unavailable")
        return [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_id="doc-1",
                text="text",
                score=0.5,
            )
        ]


def _request() -> GroundedAuxiliaryQuery:
    return GroundedAuxiliaryQuery(
        query_text="Q",
        entities_from_query=["Entity"],
        answer_type_keywords=["answer"],
        retrieval_pass_id="initial",
        rewrite_source="original",
        grounding_state="complete",
        grounding_fallback="none",
    )


def test_legacy_adapter_records_explicit_fallback_status() -> None:
    legacy = _LegacyRetriever()

    result = LegacyGroundedAuxiliaryAdapter(legacy).retrieve_grounded(
        _request(), top_k=3
    )

    assert legacy.calls == [("Q Entity answer", 3)]
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-1"]
    assert result.status.state == "fallback"
    assert result.status.stop_reason == "legacy_auxiliary_used"


def test_legacy_adapter_surfaces_failure_in_status() -> None:
    result = LegacyGroundedAuxiliaryAdapter(
        _LegacyRetriever(fail=True)
    ).retrieve_grounded(_request(), top_k=3)

    assert result.chunks == []
    assert result.status.state == "failed"
    assert result.status.failure_code == "unexpected_exception"
