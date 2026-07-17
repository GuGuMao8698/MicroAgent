from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ragflow_lite.domain.models import GroundedAuxiliaryQuery
from ragflow_lite.infrastructure.evidence.infinity_psi_node_index import (
    PsiNodeHit,
    allowed_projection_row_ids,
)


@dataclass(frozen=True, slots=True)
class PsiNodeRef:
    build_id: str
    node_id: str


class PsiNodeSearchIndex(Protocol):
    def search_nodes(
        self,
        *,
        sparse_query_text: str,
        query_vector: list[float],
        allowed_projection_row_ids: list[str],
        top_k: int,
    ) -> list[PsiNodeHit]: ...


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class PsiNodeScorer:
    def __init__(
        self, *, psi_node_index: PsiNodeSearchIndex, embedder: QueryEmbedder
    ) -> None:
        self._psi_node_index = psi_node_index
        self._embedder = embedder

    def score(
        self,
        request: GroundedAuxiliaryQuery,
        *,
        allowed_nodes: list[PsiNodeRef],
        top_k: int,
    ) -> list[PsiNodeHit]:
        if not allowed_nodes or top_k <= 0:
            return []
        dense_query_text = build_psi_dense_query_text(request)
        sparse_query_text = build_psi_sparse_query_text(request)
        query_vector = self._embedder.embed_query(dense_query_text)
        projection_ids = [
            projection_id
            for build_id, node_ids in _nodes_by_build(allowed_nodes).items()
            for projection_id in allowed_projection_row_ids(build_id, node_ids)
        ]
        return self._psi_node_index.search_nodes(
            sparse_query_text=sparse_query_text,
            query_vector=query_vector,
            allowed_projection_row_ids=projection_ids,
            top_k=top_k,
        )


def build_psi_dense_query_text(request: GroundedAuxiliaryQuery) -> str:
    return _ordered_query_text(
        request.query_text,
        request.entities_from_query,
        request.answer_type_keywords,
    )


def build_psi_sparse_query_text(request: GroundedAuxiliaryQuery) -> str:
    return _ordered_query_text(
        request.query_text,
        request.answer_type_keywords,
        request.entities_from_query,
    )


def _ordered_query_text(query: str, first: list[str], second: list[str]) -> str:
    values = [query, *first, *second]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return " ".join(result)[:2048].rstrip()


def _nodes_by_build(nodes: list[PsiNodeRef]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node in nodes:
        result.setdefault(node.build_id, []).append(node.node_id)
    return result
