from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from ragflow_lite.domain.models import (
    GroundedAuxiliaryQuery,
    GroundedAuxiliaryResult,
    PsiRetrievalStatus,
    PsiTree,
    RetrievedChunk,
)
from ragflow_lite.domain.ports.interfaces import ChunkLookup, GroundedAuxiliaryRetriever
from ragflow_lite.infrastructure.retrievers.psi_top_down_traverser import (
    PsiProjectionInconsistentError,
    PsiTraversalResult,
)


class ActivePsiTreeStore(Protocol):
    def list_active_queryable_trees(self) -> list[PsiTree]: ...


class PsiTraverser(Protocol):
    def traverse(
        self, request: GroundedAuxiliaryQuery, top_k: int
    ) -> PsiTraversalResult: ...


class PsiNarrower(Protocol):
    def narrow(
        self, request: GroundedAuxiliaryQuery, source_chunk_ids: list[str]
    ) -> tuple[list[str], str | None]: ...


class PsiRepairMarker(Protocol):
    def mark_repair_required(
        self,
        *,
        build_id: str,
        failure_code: str,
        failure_stage: str,
        error_message: str,
    ) -> None: ...


class PsiTopDownAuxiliaryRetriever:
    def __init__(
        self,
        *,
        tree_store: ActivePsiTreeStore,
        traverser: PsiTraverser,
        narrower: PsiNarrower,
        chunk_lookup: ChunkLookup,
        legacy_adapter: GroundedAuxiliaryRetriever | None = None,
        repair_marker: PsiRepairMarker | None = None,
    ) -> None:
        self._tree_store = tree_store
        self._traverser = traverser
        self._narrower = narrower
        self._chunk_lookup = chunk_lookup
        self._legacy_adapter = legacy_adapter
        self._repair_marker = repair_marker

    def retrieve_grounded(
        self, request: GroundedAuxiliaryQuery, top_k: int
    ) -> GroundedAuxiliaryResult:
        if top_k <= 0:
            raise ValueError("grounded auxiliary top_k must be positive")
        if not self._tree_store.list_active_queryable_trees():
            return self._fallback(request, top_k, stop_reason="no_active_tree")
        try:
            traversal = self._traverser.traverse(request, top_k)
        except PsiProjectionInconsistentError as exc:
            if self._repair_marker is not None:
                self._repair_marker.mark_repair_required(
                    build_id=exc.build_id,
                    failure_code="projection_inconsistent",
                    failure_stage="query_start_nodes",
                    error_message=str(exc),
                )
            return self._fallback(
                request,
                top_k,
                stop_reason="projection_inconsistent",
                failure_code="projection_inconsistent",
                error_message=str(exc),
            )
        except Exception as exc:
            return self._fallback(
                request,
                top_k,
                stop_reason="unexpected_exception",
                failure_code="unexpected_exception",
                error_message=str(exc),
            )

        if not traversal.source_chunk_ids:
            return self._fallback(
                request,
                top_k,
                stop_reason=traversal.status.stop_reason,
                failure_code=traversal.status.failure_code,
                error_message=traversal.status.error_message,
            )
        narrowed_ids, narrowing_reason = self._narrower.narrow(
            request, traversal.source_chunk_ids
        )
        requested_ids = narrowed_ids[:top_k]
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self._chunk_lookup.get_chunks(requested_ids)
            if chunk.chunk_id in set(requested_ids)
        }
        chunks = [
            _with_psi_source(chunks_by_id[chunk_id])
            for chunk_id in requested_ids
            if chunk_id in chunks_by_id
        ]
        missing_chunks = len(chunks) != len(requested_ids)
        status = replace(
            traversal.status,
            state=(
                "degraded"
                if narrowing_reason is not None or missing_chunks
                else traversal.status.state
            ),
            stop_reason=(
                "source_chunk_missing"
                if missing_chunks
                else narrowing_reason or traversal.status.stop_reason
            ),
            failure_code=(
                "source_chunk_missing"
                if missing_chunks
                else narrowing_reason or traversal.status.failure_code
            ),
            narrowed_source_chunk_count=len(requested_ids),
            returned_chunk_count=len(chunks),
        )
        return GroundedAuxiliaryResult(chunks=chunks, status=status)

    def _fallback(
        self,
        request: GroundedAuxiliaryQuery,
        top_k: int,
        *,
        stop_reason: str,
        failure_code: str | None = None,
        error_message: str | None = None,
    ) -> GroundedAuxiliaryResult:
        if self._legacy_adapter is not None:
            legacy = self._legacy_adapter.retrieve_grounded(request, top_k)
            return GroundedAuxiliaryResult(
                chunks=legacy.chunks,
                status=replace(
                    legacy.status,
                    state="fallback" if legacy.status.state != "failed" else "failed",
                    stop_reason=stop_reason,
                    fallback_source="legacy_string_retriever",
                    failure_code=failure_code or legacy.status.failure_code,
                    error_message=error_message or legacy.status.error_message,
                    returned_chunk_count=len(legacy.chunks),
                ),
            )
        return GroundedAuxiliaryResult(
            chunks=[],
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state="skipped" if failure_code is None else "failed",
                stop_reason=stop_reason,
                fallback_source="none",
                failure_code=failure_code,
                error_message=error_message,
            ),
        )


def _with_psi_source(chunk: RetrievedChunk) -> RetrievedChunk:
    return replace(
        chunk,
        metadata={**chunk.metadata, "retrieval_source": "psi_top_down_auxiliary"},
    )
