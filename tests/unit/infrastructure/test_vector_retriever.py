from __future__ import annotations

from dataclasses import dataclass

import pytest

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.retrievers import VectorRetriever


@dataclass
class FakeEmbedder:
    vector: list[float]

    def embed_query(self, query: str) -> list[float]:
        return self.vector

    def embed_chunks(self, chunks): ...


@dataclass
class FakeVectorIndex:
    results: list[RetrievedChunk]

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        return self.results[:top_k]

    def index_document(self, asset, embedded_chunks): ...

    def delete_document(self, document_id: str): ...


def _chunk(text: str = "hello") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        text=text,
        score=0.9,
    )


def test_retrieve_returns_results_from_index() -> None:
    chunks = [_chunk("a"), _chunk("b")]
    retriever = VectorRetriever(
        embedder=FakeEmbedder(vector=[1.0, 0.0]),
        vector_index=FakeVectorIndex(results=chunks),
    )

    results = retriever.retrieve("query", top_k=2)

    assert results == chunks


def test_retrieve_respects_top_k() -> None:
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
    retriever = VectorRetriever(
        embedder=FakeEmbedder(vector=[1.0, 0.0]),
        vector_index=FakeVectorIndex(results=chunks),
    )

    results = retriever.retrieve("query", top_k=1)

    assert len(results) == 1


def test_retrieve_returns_empty_when_index_is_empty() -> None:
    retriever = VectorRetriever(
        embedder=FakeEmbedder(vector=[1.0, 0.0]),
        vector_index=FakeVectorIndex(results=[]),
    )

    results = retriever.retrieve("query", top_k=5)

    assert results == []


def test_retrieve_propagates_embed_query_failure() -> None:
    @dataclass
    class BrokenEmbedder:
        def embed_query(self, query: str) -> list[float]:
            raise RuntimeError("embed failed")

        def embed_chunks(self, chunks): ...

    retriever = VectorRetriever(
        embedder=BrokenEmbedder(),
        vector_index=FakeVectorIndex(results=[]),
    )

    with pytest.raises(RuntimeError, match="embed failed"):
        retriever.retrieve("query", top_k=5)
