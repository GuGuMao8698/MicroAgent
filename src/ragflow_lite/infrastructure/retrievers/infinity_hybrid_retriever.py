"""基于 Infinity hybrid（全文 + dense fusion）的检索器。"""

from __future__ import annotations

from dataclasses import dataclass

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.domain.ports.interfaces import Embedder
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)


@dataclass(frozen=True)
class InfinityHybridRetriever:
    """Hybrid 检索：embed_query -> search_hybrid（Infinity 原生 fusion）。"""

    embedder: Embedder
    vector_index: InfinityDenseVectorIndex

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        query_vector = self.embedder.embed_query(query)
        return self.vector_index.search_hybrid(query, query_vector, top_k)
