from __future__ import annotations

from ragflow_lite.domain.models import GroundedAuxiliaryQuery, PsiTree
from ragflow_lite.infrastructure.evidence.infinity_psi_node_index import PsiNodeHit
from ragflow_lite.infrastructure.retrievers.psi_top_down_traverser import (
    PsiTopDownTraverser,
    PsiTraversalConfig,
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
    def __init__(self) -> None:
        self.node_queries: list[tuple[str, int]] = []

    def list_active_queryable_trees(self):
        return [
            PsiTree("build-a", "doc-a", 1, 1),
            PsiTree("build-b", "doc-b", 2, 2),
        ]

    def get_node_ids(self, build_id: str, *, layer: int) -> list[str]:
        self.node_queries.append((build_id, layer))
        return ["root"]

    def get_child_node_ids(self, build_id: str, parent_node_id: str) -> list[str]:
        return ["leaf"] if parent_node_id == "root" else []

    def get_source_chunk_ids(self, build_id: str, node_id: str) -> list[str]:
        return [f"chunk-{build_id}"] if node_id == "leaf" else []


class _Scorer:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def score(self, request, *, allowed_nodes, top_k):
        self.calls.append([(node.build_id, node.node_id) for node in allowed_nodes])
        return [
            PsiNodeHit(
                psi_node_id=node.node_id,
                build_id=node.build_id,
                document_id=node.build_id.replace("build", "doc"),
                layer=1 if node.node_id == "root" else 0,
                node_type="root" if node.node_id == "root" else "leaf",
                abstract_type="keyword" if node.node_id == "root" else None,
                score=1.0,
            )
            for node in allowed_nodes[:top_k]
        ]


def test_traverser_starts_at_persisted_layers_and_maps_only_source_ids() -> None:
    store = _TreeStore()
    scorer = _Scorer()

    result = PsiTopDownTraverser(tree_store=store, scorer=scorer).traverse(
        _request(), top_k=3
    )

    assert store.node_queries == [("build-a", 1), ("build-b", 2)]
    assert scorer.calls[0] == [("build-a", "root"), ("build-b", "root")]
    assert result.source_chunk_ids == ["chunk-build-a", "chunk-build-b"]
    assert "root" not in result.source_chunk_ids
    assert result.status.state == "success"


def test_traverser_records_budget_exhaustion() -> None:
    result = PsiTopDownTraverser(
        tree_store=_TreeStore(),
        scorer=_Scorer(),
        config=PsiTraversalConfig(max_total_scored_nodes=1),
    ).traverse(_request(), top_k=3)

    assert result.status.state == "degraded"
    assert result.status.stop_reason == "budget_exhausted"
