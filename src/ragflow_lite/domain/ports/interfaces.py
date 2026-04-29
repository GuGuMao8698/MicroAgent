from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ragflow_lite.domain.models import (
    AnswerRequest,
    AnswerResult,
    Chunk,
    Dataset,
    DocumentAsset,
    EmbeddedChunk,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    GroundedQuery,
    IndexedDocument,
    IngestionTaskSnapshot,
    ParsedDocument,
    RetrievedChunk,
    TopologyRetrievalResult,
)

# ---------------------------------------------------------------------------
# Async ingestion internal contracts
# ---------------------------------------------------------------------------


class IngestionTaskStore(Protocol):
    """任务快照的存储契约（第一版为单进程内存实现）。"""

    def create(self, snapshot: IngestionTaskSnapshot) -> IngestionTaskSnapshot: ...

    def reserve(
        self,
        snapshot: IngestionTaskSnapshot,
    ) -> tuple[IngestionTaskSnapshot, bool]: ...

    def release(self, idempotency_key: str, document_id: str) -> None: ...

    def get(self, document_id: str) -> IngestionTaskSnapshot | None: ...

    def get_by_idempotency_key(self, key: str) -> IngestionTaskSnapshot | None: ...

    def update(self, snapshot: IngestionTaskSnapshot) -> IngestionTaskSnapshot: ...


class IngestionStageCache(Protocol):
    """阶段产物缓存契约（只缓存 parse 和 chunk 结果）。"""

    def get(self, key: str) -> Any | None: ...

    def put(self, key: str, value: Any) -> None: ...


class IngestionTaskRunner(Protocol):
    """任务执行器契约（第一版为应用内 executor）。"""

    def submit(self, document_id: str) -> None: ...


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


class EvidenceExtractor(Protocol):
    def extract(self, chunks: list[Chunk]) -> GraphEvidenceBatch: ...


class GraphEvidenceStore(Protocol):
    def upsert_document_evidence(
        self,
        batch: GraphEvidenceBatch,
    ) -> GraphEvidenceWriteResult: ...

    def delete_document(self, document_id: str) -> None: ...

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None: ...


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


class QueryGrounder(Protocol):
    def ground(self, query: str) -> GroundedQuery: ...


class ChunkLookup(Protocol):
    def get_chunks(self, chunk_ids: list[str]) -> list[RetrievedChunk]: ...


class TopologyContextRetriever(Protocol):
    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult: ...


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


class Answerer(Protocol):
    def answer(self, request: AnswerRequest) -> AnswerResult: ...
