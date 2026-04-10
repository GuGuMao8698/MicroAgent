from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ragflow_lite.application.pipelines.ingestion import (
    IngestionPipeline,
    _build_page_spans,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    DocumentAsset,
    EmbeddedChunk,
    ParsedDocument,
)
from ragflow_lite.shared.observability import (
    bind_request_context,
    clear_request_context,
)

INGESTION_LOGGER = "ragflow_lite.application.pipelines.ingestion"


def test_build_page_spans_joins_normalized_pages() -> None:
    page_texts = [
        {"page_number": 1, "text": "Hello world"},
        {"page_number": 2, "text": "Foo bar"},
    ]

    text, spans = _build_page_spans(page_texts)

    assert text == "Hello world\n\nFoo bar"
    assert spans == [
        {"start": 0, "end": 11, "page_number": 1},
        {"start": 13, "end": 20, "page_number": 2},
    ]


def test_build_page_spans_skips_empty_normalized_page() -> None:
    page_texts = [
        {"page_number": 1, "text": "Content"},
        {"page_number": 2, "text": "   \n\t  "},
        {"page_number": 3, "text": "More content"},
    ]

    text, spans = _build_page_spans(page_texts)

    assert text == "Content\n\nMore content"
    assert len(spans) == 2
    assert spans[0]["page_number"] == 1
    assert spans[1]["page_number"] == 3


def test_build_page_spans_normalizes_each_page() -> None:
    page_texts = [
        {"page_number": 1, "text": "Hello\x00\r\n\r\n\r\nWorld"},
    ]

    text, spans = _build_page_spans(page_texts)

    assert text == "Hello\n\nWorld"
    assert spans[0]["end"] == len(text)


def test_build_page_spans_returns_empty_when_all_pages_blank() -> None:
    page_texts = [
        {"page_number": 1, "text": "   "},
        {"page_number": 2, "text": "\n\n"},
    ]

    text, spans = _build_page_spans(page_texts)

    assert text == ""
    assert spans == []


# ---------------------------------------------------------------------------
# Pipeline rollback fidelity tests
# ---------------------------------------------------------------------------


def _make_asset(document_id: str = "doc_abc") -> DocumentAsset:
    return DocumentAsset(
        document_id=document_id,
        filename="test.txt",
        file_type="txt",
        storage_path=Path("/tmp/test.txt"),
        size_bytes=10,
    )


@dataclass
class _FakeDocumentStore:
    should_fail_delete: bool = False
    delete_calls: int = 0

    def save_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        content: bytes,
    ) -> DocumentAsset:
        return _make_asset(document_id)

    def read_document(self, asset: DocumentAsset) -> bytes:
        return b"hello"

    def delete_document(self, document_id: str) -> None:
        self.delete_calls += 1
        if self.should_fail_delete:
            raise RuntimeError("store delete failed")

    def path_for(self, document_id: str, suffix: str) -> Path:
        return Path("/tmp") / f"{document_id}.{suffix}"


@dataclass
class _FakeParser:
    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text="parsed text",
            metadata={"parser_strategy": "plain_text"},
        )


@dataclass
class _FakeChunker:
    def chunk(self, document: ParsedDocument) -> list[Any]:
        return []


@dataclass
class _FakeEmbedder:
    def embed_chunks(self, chunks: list[Any]) -> list[EmbeddedChunk]:
        return []


@dataclass
class _FakeVectorIndex:
    should_fail_delete: bool = False
    delete_calls: int = 0

    def index_document(self, asset: DocumentAsset, chunks: list[EmbeddedChunk]) -> None:
        pass

    def delete_document(self, document_id: str) -> None:
        self.delete_calls += 1
        if self.should_fail_delete:
            raise RuntimeError("index delete failed")


def _build_pipeline(
    vector_index: _FakeVectorIndex | None = None,
    document_store: _FakeDocumentStore | None = None,
    normalizer: Any | None = None,
) -> IngestionPipeline:
    return IngestionPipeline(
        document_store=document_store or _FakeDocumentStore(),
        parser=_FakeParser(),
        chunker=_FakeChunker(),
        embedder=_FakeEmbedder(),
        vector_index=vector_index or _FakeVectorIndex(),
        normalizer=normalizer or (lambda text, filename: text),
    )


