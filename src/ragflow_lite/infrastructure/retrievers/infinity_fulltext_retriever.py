"""基于 Infinity 全文匹配的检索器。"""

from __future__ import annotations

from dataclasses import dataclass

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)


@dataclass(frozen=True)
class InfinityFullTextRetriever:
    """全文检索：直接调用 Infinity 的 match_text，不做 query embedding。"""

    vector_index: InfinityDenseVectorIndex

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.vector_index.search_text(query, top_k)
