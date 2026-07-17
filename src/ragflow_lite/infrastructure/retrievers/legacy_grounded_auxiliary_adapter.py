from __future__ import annotations

from ragflow_lite.application.services.grounded_auxiliary_query import (
    render_legacy_auxiliary_query,
)
from ragflow_lite.domain.models import (
    GroundedAuxiliaryQuery,
    GroundedAuxiliaryResult,
    PsiRetrievalStatus,
)
from ragflow_lite.domain.ports.interfaces import Retriever


class LegacyGroundedAuxiliaryAdapter:
    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def retrieve_grounded(
        self,
        request: GroundedAuxiliaryQuery,
        top_k: int,
    ) -> GroundedAuxiliaryResult:
        if top_k <= 0:
            raise ValueError("grounded auxiliary top_k must be positive")
        query = render_legacy_auxiliary_query(request)
        try:
            chunks = self._retriever.retrieve(query, top_k)
        except Exception as exc:
            return GroundedAuxiliaryResult(
                chunks=[],
                status=PsiRetrievalStatus(
                    retrieval_pass_id=request.retrieval_pass_id,
                    rewrite_source=request.rewrite_source,
                    state="failed",
                    stop_reason="unexpected_exception",
                    fallback_source="legacy_string_retriever",
                    failure_code="unexpected_exception",
                    error_message=str(exc),
                ),
            )
        return GroundedAuxiliaryResult(
            chunks=chunks,
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state="fallback",
                stop_reason="legacy_auxiliary_used",
                fallback_source="legacy_string_retriever",
                returned_chunk_count=len(chunks),
                metadata={"legacy_query": query},
            ),
        )
