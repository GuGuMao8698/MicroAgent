"""文档 ingestion 主流程。

该模块负责把保存文件、解析、归一化、切块、embedding 和索引写入串成一条
同步链路，并在失败时执行文档级回滚。同时提供异步任务接口（submit / process_task /
get_snapshot），支持幂等提交、阶段缓存和重试。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4

from ragflow_lite.application.services.pdf_payload_codec import (
    deserialize_parsed_pdf_document,
    fingerprint_parsed_pdf_document,
    serialize_parsed_pdf_document,
)
from ragflow_lite.application.services.text_normalization import (
    VISIBLE_TEXT_PATTERN,
    normalize_text_content,
)
from ragflow_lite.domain.errors import (
    EmptyDocumentError,
    IdempotencyKeyMissingError,
    ProcessingError,
    RagflowLiteError,
    UnsupportedFileTypeError,
)
from ragflow_lite.domain.models import (
    MAX_ATTEMPTS,
    STEP_BINDING,
    STEP_CHUNKING,
    STEP_EMBEDDING,
    STEP_GRAPH_EVIDENCE,
    STEP_INDEXING,
    STEP_NORMALIZING,
    STEP_PARSING,
    STEP_PROGRESS,
    TASK_FAILED,
    TASK_INDEXED,
    TASK_PROCESSING,
    TASK_QUEUED,
    Chunk,
    DocumentAsset,
    GraphEvidenceBatch,
    IngestionResult,
    IngestionTaskSnapshot,
    ParsedDocument,
    utc_now,
)
from ragflow_lite.domain.ports import (
    Chunker,
    DatasetStore,
    DocumentStore,
    Embedder,
    EvidenceExtractor,
    GraphEvidenceStore,
    IngestionStageCache,
    IngestionTaskRunner,
    IngestionTaskStore,
    Parser,
    VectorIndex,
)
from ragflow_lite.shared.observability import (
    log_event,
    record_ingest_outcome,
    record_ingest_stage_cache,
    record_ingest_task_accepted,
    record_ingest_task_duration,
    record_ingest_task_queue_delay,
    record_ingest_task_retry,
)

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
        document_filename=filename,
        file_type=file_type,
        **fields,
    )


def _log_academic_pdf_summary(summary: object) -> None:
    """记录 academic PDF ingestion 摘要事件。"""
    from ragflow_lite.domain.models import AcademicPdfIngestionSummary

    assert isinstance(summary, AcademicPdfIngestionSummary)
    level = logging.INFO if summary.status != "failed" else logging.ERROR
    log_event(logger, level, "academic_pdf_ingestion_summary", **asdict(summary))


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


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


ACADEMIC_PDF_CHUNK_SCHEMA_VERSION = "academic_schema_v1"


def _structured_payload_fingerprint(payload: object | None) -> str:
    from ragflow_lite.domain.models import ParsedPdfDocument as _PPD

    if not isinstance(payload, _PPD):
        return ""
    return fingerprint_parsed_pdf_document(payload)


def _reconstruct_structured_payload(serialized: str) -> object:
    """从 JSON 字符串重建 structured_payload 数据类实例。"""
    return deserialize_parsed_pdf_document(serialized)


@dataclass(frozen=True, slots=True)
class _ParsedDocumentCacheValue:
    raw_text: str
    metadata: dict[str, Any]
    structured_payload_serialized: str | None = None


@dataclass(frozen=True, slots=True)
class _ChunkCacheValue:
    text: str
    index: int
    metadata: dict[str, Any]


def _parsed_cache_fields(cached: Any) -> tuple[str, dict[str, Any]] | None:
    if isinstance(cached, ParsedDocument | _ParsedDocumentCacheValue):
        return cached.raw_text, dict(cached.metadata)
    return None


def _chunk_cache_fields(cached: Any) -> tuple[str, int, dict[str, Any]] | None:
    if isinstance(cached, Chunk | _ChunkCacheValue):
        return cached.text, cached.index, dict(cached.metadata)
    return None


class IngestionPipeline:
    """同步执行最小文档 ingestion 流程，同时支持异步任务接口。"""

    def __init__(
        self,
        document_store: DocumentStore,
        parser: Parser,
        chunker: Chunker,
        embedder: Embedder,
        vector_index: VectorIndex,
        normalizer: Normalizer,
        dataset_store: DatasetStore | None = None,
        task_store: IngestionTaskStore | None = None,
        stage_cache: IngestionStageCache | None = None,
        runner: IngestionTaskRunner | None = None,
        evidence_extractor: EvidenceExtractor | None = None,
        graph_store: GraphEvidenceStore | None = None,
        media_asset_store: Any | None = None,
        figure_describer: Any | None = None,
    ) -> None:
        self.document_store = document_store
        self.parser = parser
        self.chunker = chunker
        self.embedder = embedder
        self.vector_index = vector_index
        self.normalizer = normalizer
        self.dataset_store = dataset_store
        self.task_store = task_store
        self.stage_cache = stage_cache
        self.runner = runner
        self.evidence_extractor = evidence_extractor
        self.graph_store = graph_store
        self.media_asset_store = media_asset_store
        self.figure_describer = figure_describer

    # ------------------------------------------------------------------
    # Legacy synchronous interface
    # ------------------------------------------------------------------

    def ingest(
        self,
        filename: str,
        content: bytes,
        dataset_id: str | None = None,
    ) -> IngestionResult:
        """完成单个文档从上传内容到索引落盘的全流程。"""
        file_type = self._resolve_file_type(filename)
        document_id = f"doc_{uuid4().hex}"
        asset = None
        staged_assets = None

        parser_strategy = ""
        _log_ingest_event(
            logging.INFO,
            "ingest_started",
            document_id=document_id,
            filename=filename,
            file_type=file_type,
            outcome="started",
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

            # 阶段性写入：PDF media assets 暂存到 staging 目录
            staged_assets = self._stage_pdf_assets(
                document_id,
                parsed_document,
                filename,
            )

            # Gate B: VLM figure description before chunking
            self._apply_figure_descriptions(parsed_document, staged_assets)

            asset.metadata = _extract_doc_metadata(parsed_document.metadata)
            normalized_document = self._build_normalized_document(
                parsed_document,
                asset.filename,
            )
            chunks = self.chunker.chunk(normalized_document)

            # 学术 PDF 必须走学术分块路径，否则硬失败
            self._assert_academic_pdf_chunks(parsed_document, chunks)

            graph_evidence = self._extract_graph_evidence(chunks)
            self._maybe_log_academic_summary(
                parsed_document,
                chunks,
                document_id,
                cache_key=None,
            )
            embedded_chunks = self.embedder.embed_chunks(chunks)
            self.vector_index.index_document(asset, embedded_chunks)
            if graph_evidence is not None and self.graph_store is not None:
                self.graph_store.upsert_document_evidence(graph_evidence)

            # 在同一受控流程里完成 dataset 绑定
            if dataset_id is not None and self.dataset_store is not None:
                try:
                    self.dataset_store.bind_document(document_id, dataset_id)
                except Exception:
                    # 绑定失败时清理 binding，但不覆盖原始异常
                    self._rollback_binding(document_id)
                    raise

            # 下游写入（含 dataset binding）全部成功，提交暂存的 media assets
            if staged_assets is not None and self.media_asset_store is not None:
                self.media_asset_store.commit_assets(document_id, staged_assets)
                staged_assets = None

            result = IngestionResult(
                document_id=document_id,
                file_type=file_type,
                chunk_count=len(embedded_chunks),
                status="indexed",
                dataset_id=dataset_id,
            )
            _log_ingest_event(
                logging.INFO,
                "ingest_succeeded",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                outcome="succeeded",
                parser_strategy=parser_strategy,
                chunk_count=len(embedded_chunks),
            )
            record_ingest_outcome("succeeded", file_type)
            return result
        except RagflowLiteError as exc:
            # 回滚暂存的 media assets
            self._rollback_staged_assets(staged_assets, document_id, filename)
            # 只有文件已经落到受控存储后，才需要做文档级回滚。
            if asset is not None:
                self._rollback(document_id)
            _log_ingest_event(
                logging.ERROR,
                "ingest_failed",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            record_ingest_outcome("failed", file_type)
            raise
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
            self._rollback_staged_assets(staged_assets, document_id, filename)
            if asset is not None:
                self._rollback(document_id)
            _log_ingest_event(
                logging.ERROR,
                "ingest_failed",
                document_id=document_id,
                filename=filename,
                file_type=file_type,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            record_ingest_outcome("failed", file_type)
            raise ProcessingError("Failed to index document.") from exc

    # ------------------------------------------------------------------
    # Async task interface
    # ------------------------------------------------------------------

    def submit(
        self,
        idempotency_key: str,
        filename: str,
        content: bytes,
        dataset_id: str | None = None,
    ) -> IngestionTaskSnapshot:
        """提交一个 ingestion 任务，返回任务快照。

        幂等：相同 idempotency_key 不会创建新任务，而是返回已有快照。
        """
        if not idempotency_key or not idempotency_key.strip():
            raise IdempotencyKeyMissingError()
        if self.task_store is None or self.runner is None:
            raise ProcessingError("Async ingestion pipeline is not configured.")

        file_type = self._resolve_file_type(filename)
        now = utc_now()
        snapshot = IngestionTaskSnapshot(
            document_id=f"doc_{uuid4().hex}",
            idempotency_key=idempotency_key,
            status=TASK_QUEUED,
            step=None,
            progress_percent=0,
            attempt=1,
            file_type=file_type,
            dataset_id=dataset_id,
            chunk_count=None,
            error=None,
            filename=filename,
            created_at=now,
            updated_at=now,
        )
        reserved_snapshot, created = self.task_store.reserve(snapshot)
        if not created:
            return reserved_snapshot

        document_saved = False
        try:
            self.document_store.save_document(
                document_id=reserved_snapshot.document_id,
                filename=filename,
                file_type=file_type,
                content=content,
            )
            document_saved = True
            self.runner.submit(reserved_snapshot.document_id)
            record_ingest_task_accepted(file_type)
            current = self.task_store.get(reserved_snapshot.document_id)
            return current or reserved_snapshot
        except RagflowLiteError:
            if document_saved:
                self._rollback(reserved_snapshot.document_id)
            self.task_store.release(idempotency_key, reserved_snapshot.document_id)
            raise
        except Exception as exc:
            if document_saved:
                self._rollback(reserved_snapshot.document_id)
            self.task_store.release(idempotency_key, reserved_snapshot.document_id)
            raise ProcessingError("Failed to index document.") from exc

    def process_task(self, document_id: str) -> None:
        """处理一个已提交的任务，执行完整的处理流程。"""
        if self.task_store is None:
            raise ProcessingError("Task store not configured.")

        snapshot = self.task_store.get(document_id)
        if snapshot is None:
            raise ProcessingError(f"Task not found: {document_id}")

        # 记录队列延迟
        queue_delay = (utc_now() - snapshot.created_at).total_seconds()
        record_ingest_task_queue_delay(queue_delay)

        start_time = time.monotonic()
        file_type = snapshot.file_type
        staged_assets = None

        try:
            snapshot = replace(
                snapshot,
                status=TASK_PROCESSING,
                error=None,
                updated_at=utc_now(),
            )
            self.task_store.update(snapshot)

            # 从 document_store 读取原始文件

            asset = self._find_saved_asset(document_id, file_type, snapshot.filename)
            raw_bytes = self.document_store.read_document(asset)

            # Step: parsing
            snapshot = self._update_step(snapshot, STEP_PARSING)
            parse_cache_key = self._parse_cache_key(raw_bytes, file_type)
            parsed_document = self._cached_parse(
                parse_cache_key,
                asset,
                raw_bytes,
            )

            # 阶段性写入：PDF media assets 暂存到 staging 目录
            staged_assets = self._stage_pdf_assets(
                document_id,
                parsed_document,
                snapshot.filename,
            )

            # Gate B: VLM figure description before chunking
            self._apply_figure_descriptions(parsed_document, staged_assets)

            # Step: normalizing
            snapshot = self._update_step(snapshot, STEP_NORMALIZING)
            asset = replace(
                asset,
                filename=snapshot.filename,
                metadata=_extract_doc_metadata(parsed_document.metadata),
            )
            normalized_document = self._build_normalized_document(
                parsed_document,
                snapshot.filename,
            )

            # Step: chunking
            snapshot = self._update_step(snapshot, STEP_CHUNKING)
            chunk_cache_key = self._chunk_cache_key(normalized_document)
            chunks = self._cached_chunk(chunk_cache_key, normalized_document)

            # 学术 PDF 必须走学术分块路径，否则硬失败
            self._assert_academic_pdf_chunks(parsed_document, chunks)

            self._maybe_log_academic_summary(
                parsed_document,
                chunks,
                document_id,
                cache_key=chunk_cache_key,
            )

            # Step: graph evidence
            snapshot = self._update_step(snapshot, STEP_GRAPH_EVIDENCE)
            graph_evidence = self._extract_graph_evidence(chunks)

            # Step: embedding
            snapshot = self._update_step(snapshot, STEP_EMBEDDING)
            embedded_chunks = self.embedder.embed_chunks(chunks)

            # Step: indexing (never cached)
            snapshot = self._update_step(snapshot, STEP_INDEXING)
            self.vector_index.index_document(asset, embedded_chunks)
            if graph_evidence is not None and self.graph_store is not None:
                self.graph_store.upsert_document_evidence(graph_evidence)

            # Step: binding
            ds_id = snapshot.dataset_id
            if ds_id is not None and self.dataset_store is not None:
                snapshot = self._update_step(snapshot, STEP_BINDING)
                self.dataset_store.bind_document(document_id, ds_id)

            # 下游写入（含 dataset binding）全部成功，提交暂存的 media assets
            if staged_assets is not None and self.media_asset_store is not None:
                self.media_asset_store.commit_assets(document_id, staged_assets)
                staged_assets = None

            # Success
            snapshot = replace(
                snapshot,
                status=TASK_INDEXED,
                step=None,
                progress_percent=100,
                chunk_count=len(embedded_chunks),
                error=None,
                updated_at=utc_now(),
            )
            self.task_store.update(snapshot)

            duration = time.monotonic() - start_time
            record_ingest_task_duration("succeeded", duration)
            record_ingest_outcome("succeeded", file_type)

        except Exception as exc:
            duration = time.monotonic() - start_time
            record_ingest_task_duration("failed", duration)

            # 回滚暂存的 media assets
            self._rollback_staged_assets(
                staged_assets,
                document_id,
                snapshot.filename,
            )

            if snapshot.attempt < MAX_ATTEMPTS:
                if self.runner is None:
                    raise ProcessingError("Task runner not configured.") from exc
                record_ingest_task_retry(file_type)
                snapshot = replace(
                    snapshot,
                    status=TASK_QUEUED,
                    attempt=snapshot.attempt + 1,
                    error=str(exc),
                    updated_at=utc_now(),
                )
                self.task_store.update(snapshot)
                try:
                    self.runner.submit(document_id)
                except Exception as resubmit_exc:
                    snapshot = replace(
                        snapshot,
                        status=TASK_FAILED,
                        error=str(resubmit_exc),
                        updated_at=utc_now(),
                    )
                    self._rollback(document_id)
                    self.task_store.update(snapshot)
                    raise ProcessingError(
                        "Failed to reschedule document ingestion."
                    ) from resubmit_exc
                return
            else:
                # 已耗尽重试次数，标记失败并回滚
                snapshot = replace(
                    snapshot,
                    status=TASK_FAILED,
                    step=snapshot.step,
                    error=str(exc),
                    updated_at=utc_now(),
                )
                self._rollback(document_id)
                self.task_store.update(snapshot)
                raise

    def get_snapshot(self, document_id: str) -> IngestionTaskSnapshot | None:
        """获取任务快照，不存在则返回 None。"""
        if self.task_store is None:
            return None
        return self.task_store.get(document_id)

    # ------------------------------------------------------------------
    # Internal helpers for async pipeline
    # ------------------------------------------------------------------

    def _find_saved_asset(
        self, document_id: str, file_type: str, filename: str
    ) -> DocumentAsset:
        """Locate a previously saved document and rebuild its asset.

        For LocalDocumentStore (production), reads from uploads_dir on disk.
        For test doubles without uploads_dir, returns a minimal asset that
        relies on read_document() using document_id for lookup.
        """
        from pathlib import Path

        uploads_dir = getattr(self.document_store, "uploads_dir", None)
        if uploads_dir is not None:
            suffix = f".{file_type}"
            storage_path = uploads_dir / f"{document_id}{suffix}"
            if not storage_path.exists():
                # Fallback: search by prefix (in case suffix differs)
                matches = list(uploads_dir.glob(f"{document_id}.*"))
                if not matches:
                    raise ProcessingError(f"Saved file not found for {document_id}")
                storage_path = matches[0]
            return DocumentAsset(
                document_id=document_id,
                file_type=file_type,
                filename=filename,
                storage_path=storage_path,
                size_bytes=storage_path.stat().st_size,
            )

        return DocumentAsset(
            document_id=document_id,
            file_type=file_type,
            filename=filename,
            storage_path=Path(""),
            size_bytes=0,
        )

    def _extract_graph_evidence(self, chunks: list[Chunk]) -> GraphEvidenceBatch | None:
        if not chunks:
            return None
        if self.evidence_extractor is None or self.graph_store is None:
            return None
        return self.evidence_extractor.extract(chunks)

    def _maybe_log_academic_summary(
        self,
        parsed_document: ParsedDocument,
        chunks: list[Chunk],
        document_id: str,
        *,
        cache_key: str | None,
    ) -> None:
        """当文档包含 structured_payload 时记录 academic PDF 摘要。"""
        from ragflow_lite.domain.models import (
            AcademicPdfIngestionSummary,
            ParsedPdfDocument,
        )

        payload = parsed_document.structured_payload
        if not isinstance(payload, ParsedPdfDocument):
            return
        summary = AcademicPdfIngestionSummary(
            document_id=document_id,
            status="success",
            parser_strategy=payload.parser_strategy,
            parse_source="cold" if cache_key is None else "cached",
            structured_payload_present=True,
            structured_payload_fingerprint_present=True,
            chunker_strategy="academic_pdf",
            pdf_element_count=len(payload.elements),
            table_chunk_count=sum(
                1 for c in chunks if c.metadata.get("pdf_element_type") == "table"
            ),
            figure_chunk_count=sum(
                1 for c in chunks if c.metadata.get("pdf_element_type") == "figure"
            ),
        )
        _log_academic_pdf_summary(summary)

    def _update_step(
        self,
        snapshot: IngestionTaskSnapshot,
        step: str,
    ) -> IngestionTaskSnapshot:
        assert self.task_store is not None  # only called from process_task
        progress = STEP_PROGRESS.get(step, snapshot.progress_percent)
        snapshot = replace(
            snapshot,
            step=step,
            progress_percent=progress,
            updated_at=utc_now(),
        )
        self.task_store.update(snapshot)
        return snapshot

    def _parse_cache_key(self, raw_bytes: bytes, file_type: str) -> str:
        return f"parse:composite:{_sha256_hex(raw_bytes)}:{file_type}"

    def _chunk_cache_key(self, normalized_document: ParsedDocument) -> str:
        chunker = self.chunker
        parts = [
            type(chunker).__name__,
            str(chunker.chunk_size),
            str(chunker.chunk_overlap),
        ]
        if hasattr(chunker, "separators"):
            parts.append(str(tuple(chunker.separators)))
        chunker_fingerprint = ":".join(parts)
        relevant_metadata = json.dumps(
            normalized_document.metadata.get("page_spans", []),
            sort_keys=True,
        )
        result = (
            f"chunk:{chunker_fingerprint}"
            f":{_sha256_hex(normalized_document.raw_text.encode())}"
            f":{_sha256_hex(relevant_metadata.encode())}"
        )
        if normalized_document.structured_payload is not None:
            payload_parts = [
                str(normalized_document.metadata.get("parser_strategy", "")),
                ACADEMIC_PDF_CHUNK_SCHEMA_VERSION,
                _structured_payload_fingerprint(normalized_document.structured_payload),
            ]
            result += ":" + ":".join(payload_parts)
        return result

    def _cached_parse(
        self,
        cache_key: str,
        asset: Any,
        raw_bytes: bytes,
    ) -> ParsedDocument:
        if self.stage_cache is not None:
            cached = self.stage_cache.get(cache_key)
            if cached is not None:
                record_ingest_stage_cache("hit")
                return self._restore_cached_parse(asset, cached)

        parsed_document = self.parser.parse(asset, raw_bytes)

        if self.stage_cache is not None:
            from ragflow_lite.domain.models import (
                ParsedPdfDocument as _ParsedPdfDocument,
            )

            sp = parsed_document.structured_payload
            serialized: str | None = None
            if isinstance(sp, _ParsedPdfDocument):
                serialized = serialize_parsed_pdf_document(sp)
            self.stage_cache.put(
                cache_key,
                _ParsedDocumentCacheValue(
                    raw_text=parsed_document.raw_text,
                    metadata=dict(parsed_document.metadata),
                    structured_payload_serialized=serialized,
                ),
            )
        record_ingest_stage_cache("miss")

        return parsed_document

    def _cached_chunk(
        self,
        cache_key: str,
        normalized_document: ParsedDocument,
    ) -> list:
        if self.stage_cache is not None:
            cached = self.stage_cache.get(cache_key)
            if cached is not None:
                record_ingest_stage_cache("hit")
                return self._restore_cached_chunks(
                    normalized_document.document_id,
                    cached,
                )

        chunks = self.chunker.chunk(normalized_document)

        if self.stage_cache is not None:
            self.stage_cache.put(
                cache_key,
                [
                    _ChunkCacheValue(
                        text=chunk.text,
                        index=chunk.index,
                        metadata=dict(chunk.metadata),
                    )
                    for chunk in chunks
                ],
            )
        record_ingest_stage_cache("miss")

        return chunks

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _stage_pdf_assets(
        self,
        document_id: str,
        parsed_document: ParsedDocument,
        filename: str,
    ) -> Any | None:
        """暂存 PDF media assets 到 staging 目录，非 PDF 或无 assets 时返回 None。"""
        from ragflow_lite.domain.models import ParsedPdfDocument as _PPD

        if (
            self.media_asset_store is not None
            and isinstance(parsed_document.structured_payload, _PPD)
            and parsed_document.structured_payload.media_assets
        ):
            return self.media_asset_store.stage_assets(
                document_id,
                parsed_document.structured_payload.media_assets,
            )
        return None

    def _apply_figure_descriptions(
        self,
        parsed_document: ParsedDocument,
        staged_assets: Any | None,
    ) -> None:
        from ragflow_lite.domain.models import ParsedPdfDocument

        if self.figure_describer is None:
            return
        payload = parsed_document.structured_payload
        if not isinstance(payload, ParsedPdfDocument):
            return
        asset_paths = (
            getattr(staged_assets, "asset_paths", {})
            if staged_assets is not None
            else {}
        )
        for element in payload.elements:
            if element.element_type != "figure" or not element.media_asset_id:
                continue
            image_path = asset_paths.get(element.media_asset_id)
            if image_path is None:
                element.metadata["figure_description_status"] = "skipped"
                element.metadata["figure_description_error_type"] = "missing_asset"
                continue
            try:
                result = self.figure_describer.describe(
                    image_path=image_path,
                    caption=element.caption,
                    section_path=list(element.section_path),
                    paper_title=payload.title,
                )
            except Exception as exc:
                element.metadata["figure_description_status"] = "failed"
                element.metadata["figure_description_error_type"] = type(exc).__name__
                continue
            element.metadata["figure_description_status"] = str(
                getattr(result, "status", "failed")
            )
            if getattr(result, "description", None):
                element.metadata["visual_description"] = str(result.description)
            error_type = getattr(result, "error_type", None) or getattr(
                result, "skipped_reason", None
            )
            if error_type:
                element.metadata["figure_description_error_type"] = str(error_type)

    def _assert_academic_pdf_chunks(
        self,
        parsed_document: ParsedDocument,
        chunks: list[Chunk],
    ) -> None:
        from ragflow_lite.domain.models import ParsedPdfDocument

        if not isinstance(parsed_document.structured_payload, ParsedPdfDocument):
            return
        if any(c.metadata.get("chunker_strategy") != "academic_pdf" for c in chunks):
            raise ProcessingError("Academic PDF reached non-academic chunking path.")

    def _rollback_staged_assets(
        self,
        staged_assets: Any | None,
        document_id: str,
        filename: str,
    ) -> None:
        """回滚暂存的 media assets，失败时只记录日志。"""
        if staged_assets is not None and self.media_asset_store is not None:
            try:
                self.media_asset_store.rollback_staged_assets(staged_assets)
            except Exception:
                log_event(
                    logger,
                    logging.ERROR,
                    "pdf_media_asset_rollback_failed",
                    document_id=document_id,
                    document_filename=filename,
                )

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
            structured_payload=parsed_document.structured_payload,
        )

    def _restore_cached_parse(
        self,
        asset: DocumentAsset,
        cached: Any,
    ) -> ParsedDocument:
        payload = _parsed_cache_fields(cached)
        if payload is not None:
            raw_text, metadata = payload
            structured_payload = None
            serialized = getattr(cached, "structured_payload_serialized", None)
            if serialized is not None:
                structured_payload = _reconstruct_structured_payload(serialized)
            return ParsedDocument(
                document_id=asset.document_id,
                file_type=asset.file_type,
                raw_text=raw_text,
                metadata=metadata,
                structured_payload=structured_payload,
            )
        raise ProcessingError("Unexpected parse cache payload.")

    def _restore_cached_chunks(
        self,
        document_id: str,
        cached: Any,
    ) -> list[Chunk]:
        if cached == []:
            return []

        restored: list[Chunk] = []

        if isinstance(cached, list):
            for entry in cached:
                payload = _chunk_cache_fields(entry)
                if payload is None:
                    continue

                text, index, metadata = payload
                restored.append(
                    Chunk(
                        chunk_id=f"chunk_{document_id}_{index}",
                        document_id=document_id,
                        text=text,
                        index=index,
                        metadata=metadata,
                    )
                )

        if restored:
            return restored

        raise ProcessingError("Unexpected chunk cache payload.")

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
        if self.graph_store is not None:
            self._rollback_step(
                document_id,
                "graph_evidence",
                self.graph_store.delete_document,
            )
        self._rollback_binding(document_id)

    def _rollback_binding(self, document_id: str) -> None:
        """Best-effort 清理 dataset binding。"""
        if self.dataset_store is None:
            return
        self._rollback_step(
            document_id,
            "dataset_binding",
            self.dataset_store.unbind_document,
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
