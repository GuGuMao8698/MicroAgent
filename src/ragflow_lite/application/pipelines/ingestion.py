"""文档 ingestion 主流程。

该模块负责把保存文件、解析、归一化、切块、embedding 和索引写入串成一条
同步链路，并在失败时执行文档级回滚。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from ragflow_lite.application.services.text_normalization import (
    VISIBLE_TEXT_PATTERN,
    normalize_text_content,
)
from ragflow_lite.domain.errors import (
    EmptyDocumentError,
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
from ragflow_lite.shared.observability import log_event

Normalizer = Callable[[str, str], str]

SUPPORTED_FILE_TYPES = {".txt": "txt", ".md": "md", ".pdf": "pdf"}

# 顶层已有字段和 chunk/派生字段，不应写入文档级 metadata。
_EXCLUDED_DOC_METADATA_KEYS = frozenset(
    {
        "filename",
        "file_type",
        "normalized",
        "start_offset",
        "end_offset",
        "page_texts",
        "page_spans",
    }
)

logger = logging.getLogger(__name__)


def _log_ingest_event(
    level: int,
    event: str,
    document_id: str,
    filename: str,
    file_type: str,
    **fields: Any,
) -> None:
    log_event(
        logger,
        level,
        event,
        document_id=document_id,
        filename=filename,
        file_type=file_type,
        **fields,
    )


def _extract_doc_metadata(parser_metadata: dict[str, Any]) -> dict[str, Any]:
    """从 parser metadata 中提取文档级 extras，去掉顶层已有和 chunk/派生字段。"""
    return {
        k: v for k, v in parser_metadata.items() if k not in _EXCLUDED_DOC_METADATA_KEYS
    }


def _build_page_spans(
    page_texts: list[dict[str, Any]],
) -> tuple[str, list[dict[str, int]]]:
    """对 PDF 逐页文本分别规范化，拼接后返回归一化全文和页区间映射。

    Returns:
        ``(normalized_text, page_spans)`` 其中 ``page_spans`` 为半开区间
        ``[start, end)`` 列表，与返回的 ``normalized_text`` 对齐。
    """
    normalized_pages: list[dict[str, Any]] = []
    for entry in page_texts:
        norm = normalize_text_content(entry["text"])
        if norm and VISIBLE_TEXT_PATTERN.search(norm):
            normalized_pages.append({"page_number": entry["page_number"], "text": norm})

    parts: list[str] = []
    spans: list[dict[str, int]] = []
    offset = 0
    for page in normalized_pages:
        text = page["text"]
        start = offset
        end = start + len(text)
        spans.append({"start": start, "end": end, "page_number": page["page_number"]})
        parts.append(text)
        offset = end + 2  # "\n\n" separator

    return "\n\n".join(parts), spans


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

        parser_strategy = ""
        _log_ingest_event(
            logging.INFO,
            "ingest_started",
            document_id=document_id,
            filename=filename,
            file_type=file_type,
        )

        try:
            asset = self.document_store.save_document(
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                content=content,
            )
            raw_bytes = self.document_store.read_document(asset)
            parsed_document = self.parser.parse(asset, raw_bytes)
            parser_strategy = parsed_document.metadata.get("parser_strategy", "")
            asset.metadata = _extract_doc_metadata(parsed_document.metadata)
            normalized_document = self._build_normalized_document(
                parsed_document,
                asset.filename,
            )
            chunks = self.chunker.chunk(normalized_document)
            embedded_chunks = self.embedder.embed_chunks(chunks)
            self.vector_index.index_document(asset, embedded_chunks)
            result = IngestionResult(
                document_id=document_id,
                file_type=file_type,
                chunk_count=len(embedded_chunks),
                status="indexed",
            )
            _log_ingest_event(
                logging.INFO,
                "ingest_succeeded",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                parser_strategy=parser_strategy,
                chunk_count=len(embedded_chunks),
            )
            return result
        except RagflowLiteError:
            # 只有文件已经落到受控存储后，才需要做文档级回滚。
            if asset is not None:
                self._rollback(document_id)
            _log_ingest_event(
                logging.ERROR,
                "ingest_failed",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
            )
            raise
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
            if asset is not None:
                self._rollback(document_id)
            _log_ingest_event(
                logging.ERROR,
                "ingest_failed",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
            )
            raise ProcessingError("Failed to index document.") from exc

    def _build_normalized_document(
        self, parsed_document: ParsedDocument, filename: str
    ) -> ParsedDocument:
        """归一化文本，并补齐 chunking 所需的派生 metadata。"""
        normalized_text, derived_metadata = self._normalize_content(
            parsed_document, filename
        )
        metadata = _extract_doc_metadata(parsed_document.metadata)
        metadata["normalized"] = True
        metadata.update(derived_metadata)
        return ParsedDocument(
            document_id=parsed_document.document_id,
            file_type=parsed_document.file_type,
            raw_text=normalized_text,
            metadata=metadata,
        )

    def _normalize_content(
        self, parsed_document: ParsedDocument, filename: str
    ) -> tuple[str, dict[str, Any]]:
        """归一化文本；PDF 逐页归一化并返回 page_spans，其他类型走原始路径。"""
        page_texts = parsed_document.metadata.get("page_texts")
        if page_texts:
            normalized_text, page_spans = _build_page_spans(page_texts)
            if not VISIBLE_TEXT_PATTERN.search(normalized_text):
                raise EmptyDocumentError(filename)
            return normalized_text, {"page_spans": page_spans}

        return self.normalizer(parsed_document.raw_text, filename), {}

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
        """Best-effort 回滚：分别尝试清理 vector_index 和 document_store。

        任一步骤失败时记录日志但不覆盖原始异常。
        """
        self._rollback_step(
            document_id,
            "vector_index",
            self.vector_index.delete_document,
        )
        self._rollback_step(
            document_id,
            "document_store",
            self.document_store.delete_document,
        )

    def _rollback_step(
        self,
        document_id: str,
        step_name: str,
        delete_fn: Callable[[str], None],
    ) -> None:
        try:
            delete_fn(document_id)
        except Exception:
            log_event(
                logger,
                logging.ERROR,
                "rollback_failed",
                document_id=document_id,
                step=step_name,
            )
