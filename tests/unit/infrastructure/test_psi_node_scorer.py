from __future__ import annotations

from ragflow_lite.domain.models import GroundedAuxiliaryQuery
from ragflow_lite.infrastructure.retrievers.psi_node_scorer import (
    PsiNodeRef,
    PsiNodeScorer,
    build_psi_dense_query_text,
    build_psi_sparse_query_text,
)


class _Embedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1, 0.2]


class _Index:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search_nodes(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _request() -> GroundedAuxiliaryQuery:
    return GroundedAuxiliaryQuery(
        query_text="Q",
        entities_from_query=["Entity", "Entity"],
        answer_type_keywords=["answer"],
        retrieval_pass_id="initial",
        rewrite_source="original",
        grounding_state="complete",
        grounding_fallback="none",
    )


def test_node_scorer_builds_grounded_queries_and_build_scoped_allowlist() -> None:
    embedder = _Embedder()
    index = _Index()

    PsiNodeScorer(psi_node_index=index, embedder=embedder).score(
        _request(),
        allowed_nodes=[PsiNodeRef("build-a", "psi-a"), PsiNodeRef("build-b", "psi-a")],
        top_k=2,
    )

    assert build_psi_dense_query_text(_request()) == "Q Entity answer"
    assert build_psi_sparse_query_text(_request()) == "Q answer Entity"
    assert embedder.queries == ["Q Entity answer"]
    assert index.calls[0]["allowed_projection_row_ids"] == [
        "build-a:psi-a",
        "build-b:psi-a",
    ]
