"""Ark text embedding implementation for the V0 runtime path."""

from __future__ import annotations

import math
from typing import Any

from volcenginesdkarkruntime import Ark

from ragflow_lite.domain.models import Chunk, EmbeddedChunk

EmbeddingSignature = dict[str, str | int | None]


class ArkMultimodalTextEmbedder:
    """Embed text with Ark multimodal embeddings using text-only input items."""

    def __init__(
        self,
        api_key: str,
        model: str,
        dimensions: int | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.client = client or self._build_client(api_key)
        self.signature: EmbeddingSignature = {
            "provider": "ark",
            "model": self.model,
            "dimensions": self.dimensions,
        }

    def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """Batch-embed document chunks into the shared retrieval vector space."""
        return [
            EmbeddedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.text,
                index=chunk.index,
                vector=self._embed_text(chunk.text),
                metadata=dict(chunk.metadata),
            )
            for chunk in chunks
        ]

    def embed_query(self, query: str) -> list[float]:
        """Embed a user query into the same space as indexed chunks."""
        return self._embed_text(query)

    @staticmethod
    def _build_client(api_key: str) -> Any:
        return Ark(api_key=api_key)

    def _embed_text(self, text: str) -> list[float]:
        request: dict[str, Any] = {
            "input": [{"type": "text", "text": text}],
            "model": self.model,
        }
        if self.dimensions is not None:
            request["dimensions"] = self.dimensions

        response = self.client.multimodal_embeddings.create(**request)
        return self._normalize_vector(response.data.embedding)

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        normalized_source = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in normalized_source))
        if norm == 0:
            return normalized_source
        return [value / norm for value in normalized_source]
