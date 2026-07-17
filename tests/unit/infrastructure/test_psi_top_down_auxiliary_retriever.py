from __future__ import annotations

from ragflow_lite.domain.models import (
    GroundedAuxiliaryQuery,
    GroundedAuxiliaryResult,
    PsiRetrievalStatus,
    PsiTree,
    RetrievedChunk,
)
from ragflow_lite.infrastructure.retrievers.psi_node_scorer import PsiNodeRef
from ragflow_lite.infrastructure.retrievers.psi_top_down_auxiliary_retriever import (
    PsiTopDownAuxiliaryRetriever,
)
from ragflow_lite.infrastructure.retrievers.psi_top_down_traverser import (
    PsiProjectionInconsistentError,
    PsiTraversalResult,
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


class _TreeStore:
    def __init__(self, active: bool = True) -> None:
        self.active = active

    def list_active_queryable_trees(self):
        return [PsiTree("build-a", "doc-a", 1, 1)] if self.active else []


class _Traversal:
    def traverse(self, request, top_k):
        return PsiTraversalResult(
            selected_nodes=[PsiNodeRef("build-a", "psi-node")],
            source_chunk_ids=["chunk-1"],
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state="success",
                stop_reason="leaf_reached",
                fallback_source="none",
                mapped_source_chunk_count=1,
            ),
        )


class _Narrower:
    def narrow(self, request, source_chunk_ids):
        return source_chunk_ids, None


class _Lookup:
    def get_chunks(self, chunk_ids):
        return [
            RetrievedChunk(chunk_id, "doc-1", "source", 0.5) for chunk_id in chunk_ids
        ]


class _Legacy:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve_grounded(self, request, top_k):
        self.calls += 1
        chunks = [RetrievedChunk("chunk-legacy", "doc-1", "legacy", 0.1)]
        return GroundedAuxiliaryResult(
            chunks=chunks,
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state="fallback",
                stop_reason="legacy_auxiliary_used",
                fallback_source="legacy_string_retriever",
            ),
        )


class _BadTraversal:
    def traverse(self, request, top_k):
        raise PsiProjectionInconsistentError("build-a", "wrong projected node")


class _RepairMarker:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def mark_repair_required(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_auxiliary_retriever_returns_original_chunks_only() -> None:
    result = PsiTopDownAuxiliaryRetriever(
        tree_store=_TreeStore(),
        traverser=_Traversal(),
        narrower=_Narrower(),
        chunk_lookup=_Lookup(),
        legacy_adapter=_Legacy(),
    ).retrieve_grounded(_request(), 3)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-1"]
    assert result.chunks[0].metadata == {"retrieval_source": "psi_top_down_auxiliary"}
    assert result.status.returned_chunk_count == 1


def test_no_active_tree_falls_back_with_exact_reason() -> None:
    legacy = _Legacy()
    result = PsiTopDownAuxiliaryRetriever(
        tree_store=_TreeStore(active=False),
        traverser=_Traversal(),
        narrower=_Narrower(),
        chunk_lookup=_Lookup(),
        legacy_adapter=legacy,
    ).retrieve_grounded(_request(), 3)

    assert legacy.calls == 1
    assert result.status.state == "fallback"
    assert result.status.stop_reason == "no_active_tree"
    assert result.status.fallback_source == "legacy_string_retriever"


def test_projection_inconsistency_marks_repair_before_fallback() -> None:
    repair = _RepairMarker()
    result = PsiTopDownAuxiliaryRetriever(
        tree_store=_TreeStore(),
        traverser=_BadTraversal(),
        narrower=_Narrower(),
        chunk_lookup=_Lookup(),
        legacy_adapter=_Legacy(),
        repair_marker=repair,
    ).retrieve_grounded(_request(), 3)

    assert result.status.stop_reason == "projection_inconsistent"
    assert repair.calls == [
        {
            "build_id": "build-a",
            "failure_code": "projection_inconsistent",
            "failure_stage": "query_start_nodes",
            "error_message": "wrong projected node",
        }
    ]
