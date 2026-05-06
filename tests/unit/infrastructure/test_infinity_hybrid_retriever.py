"""使用 mock 验证 `InfinityHybridRetriever` 的单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.domain.models.entities import Chunk, EmbeddedChunk
from ragflow_lite.infrastructure.retrievers.infinity_hybrid_retriever import (
    InfinityHybridRetriever,
)


@dataclass
class FakeEmbedder:
    vector: list[float]

    def embed_query(self, query: str) -> list[float]:
        return self.vector

    def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]: ...


def _chunk(text: str = "hello") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        text=text,
        score=0.9,
    )


class TestInfinityHybridRetriever:
    def test_retrieve_returns_search_hybrid_results(self) -> None:
        chunks = [_chunk("a"), _chunk("b")]
        embedder = MagicMock()
        embedder.embed_query.return_value = [1.0]
        vector_index = MagicMock()
        vector_index.search_hybrid.return_value = chunks

        retriever = InfinityHybridRetriever(
            embedder=embedder, vector_index=vector_index
        )
        results = retriever.retrieve("query", top_k=5)

        assert results == chunks

    def test_retrieve_returns_empty_when_no_results(self) -> None:
        embedder = MagicMock()
        embedder.embed_query.return_value = [1.0]
        vector_index = MagicMock()
        vector_index.search_hybrid.return_value = []

        retriever = InfinityHybridRetriever(
            embedder=embedder, vector_index=vector_index
        )
        results = retriever.retrieve("query", top_k=5)

        assert results == []

    def test_retrieve_propagates_embed_query_failure(self) -> None:
        @dataclass
        class BrokenEmbedder:
            def embed_query(self, query: str) -> list[float]:
                raise RuntimeError("embed failed")

            def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]: ...

        vector_index = MagicMock()
        retriever = InfinityHybridRetriever(
            embedder=BrokenEmbedder(), vector_index=vector_index
        )

        with pytest.raises(RuntimeError, match="embed failed"):
            retriever.retrieve("query", top_k=5)

    def test_retrieve_propagates_search_hybrid_failure(self) -> None:
        embedder = MagicMock()
        embedder.embed_query.return_value = [1.0]
        vector_index = MagicMock()
        vector_index.search_hybrid.side_effect = RuntimeError("db error")

        retriever = InfinityHybridRetriever(
            embedder=embedder, vector_index=vector_index
        )

        with pytest.raises(RuntimeError, match="db error"):
            retriever.retrieve("query", top_k=5)

    def test_retrieve_passes_raw_query_to_embedder(self) -> None:
        embedder = MagicMock()
        embedder.embed_query.return_value = [1.0, 0.0]
        vector_index = MagicMock()
        vector_index.search_hybrid.return_value = []

        retriever = InfinityHybridRetriever(
            embedder=embedder, vector_index=vector_index
        )
        retriever.retrieve("RAG系统API", top_k=5)

        embedder.embed_query.assert_called_once_with("RAG系统API")

    def test_retrieve_uses_chunk_text_query_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: dict[str, object] = {}

        class FakeEmbedder:
            def embed_query(self, query: str) -> list[float]:
                calls["embedded_query"] = query
                return [1.0, 0.0]

        class FakeVectorIndex:
            def search_hybrid(self, query: str, query_vector: list[float], top_k: int):
                calls["sparse_query"] = query
                calls["query_vector"] = query_vector
                calls["top_k"] = top_k
                return []

        from ragflow_lite.infrastructure.retrievers import infinity_hybrid_retriever

        monkeypatch.setattr(
            infinity_hybrid_retriever,
            "build_chunk_text_query",
            lambda query: "tokenized query",
        )

        retriever = infinity_hybrid_retriever.InfinityHybridRetriever(
            embedder=FakeEmbedder(),
            vector_index=FakeVectorIndex(),
        )
        retriever.retrieve("Raw Query", top_k=6)

        assert calls == {
            "embedded_query": "Raw Query",
            "sparse_query": "tokenized query",
            "query_vector": [1.0, 0.0],
            "top_k": 6,
        }
