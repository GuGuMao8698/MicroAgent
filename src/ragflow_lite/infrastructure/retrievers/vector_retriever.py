from __future__ import annotations

from dataclasses import dataclass

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.domain.ports.interfaces import Embedder, VectorIndex


@dataclass(frozen=True)
class VectorRetriever:
    """纯向量检索：embed_query -> vector_index.search。"""

    embedder: Embedder
    vector_index: VectorIndex

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        query_vector = self.embedder.embed_query(query)
        return self.vector_index.search(query_vector, top_k)