def _raising_normalizer(error: Exception):
    def _raise(text: str, filename: str) -> str:
        raise error

    return _raise


def _event_names(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records]


def test_rollback_both_steps_attempted_when_pipeline_fails() -> None:
    """When the pipeline fails after save, both rollback steps should be attempted."""
    vector_index = _FakeVectorIndex()
    document_store = _FakeDocumentStore()
    pipeline = _build_pipeline(
        vector_index=vector_index,
        document_store=document_store,
        normalizer=_raising_normalizer(ProcessingError("main failure")),
    )

    with pytest.raises(ProcessingError, match="main failure"):
        pipeline.ingest("test.txt", b"hello")

    assert vector_index.delete_calls == 1
    assert document_store.delete_calls == 1


def test_rollback_failure_does_not_suppress_original_exception() -> None:
    """When rollback also fails, the original exception should still be raised."""
    vector_index = _FakeVectorIndex(should_fail_delete=True)
    document_store = _FakeDocumentStore(should_fail_delete=True)
    pipeline = _build_pipeline(
        vector_index=vector_index,
        document_store=document_store,
        normalizer=_raising_normalizer(ProcessingError("original error")),
    )

    with pytest.raises(ProcessingError, match="original error"):
        pipeline.ingest("test.txt", b"hello")

    # Both rollback steps were still attempted
    assert vector_index.delete_calls == 1
    assert document_store.delete_calls == 1


def test_rollback_failure_logs_per_step(caplog: pytest.LogCaptureFixture) -> None:
    """Each failed rollback step should produce its own rollback_failed log."""
    vector_index = _FakeVectorIndex(should_fail_delete=True)
    document_store = _FakeDocumentStore(should_fail_delete=True)
    pipeline = _build_pipeline(
        vector_index=vector_index,
        document_store=document_store,
        normalizer=_raising_normalizer(ProcessingError("boom")),
    )

    with caplog.at_level(logging.ERROR, logger=INGESTION_LOGGER):
        with pytest.raises(ProcessingError):
            pipeline.ingest("test.txt", b"hello")

    rollback_logs = [r for r in caplog.records if r.event == "rollback_failed"]
    assert len(rollback_logs) == 2
    steps = {r.step for r in rollback_logs}
    assert steps == {"vector_index", "document_store"}


def test_ingest_logs_started_and_succeeded_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = _build_pipeline()

    with caplog.at_level(logging.INFO, logger=INGESTION_LOGGER):
        result = pipeline.ingest("test.txt", b"hello")

    assert "ingest_started" in _event_names(caplog)
    assert "ingest_succeeded" in _event_names(caplog)
    assert result.status == "indexed"


def test_ingest_logs_failed_on_domain_error(caplog: pytest.LogCaptureFixture) -> None:
    pipeline = _build_pipeline(
        normalizer=_raising_normalizer(ProcessingError("domain failure")),
    )

    with caplog.at_level(logging.INFO, logger=INGESTION_LOGGER):
        with pytest.raises(ProcessingError):
            pipeline.ingest("test.txt", b"hello")

    assert "ingest_started" in _event_names(caplog)
    assert "ingest_failed" in _event_names(caplog)


def test_ingest_logs_trace_id_request_id_and_outcome(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = _build_pipeline(
        normalizer=_raising_normalizer(ProcessingError("domain failure")),
    )
    bind_request_context("trace-ingest-1")

    try:
        with caplog.at_level(logging.INFO, logger=INGESTION_LOGGER):
            with pytest.raises(ProcessingError):
                pipeline.ingest("test.txt", b"hello")
    finally:
        clear_request_context()

    failed_record = next(record for record in caplog.records if record.event == "ingest_failed")
    assert failed_record.trace_id == "trace-ingest-1"
    assert failed_record.request_id
    assert failed_record.outcome == "failed"
    assert failed_record.error_type == "ProcessingError"
