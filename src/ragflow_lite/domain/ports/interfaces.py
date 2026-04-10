from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ragflow_lite.domain.models import (
    AnswerResult,
    Chunk,
    Dataset,
    DocumentAsset,
    EmbeddedChunk,
    IndexedDocument,
    ParsedDocument,
    RetrievedChunk,
)


class DatasetStore(Protocol):
    def create_dataset(self, name: str, description: str) -> Dataset: ...

    def list_datasets(self) -> list[Dataset]: ...

    def get_dataset(self, dataset_id: str) -> Dataset: ...

    def delete_dataset(self, dataset_id: str) -> None: ...

    def bind_document(self, document_id: str, dataset_id: str) -> None: ...

    def unbind_document(self, document_id: str) -> None: ...

    def get_dataset_id_for_document(self, document_id: str) -> str | None: ...

    def get_document_ids_for_dataset(self, dataset_id: str) -> list[str]: ...

    def get_dataset_document_count(self, dataset_id: str) -> int: ...


class DocumentCatalog(Protocol):
    def list_documents(self) -> list[IndexedDocument]: ...

    def get_document(self, document_id: str) -> IndexedDocument: ...


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
