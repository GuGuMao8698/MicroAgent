from __future__ import annotations

from typing import Any

import pytest

from ragflow_lite.domain.models import Chunk
from ragflow_lite.infrastructure.embedders import ArkMultimodalTextEmbedder


class FakeMultimodalEmbeddingsAPI:
    def __init__(
        self,
        response_vectors: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response_vectors = list(response_vectors or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error

        vector = self.response_vectors.pop(0)
        return type(
            "FakeResponse",
            (),
            {"data": type("FakeData", (), {"embedding": vector})()},
        )()


class FakeArkClient:
    def __init__(
        self,
        response_vectors: list[list[float]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.multimodal_embeddings = FakeMultimodalEmbeddingsAPI(
            response_vectors=response_vectors,
            error=error,
        )


def test_embed_query_sends_text_input_and_normalizes_vector() -> None:
    fake_client = FakeArkClient(response_vectors=[[3.0, 4.0]])
    embedder = ArkMultimodalTextEmbedder(
        api_key="test-ark-api-key",
        model="ep-test-model",
        dimensions=2,
        client=fake_client,
    )

    vector = embedder.embed_query("rag system 检索")

    assert vector == pytest.approx([0.6, 0.8])
    assert fake_client.multimodal_embeddings.calls == [
        {
            "input": [{"type": "text", "text": "rag system 检索"}],
            "model": "ep-test-model",
            "dimensions": 2,
        }
    ]


def test_embed_chunks_reads_response_data_embedding_and_preserves_chunk_fields() -> None:
    fake_client = FakeArkClient(response_vectors=[[2.0, 0.0], [0.0, 5.0]])
    embedder = ArkMultimodalTextEmbedder(
        api_key="test-ark-api-key",
        model="ep-test-model",
        client=fake_client,
    )
    chunks = [
        Chunk(
            chunk_id="chunk_1",
            document_id="doc_1",
            text="first chunk",
            index=0,
            metadata={"filename": "alpha.txt"},
        ),
        Chunk(
            chunk_id="chunk_2",
            document_id="doc_1",
            text="second chunk",
            index=1,
            metadata={"filename": "alpha.txt"},
        ),
    ]

    embedded_chunks = embedder.embed_chunks(chunks)

    assert embedded_chunks[0].vector == pytest.approx([1.0, 0.0])
    assert embedded_chunks[1].vector == pytest.approx([0.0, 1.0])
    assert [chunk.chunk_id for chunk in embedded_chunks] == ["chunk_1", "chunk_2"]
    assert [chunk.metadata for chunk in embedded_chunks] == [
        {"filename": "alpha.txt"},
        {"filename": "alpha.txt"},
    ]
    assert fake_client.multimodal_embeddings.calls == [
        {
            "input": [{"type": "text", "text": "first chunk"}],
            "model": "ep-test-model",
        },
        {
            "input": [{"type": "text", "text": "second chunk"}],
            "model": "ep-test-model",
        },
    ]


def test_embedder_propagates_ark_client_errors() -> None:
    embedder = ArkMultimodalTextEmbedder(
        api_key="test-ark-api-key",
        model="ep-test-model",
        client=FakeArkClient(error=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        embedder.embed_query("this should fail")
