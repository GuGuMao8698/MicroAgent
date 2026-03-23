"""文档 ingestion 主流程。

该模块负责把保存文件、解析、归一化、切块、embedding 和索引写入串成一条
同步链路，并在失败时执行文档级回滚。
"""

from __future__ import annotations

from typing import Callable
from uuid import uuid4

from ragflow_lite.domain.errors import (
    ProcessingError,
    RagflowLiteError,
    UnsupportedFileTypeError,
)
from ragflow_lite.domain.models import IngestionResult, ParsedDocument
from ragflow_lite.domain.ports import (
    Chunker,
    DocumentStore,
    Embedder,
    Parser,
    VectorIndex,
)

Normalizer = Callable[[str, str], str]

SUPPORTED_FILE_TYPES = {".txt": "txt", ".md": "md"}


class IngestionPipeline:
    """同步执行最小文档 ingestion 流程。"""

    def __init__(
        self,
        document_store: DocumentStore,
        parser: Parser,
        chunker: Chunker,
        embedder: Embedder,
        vector_index: VectorIndex,
        normalizer: Normalizer,
    ) -> None:
        self.document_store = document_store
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.vector_index = vector_index
        self.normalizer = normalizer

    def ingest(self, filename: str, content: bytes) -> IngestionResult:
        """完成单个文档从上传内容到索引落盘的全流程。"""
        file_type = self._resolve_file_type(filename)
        document_id = f"doc_{uuid4().hex}"
        asset = None

        try:
            asset = self.document_store.save_document(
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                content=content,
            )
            raw_bytes = self.document_store.read_document(asset)
            parsed_document = self.parser.parse(asset, raw_bytes)
            normalized_text = self.normalizer(parsed_document.raw_text, asset.filename)
            normalized_document = ParsedDocument(
                document_id=parsed_document.document_id,
                file_type=parsed_document.file_type,
                raw_text=normalized_text,
                metadata={**parsed_document.metadata, "normalized": True},
            )
            chunks = self.chunker.chunk(normalized_document)
            embedded_chunks = self.embedder.embed_chunks(chunks)
            self.vector_index.index_document(asset, embedded_chunks)
            return IngestionResult(
                document_id=document_id,
                file_type=file_type,
                chunk_count=len(embedded_chunks),
                status="indexed",
            )
        except RagflowLiteError:
            # 只有文件已经落到受控存储后，才需要做文档级回滚。
            if asset is not None:
                self._rollback(document_id)
            raise
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
            if asset is not None:
                self._rollback(document_id)
            raise ProcessingError("Failed to index document.") from exc

    def _resolve_file_type(self, filename: str) -> str:
        """根据文件名后缀映射到当前支持的文档类型。"""
        normalized_name = (filename or "").strip()
        suffix = ""
        if "." in normalized_name:
            suffix = normalized_name[normalized_name.rfind(".") :].lower()

        file_type = SUPPORTED_FILE_TYPES.get(suffix)
        if file_type is None:
            raise UnsupportedFileTypeError(filename or "<unknown>")
        return file_type

    def _rollback(self, document_id: str) -> None:
        """回滚当前文档在本次 ingestion 中产生的持久化副作用。"""
        self.vector_index.delete_document(document_id)
        self.document_store.delete_document(document_id)
