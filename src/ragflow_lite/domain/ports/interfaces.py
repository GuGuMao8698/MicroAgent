from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ragflow_lite.domain.models import (
    AnswerResult,
    Chunk,
    DocumentAsset,
    EmbeddedChunk,
    ParsedDocument,
    RetrievedChunk,
)


class DocumentStore(Protocol):
    def save_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        content: bytes,
    ) -> DocumentAsset: ...

    def read_document(self, asset: DocumentAsset) -> bytes: ...

    def delete_document(self, document_id: str) -> None: ...

    def path_for(self, document_id: str, suffix: str) -> Path: ...


class Parser(Protocol):
    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument: ...


class Chunker(Protocol):
    def chunk(self, document: ParsedDocument) -> list[Chunk]: ...


class Embedder(Protocol):
    def embed_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]: ...

    def embed_query(self, query: str) -> list[float]: ...


class VectorIndex(Protocol):
    def index_document(
        self,
        asset: DocumentAsset,
        embedded_chunks: list[EmbeddedChunk],
    ) -> None: ...

    def delete_document(self, document_id: str) -> None: ...

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]: ...


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


class Answerer(Protocol):
    def answer(self, query: str, contexts: list[RetrievedChunk]) -> AnswerResult: ...
