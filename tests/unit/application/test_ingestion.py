from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest

from ragflow_lite.application.pipelines.ingestion import (
    IngestionPipeline,
    _build_page_spans,
)
from ragflow_lite.domain.errors import (
    ProcessingError,
)
from ragflow_lite.domain.models import (
    STEP_CHUNKING,
    STEP_EMBEDDING,
    STEP_INDEXING,
    STEP_NORMALIZING,
    STEP_PARSING,
    STEP_PROGRESS,
    TASK_FAILED,
    TASK_INDEXED,
    TASK_QUEUED,
    Chunk,
    DocumentAsset,
    EmbeddedChunk,
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    IngestionTaskSnapshot,
    ParsedDocument,
    RelationEvidence,
)
from ragflow_lite.infrastructure.chunkers import (
    FixedWindowChunker,
    RecursiveCharacterChunker,
)
from ragflow_lite.infrastructure.ingestion.memory import InMemoryTaskStore
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
    save_calls: int = 0
    _saved: dict = field(default_factory=dict)  # document_id -> bytes
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def save_document(
        self,
        document_id: str,
        filename: str,
        file_type: str,
        content: bytes,
    ) -> DocumentAsset:
        with self._lock:
            self.save_calls += 1
            self._saved[document_id] = content
        return _make_asset(document_id)

    def read_document(self, asset: DocumentAsset) -> bytes:
        with self._lock:
            return self._saved.get(asset.document_id, b"hello")

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
    chunk_size: int = 500
    chunk_overlap: int = 50

    def chunk(self, document: ParsedDocument) -> list[Any]:
        return []


@dataclass
class _ProducingChunker:
    """Chunker that yields a single chunk so downstream consumers see real chunk_ids."""

    chunk_size: int = 500
    chunk_overlap: int = 50

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        return [
            Chunk(
                chunk_id=f"chunk_{document.document_id}_0",
                document_id=document.document_id,
                text=document.raw_text,
                index=0,
                metadata={},
            )
        ]


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
    chunker: Any | None = None,
) -> IngestionPipeline:
    return IngestionPipeline(
        document_store=document_store or _FakeDocumentStore(),
        parser=_FakeParser(),
        chunker=chunker or _FakeChunker(),
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

    failed_record = next(
        record for record in caplog.records if record.event == "ingest_failed"
    )
    assert failed_record.trace_id == "trace-ingest-1"
    assert failed_record.request_id
    assert failed_record.outcome == "failed"
    assert failed_record.error_type == "ProcessingError"


# ===========================================================================
# Async ingestion task test infrastructure
# ===========================================================================


@dataclass
class _FakeTaskStore:
    _tasks: dict = field(default_factory=dict)  # document_id -> snapshot
    _idempotency: dict = field(default_factory=dict)  # key -> document_id
    updates: list = field(default_factory=list)  # all snapshots from update() calls
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def create(self, snapshot: IngestionTaskSnapshot) -> IngestionTaskSnapshot:
        with self._lock:
            self._tasks[snapshot.document_id] = snapshot
            self._idempotency[snapshot.idempotency_key] = snapshot.document_id
        return snapshot

    def reserve(
        self,
        snapshot: IngestionTaskSnapshot,
    ) -> tuple[IngestionTaskSnapshot, bool]:
        with self._lock:
            existing_document_id = self._idempotency.get(snapshot.idempotency_key)
            if existing_document_id is not None:
                existing = self._tasks.get(existing_document_id)
                if existing is not None:
                    return existing, False
                self._idempotency.pop(snapshot.idempotency_key, None)

            self._tasks[snapshot.document_id] = snapshot
            self._idempotency[snapshot.idempotency_key] = snapshot.document_id
            return snapshot, True

    def release(self, idempotency_key: str, document_id: str) -> None:
        with self._lock:
            if self._idempotency.get(idempotency_key) == document_id:
                self._idempotency.pop(idempotency_key, None)
            self._tasks.pop(document_id, None)

    def get(self, document_id: str) -> IngestionTaskSnapshot | None:
        with self._lock:
            return self._tasks.get(document_id)

    def get_by_idempotency_key(self, key: str) -> IngestionTaskSnapshot | None:
        with self._lock:
            doc_id = self._idempotency.get(key)
            if doc_id is None:
                return None
            return self._tasks.get(doc_id)

    def update(self, snapshot: IngestionTaskSnapshot) -> IngestionTaskSnapshot:
        with self._lock:
            self._tasks[snapshot.document_id] = snapshot
            self.updates.append(snapshot)
        return snapshot


@dataclass
class _FakeStageCache:
    _entries: dict = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        return self._entries.get(key)

    def put(self, key: str, value: Any) -> None:
        self._entries[key] = value


@dataclass
class _FakeRunner:
    submitted: list = field(default_factory=list)

    def submit(self, document_id: str) -> None:
        self.submitted.append(document_id)


@dataclass
class _FakeDatasetStore:
    bind_calls: list = field(default_factory=list)

    def bind_document(self, document_id: str, dataset_id: str) -> None:
        self.bind_calls.append((document_id, dataset_id))

    def unbind_document(self, document_id: str) -> None:
        pass


def _build_async_pipeline(
    *,
    parser: Any | None = None,
    chunker: Any | None = None,
    embedder: Any | None = None,
    vector_index: Any | None = None,
    document_store: Any | None = None,
    normalizer: Any | None = None,
    dataset_store: Any | None = None,
    task_store: Any | None = None,
    runner: Any | None = None,
) -> tuple[IngestionPipeline, _FakeTaskStore, _FakeStageCache, _FakeRunner]:
    """Build a pipeline with async infrastructure fakes. Returns (pipeline, task_store, stage_cache, runner)."""
    task_store = task_store or _FakeTaskStore()
    stage_cache = _FakeStageCache()
    runner = runner or _FakeRunner()
    pipeline = IngestionPipeline(
        document_store=document_store or _FakeDocumentStore(),
        parser=parser or _FakeParser(),
        chunker=chunker or _FakeChunker(),
        embedder=embedder or _FakeEmbedder(),
        vector_index=vector_index or _FakeVectorIndex(),
        normalizer=normalizer or (lambda text, filename: text),
        dataset_store=dataset_store,
        task_store=task_store,
        stage_cache=stage_cache,
        runner=runner,
    )
    return pipeline, task_store, stage_cache, runner


# ===========================================================================
# Group 1: Success state sequence (queued -> processing -> indexed)
# ===========================================================================


class TestSubmitCreatesQueuedTask:
    def test_submit_creates_queued_snapshot(self):
        """submit() should create a task with status=queued and persist raw upload."""
        pipeline, task_store, stage_cache, runner = _build_async_pipeline()
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
            dataset_id=None,
        )
        assert snapshot.status == TASK_QUEUED
        assert snapshot.progress_percent == 0
        assert snapshot.step is None
        assert snapshot.document_id.startswith("doc_")
        assert runner.submitted == [snapshot.document_id]

    def test_submit_returns_snapshot(self):
        """submit() should return the IngestionTaskSnapshot."""
        pipeline, task_store, stage_cache, runner = _build_async_pipeline()
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        assert isinstance(snapshot, IngestionTaskSnapshot)
        assert snapshot.idempotency_key == "key-1"

    def test_submit_failure_releases_idempotency_reservation(self):
        """A submit-time failure must not leave the idempotency key stuck."""

        @dataclass
        class _FailingRunner:
            def submit(self, document_id: str) -> None:
                raise RuntimeError("queue unavailable")

        task_store = InMemoryTaskStore()
        pipeline, _, _, _ = _build_async_pipeline(
            task_store=task_store,
            runner=_FailingRunner(),
        )

        with pytest.raises(ProcessingError, match="Failed to index document."):
            pipeline.submit(
                idempotency_key="key-1",
                filename="test.txt",
                content=b"hello",
            )

        assert task_store.get_by_idempotency_key("key-1") is None


class TestProcessTaskTransitions:
    def test_process_task_queued_to_processing_to_indexed(self):
        """process_task() should transition queued -> processing -> indexed."""
        pipeline, task_store, _, _ = _build_async_pipeline()
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id
        pipeline.process_task(doc_id)

        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_INDEXED
        assert final.progress_percent == 100
        assert final.document_id == doc_id

    def test_process_task_updates_steps(self):
        """process_task() should update step through all processing stages."""
        pipeline, task_store, _, _ = _build_async_pipeline()
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id
        pipeline.process_task(doc_id)

        # Check intermediate snapshots captured via update() calls
        updated_steps = [s.step for s in task_store.updates]
        assert STEP_PARSING in updated_steps
        assert STEP_NORMALIZING in updated_steps
        assert STEP_CHUNKING in updated_steps
        assert STEP_EMBEDDING in updated_steps
        assert STEP_INDEXING in updated_steps

        # Final snapshot: step=None, status=indexed
        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_INDEXED
        assert final.step is None

    def test_process_task_with_dataset_binding(self):
        """process_task() should bind dataset if dataset_id is set."""
        ds_store = _FakeDatasetStore()
        pipeline, task_store, _, _ = _build_async_pipeline(dataset_store=ds_store)
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
            dataset_id="ds-001",
        )
        doc_id = snapshot.document_id
        pipeline.process_task(doc_id)

        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_INDEXED
        assert ds_store.bind_calls == [(doc_id, "ds-001")]

    def test_process_task_persists_graph_evidence(self) -> None:
        extractor = _FakeEvidenceExtractor()
        graph_store = _FakeGraphEvidenceStore()
        pipeline, task_store, _, runner = _build_async_pipeline(
            chunker=_ProducingChunker(),
        )
        pipeline.evidence_extractor = extractor
        pipeline.graph_store = graph_store
        snapshot = pipeline.submit(
            idempotency_key="key-graph",
            filename="graph.txt",
            content=b"graph content",
        )

        pipeline.process_task(snapshot.document_id)

        final = task_store.get(snapshot.document_id)
        assert final is not None
        assert final.status == TASK_INDEXED
        assert extractor.calls == 1
        assert graph_store.upserts[0].document_id == snapshot.document_id
        assert graph_store.upserts[0].relations[0].source_chunk_ids


# ===========================================================================
# Group 2: Idempotency
# ===========================================================================


class TestIdempotency:
    def test_same_idempotency_key_returns_same_document_id(self):
        """Duplicate idempotency key returns existing task, doesn't create new one."""
        pipeline, _, _, runner = _build_async_pipeline()
        s1 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        s2 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        assert s1.document_id == s2.document_id
        # Runner should only have been called once (for the first submit)
        assert len(runner.submitted) == 1

    def test_idempotency_returns_current_snapshot(self):
        """Duplicate submission returns current task state, not initial state."""
        pipeline, task_store, _, _ = _build_async_pipeline()
        s1 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        doc_id = s1.document_id

        # Process to completion
        pipeline.process_task(doc_id)

        # Submit again with same key
        s2 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        assert s2.status == TASK_INDEXED
        assert s2.document_id == doc_id

    def test_different_idempotency_keys_create_different_tasks(self):
        """Different keys create different tasks."""
        pipeline, _, _, runner = _build_async_pipeline()
        s1 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        s2 = pipeline.submit(idempotency_key="key-2", filename="test.txt", content=b"b")
        assert s1.document_id != s2.document_id
        assert len(runner.submitted) == 2

    def test_concurrent_same_idempotency_key_reserves_once(self):
        """Concurrent submits with the same key must reuse one reservation."""

        @dataclass
        class _BlockingDocumentStore(_FakeDocumentStore):
            entered: threading.Event = field(default_factory=threading.Event)
            release: threading.Event = field(default_factory=threading.Event)

            def save_document(self, document_id, filename, file_type, content):
                self.entered.set()
                self.release.wait(timeout=2)
                return super().save_document(document_id, filename, file_type, content)

        document_store = _BlockingDocumentStore()
        runner = _FakeRunner()
        pipeline, task_store, _, _ = _build_async_pipeline(
            document_store=document_store,
            task_store=InMemoryTaskStore(),
            runner=runner,
        )
        snapshots: list[IngestionTaskSnapshot] = []

        def _submit() -> None:
            snapshots.append(
                pipeline.submit(
                    idempotency_key="same-key",
                    filename="test.txt",
                    content=b"hello",
                )
            )

        first = threading.Thread(target=_submit)
        second = threading.Thread(target=_submit)
        first.start()
        assert document_store.entered.wait(timeout=2)
        second.start()
        second.join(timeout=2)
        document_store.release.set()
        first.join(timeout=2)

        assert len(snapshots) == 2
        assert snapshots[0].document_id == snapshots[1].document_id
        assert document_store.save_calls == 1
        assert len(runner.submitted) == 1
        assert task_store.get(snapshots[0].document_id) is not None


# ===========================================================================
# Group 3: Idempotency before retry
# ===========================================================================


class TestIdempotencyBeforeRetry:
    def test_duplicate_submit_does_not_use_retry_path(self):
        """Duplicate submission must not increment attempt counter."""
        pipeline, _, _, _ = _build_async_pipeline()
        s1 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        s2 = pipeline.submit(idempotency_key="key-1", filename="test.txt", content=b"a")
        # attempt should still be 1 (initial value from first submit)
        assert s1.attempt == 1
        assert s2.attempt == 1


# ===========================================================================
# Group 4: Retry
# ===========================================================================


@dataclass
class _FlakyParser:
    """Parser that fails N times, then succeeds."""

    fail_count: int = 1
    _calls: int = field(init=False, default=0)

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        self._calls += 1
        if self._calls <= self.fail_count:
            raise ProcessingError("parse failed")
        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text="parsed text",
            metadata={"parser_strategy": "plain_text"},
        )


@dataclass
class _AlwaysFailParser:
    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        raise ProcessingError("always fails")


class TestRetry:
    def test_retry_success_on_second_attempt(self):
        """First attempt is re-queued, second succeeds; attempt increments."""
        parser = _FlakyParser(fail_count=1)
        pipeline, task_store, _, runner = _build_async_pipeline(parser=parser)
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        mid = task_store.get(doc_id)
        assert mid is not None
        assert mid.attempt == 2
        assert mid.status == TASK_QUEUED
        assert mid.error == "parse failed"
        assert runner.submitted == [doc_id, doc_id]

        pipeline.process_task(doc_id)

        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_INDEXED
        assert final.attempt == 2

    def test_retry_exhausted_goes_to_failed(self):
        """When all attempts fail, final status is failed and rollback happens."""
        parser = _AlwaysFailParser()
        vector_index = _FakeVectorIndex()
        pipeline, task_store, _, _ = _build_async_pipeline(
            parser=parser,
            vector_index=vector_index,
        )
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        mid = task_store.get(doc_id)
        assert mid is not None
        assert mid.attempt == 2
        assert mid.status == TASK_QUEUED

        with pytest.raises(ProcessingError):
            pipeline.process_task(doc_id)

        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_FAILED
        # Rollback should have been attempted
        assert vector_index.delete_calls == 1

    def test_retry_reuses_same_document_id(self):
        """Retry always reuses the same document_id, never creates a new task."""
        parser = _FlakyParser(fail_count=1)
        pipeline, task_store, _, _ = _build_async_pipeline(parser=parser)
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        pipeline.process_task(doc_id)

        # Only one task in store
        assert len(task_store._tasks) == 1
        final = task_store.get(doc_id)
        assert final is not None
        assert final.document_id == doc_id


# ===========================================================================
# Group 5: Progress
# ===========================================================================


class TestProgress:
    def test_each_step_updates_progress(self):
        """Each processing step updates step and progress_percent."""
        ds_store = _FakeDatasetStore()
        pipeline, task_store, _, _ = _build_async_pipeline(dataset_store=ds_store)
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
            dataset_id="ds-001",
        )
        doc_id = snapshot.document_id
        pipeline.process_task(doc_id)

        # Verify each step's progress was recorded via update() calls
        step_progress_map = {
            s.step: s.progress_percent for s in task_store.updates if s.step is not None
        }
        for step_name, expected_pct in STEP_PROGRESS.items():
            assert step_name in step_progress_map, (
                f"Step {step_name} not found in updates"
            )
            assert step_progress_map[step_name] == expected_pct, (
                f"Step {step_name} progress: got {step_progress_map[step_name]}, expected {expected_pct}"
            )

    def test_failed_preserves_failed_step(self):
        """Failed state preserves the step that failed."""
        parser = _AlwaysFailParser()
        pipeline, task_store, _, _ = _build_async_pipeline(parser=parser)
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        mid = task_store.get(doc_id)
        assert mid is not None
        assert mid.step == STEP_PARSING
        assert mid.error is not None
        assert "always fails" in mid.error
        assert mid.status == TASK_QUEUED

        with pytest.raises(ProcessingError):
            pipeline.process_task(doc_id)

        final = task_store.get(doc_id)
        assert final is not None
        assert final.status == TASK_FAILED
        assert final.step == STEP_PARSING
        assert final.error is not None


# ===========================================================================
# Group 6: Stage cache
# ===========================================================================


@dataclass
class _FailingEmbedder:
    """Embedder that fails N times then succeeds."""

    fail_count: int = 1
    _calls: int = field(init=False, default=0)

    def embed_chunks(self, chunks: list[Any]) -> list[EmbeddedChunk]:
        self._calls += 1
        if self._calls <= self.fail_count:
            raise ProcessingError("embed failed")
        return []


class TestStageCache:
    def test_parse_cache_hit_on_retry(self):
        """parse cache is reused on retry."""
        embedder = _FailingEmbedder(fail_count=1)
        parse_calls = []

        @dataclass
        class _CountingParser:
            def parse(self, asset, raw_bytes):
                parse_calls.append(1)
                return ParsedDocument(
                    document_id=asset.document_id,
                    file_type=asset.file_type,
                    raw_text="parsed text",
                    metadata={"parser_strategy": "plain_text"},
                )

        pipeline, _, stage_cache, _ = _build_async_pipeline(
            parser=_CountingParser(),
            embedder=embedder,
        )
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        assert len(parse_calls) == 1

        parse_cache_keys = [k for k in stage_cache._entries if k.startswith("parse:")]
        assert len(parse_cache_keys) == 1

        pipeline.process_task(doc_id)

        assert len(parse_calls) == 1

    def test_parse_cache_miss_on_different_bytes(self):
        """parse cache key changes when raw_bytes differ."""
        pipeline, _, stage_cache, _ = _build_async_pipeline()
        s1 = pipeline.submit(
            idempotency_key="key-1", filename="test.txt", content=b"aaa"
        )
        pipeline.process_task(s1.document_id)

        s2 = pipeline.submit(
            idempotency_key="key-2", filename="test.txt", content=b"bbb"
        )
        pipeline.process_task(s2.document_id)

        parse_cache_keys = [k for k in stage_cache._entries if k.startswith("parse:")]
        assert len(parse_cache_keys) == 2

    def test_parse_cache_miss_on_different_file_type(self):
        """parse cache key changes when file_type differs."""
        pipeline, _, stage_cache, _ = _build_async_pipeline()
        s1 = pipeline.submit(
            idempotency_key="key-1", filename="test.txt", content=b"hello"
        )
        pipeline.process_task(s1.document_id)

        s2 = pipeline.submit(
            idempotency_key="key-2", filename="test.md", content=b"hello"
        )
        pipeline.process_task(s2.document_id)

        parse_cache_keys = [k for k in stage_cache._entries if k.startswith("parse:")]
        assert len(parse_cache_keys) == 2

    def test_chunk_cache_hit_on_retry(self):
        """chunk cache is reused on retry."""
        embedder = _FailingEmbedder(fail_count=1)
        chunk_calls = []

        @dataclass
        class _CountingChunker:
            chunk_size: int = 500
            chunk_overlap: int = 50

            def chunk(self, document):
                chunk_calls.append(1)
                return []

        pipeline, _, stage_cache, _ = _build_async_pipeline(
            chunker=_CountingChunker(),
            embedder=embedder,
        )
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)

        assert len(chunk_calls) == 1

        chunk_cache_keys = [k for k in stage_cache._entries if k.startswith("chunk:")]
        assert len(chunk_cache_keys) == 1

        pipeline.process_task(doc_id)

        assert len(chunk_calls) == 1

    def test_index_never_cached(self):
        """index_document is always executed, never cached."""
        index_calls = []

        @dataclass
        class _CountingVectorIndex:
            delete_calls: int = 0

            def index_document(self, asset, chunks):
                index_calls.append(asset.document_id)

            def delete_document(self, document_id):
                self.delete_calls += 1

        embedder = _FailingEmbedder(fail_count=1)
        pipeline, _, stage_cache, _ = _build_async_pipeline(
            vector_index=_CountingVectorIndex(),
            embedder=embedder,
        )
        snapshot = pipeline.submit(
            idempotency_key="key-1",
            filename="test.txt",
            content=b"hello",
        )
        doc_id = snapshot.document_id

        pipeline.process_task(doc_id)
        assert len(index_calls) == 0

        pipeline.process_task(doc_id)
        assert len(index_calls) == 1
        assert index_calls[0] == doc_id

        # No index-related cache keys
        index_cache_keys = [k for k in stage_cache._entries if "index" in k]
        assert len(index_cache_keys) == 0

    def test_same_content_different_document_ids_rebind_cached_identity(self):
        """Cache hits must rebind document_id and chunk_id to the current task."""

        @dataclass
        class _CountingParser:
            calls: int = 0

            def parse(self, asset, raw_bytes):
                self.calls += 1
                return ParsedDocument(
                    document_id=asset.document_id,
                    file_type=asset.file_type,
                    raw_text="same parsed text",
                    metadata={"parser_strategy": "plain_text"},
                )

        @dataclass
        class _CountingChunker:
            chunk_size: int = 500
            chunk_overlap: int = 50
            calls: int = 0

            def chunk(self, document):
                self.calls += 1
                return [
                    Chunk(
                        chunk_id=f"chunk_{document.document_id}_0",
                        document_id=document.document_id,
                        text=document.raw_text,
                        index=0,
                        metadata={"kind": "unit"},
                    )
                ]

        @dataclass
        class _PassThroughEmbedder:
            def embed_chunks(self, chunks):
                return [
                    EmbeddedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        index=chunk.index,
                        vector=[1.0],
                        metadata=dict(chunk.metadata),
                    )
                    for chunk in chunks
                ]

        @dataclass
        class _CapturingVectorIndex:
            indexed: list = field(default_factory=list)

            def index_document(self, asset, chunks):
                self.indexed.append(
                    {
                        "asset_document_id": asset.document_id,
                        "chunk_document_ids": [chunk.document_id for chunk in chunks],
                        "chunk_ids": [chunk.chunk_id for chunk in chunks],
                    }
                )

            def delete_document(self, document_id):
                pass

        parser = _CountingParser()
        chunker = _CountingChunker()
        vector_index = _CapturingVectorIndex()
        pipeline, _, _, _ = _build_async_pipeline(
            parser=parser,
            chunker=chunker,
            embedder=_PassThroughEmbedder(),
            vector_index=vector_index,
        )

        first = pipeline.submit(
            idempotency_key="key-1",
            filename="same.txt",
            content=b"same-content",
        )
        pipeline.process_task(first.document_id)

        second = pipeline.submit(
            idempotency_key="key-2",
            filename="same.txt",
            content=b"same-content",
        )
        pipeline.process_task(second.document_id)

        assert parser.calls == 1
        assert chunker.calls == 1
        assert first.document_id != second.document_id
        assert vector_index.indexed[0]["asset_document_id"] == first.document_id
        assert vector_index.indexed[0]["chunk_document_ids"] == [first.document_id]
        assert vector_index.indexed[0]["chunk_ids"] == [f"chunk_{first.document_id}_0"]
        assert vector_index.indexed[1]["asset_document_id"] == second.document_id
        assert vector_index.indexed[1]["chunk_document_ids"] == [second.document_id]
        assert vector_index.indexed[1]["chunk_ids"] == [f"chunk_{second.document_id}_0"]


# ===========================================================================
# Group 7: Observability
# ===========================================================================


class TestObservability:
    def test_submit_records_accepted_metric(self):
        """Submit increments ingest_task_accepted_total counter."""
        from prometheus_client import CollectorRegistry

        from ragflow_lite.shared.observability import (
            _metrics_state_ctx,
        )

        registry = CollectorRegistry()
        metrics_state = _build_metrics_state_with_registry(registry)
        token = _metrics_state_ctx.set(metrics_state)

        try:
            pipeline, _, _, _ = _build_async_pipeline()
            pipeline.submit(
                idempotency_key="key-1", filename="test.txt", content=b"hello"
            )

            # Check counter was incremented
            samples = list(
                registry.get_sample_value(
                    "ragflow_lite_ingest_task_accepted_total",
                    {"file_type": "txt"},
                )
                for _ in [1]
            )
            assert samples[0] == 1.0
        finally:
            _metrics_state_ctx.reset(token)

    def test_retry_records_retry_metric(self):
        """Retry increments ingest_task_retry_total counter."""
        from prometheus_client import CollectorRegistry

        from ragflow_lite.shared.observability import _metrics_state_ctx

        registry = CollectorRegistry()
        metrics_state = _build_metrics_state_with_registry(registry)
        token = _metrics_state_ctx.set(metrics_state)

        try:
            parser = _AlwaysFailParser()
            pipeline, _, _, _ = _build_async_pipeline(parser=parser)
            snapshot = pipeline.submit(
                idempotency_key="key-1",
                filename="test.txt",
                content=b"hello",
            )

            pipeline.process_task(snapshot.document_id)

            val = registry.get_sample_value(
                "ragflow_lite_ingest_task_retry_total",
                {"file_type": "txt"},
            )
            assert val == 1.0
        finally:
            _metrics_state_ctx.reset(token)

    def test_cache_hit_miss_recorded(self):
        """Cache hits and misses are recorded."""
        from prometheus_client import CollectorRegistry

        from ragflow_lite.shared.observability import _metrics_state_ctx

        registry = CollectorRegistry()
        metrics_state = _build_metrics_state_with_registry(registry)
        token = _metrics_state_ctx.set(metrics_state)

        try:
            embedder = _FailingEmbedder(fail_count=1)
            pipeline, _, _, _ = _build_async_pipeline(embedder=embedder)
            snapshot = pipeline.submit(
                idempotency_key="key-1",
                filename="test.txt",
                content=b"hello",
            )
            doc_id = snapshot.document_id

            pipeline.process_task(doc_id)

            misses_after_first = registry.get_sample_value(
                "ragflow_lite_ingest_stage_cache_total",
                {"outcome": "miss"},
            )

            pipeline.process_task(doc_id)

            hits_after_second = registry.get_sample_value(
                "ragflow_lite_ingest_stage_cache_total",
                {"outcome": "hit"},
            )
            misses_after_second = registry.get_sample_value(
                "ragflow_lite_ingest_stage_cache_total",
                {"outcome": "miss"},
            )

            assert hits_after_second is not None
            assert hits_after_second >= 2  # parse + chunk cache hits on retry
            assert misses_after_first is not None
            assert misses_after_second is not None
            # First process: 2 misses (parse + chunk). Second process: 0 new misses (both cached).
            assert misses_after_first == 2.0
            assert misses_after_second == 2.0
        finally:
            _metrics_state_ctx.reset(token)

    def test_task_duration_recorded(self):
        """Task processing duration is recorded."""
        from prometheus_client import CollectorRegistry

        from ragflow_lite.shared.observability import _metrics_state_ctx

        registry = CollectorRegistry()
        metrics_state = _build_metrics_state_with_registry(registry)
        token = _metrics_state_ctx.set(metrics_state)

        try:
            pipeline, _, _, _ = _build_async_pipeline()
            snapshot = pipeline.submit(
                idempotency_key="key-1",
                filename="test.txt",
                content=b"hello",
            )
            pipeline.process_task(snapshot.document_id)

            # Check histogram has observations for succeeded
            succeeded_count = registry.get_sample_value(
                "ragflow_lite_ingest_task_duration_seconds_count",
                {"outcome": "succeeded"},
            )
            assert succeeded_count == 1.0
        finally:
            _metrics_state_ctx.reset(token)


def _build_metrics_state_with_registry(registry) -> Any:
    """Build a _MetricsState with all async ingestion metrics on a given registry."""
    from prometheus_client import Counter, Histogram

    from ragflow_lite.shared.observability import _MetricsState

    return _MetricsState(
        enabled=True,
        registry=registry,
        ingest_task_accepted_total=Counter(
            "ragflow_lite_ingest_task_accepted_total",
            "test",
            ("file_type",),
            registry=registry,
        ),
        ingest_task_retry_total=Counter(
            "ragflow_lite_ingest_task_retry_total",
            "test",
            ("file_type",),
            registry=registry,
        ),
        ingest_stage_cache_total=Counter(
            "ragflow_lite_ingest_stage_cache_total",
            "test",
            ("outcome",),
            registry=registry,
        ),
        ingest_task_duration_seconds=Histogram(
            "ragflow_lite_ingest_task_duration_seconds",
            "test",
            ("outcome",),
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
            registry=registry,
        ),
        ingest_task_queue_delay_seconds=Histogram(
            "ragflow_lite_ingest_task_queue_delay_seconds",
            "test",
            (),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=registry,
        ),
    )


# ---------------------------------------------------------------------------
# Fake graph evidence collaborators
# ---------------------------------------------------------------------------


@dataclass
class _FakeEvidenceExtractor:
    calls: int = 0

    def extract(self, chunks: list[Chunk]) -> GraphEvidenceBatch:
        self.calls += 1
        document_id = chunks[0].document_id
        source_chunk_ids = [chunk.chunk_id for chunk in chunks]
        entity = EntityEvidence(
            entity_id="entity_minirag",
            document_id=document_id,
            name="MiniRAG",
            entity_type="concept",
            description="Lightweight graph retrieval.",
            source_chunk_ids=source_chunk_ids,
            metadata={"source_id": "|".join(source_chunk_ids)},
        )
        relation = RelationEvidence(
            relation_id="relation_minirag_chunk",
            document_id=document_id,
            source_entity_id="entity_minirag",
            target_entity_id="entity_chunk",
            source_entity_name="MiniRAG",
            target_entity_name="chunk",
            description="MiniRAG links evidence to chunks.",
            keywords=["provenance"],
            weight=1.0,
            source_chunk_ids=source_chunk_ids,
            metadata={"source_id": "|".join(source_chunk_ids)},
        )
        return GraphEvidenceBatch(
            document_id=document_id,
            entities=[entity],
            relations=[relation],
        )


@dataclass
class _FakeGraphEvidenceStore:
    upserts: list[GraphEvidenceBatch] = field(default_factory=list)
    delete_calls: list[str] = field(default_factory=list)

    def upsert_document_evidence(self, batch: GraphEvidenceBatch):
        self.upserts.append(batch)
        return None

    def delete_document(self, document_id: str) -> None:
        self.delete_calls.append(document_id)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        for batch in self.upserts:
            if batch.document_id == document_id:
                return batch
        return None


@dataclass
class _FailingGraphEvidenceStore(_FakeGraphEvidenceStore):
    def upsert_document_evidence(self, batch: GraphEvidenceBatch):
        raise RuntimeError("graph store failed")


# ---------------------------------------------------------------------------
# Graph evidence integration tests
# ---------------------------------------------------------------------------


def test_ingest_persists_graph_evidence_after_chunking() -> None:
    extractor = _FakeEvidenceExtractor()
    graph_store = _FakeGraphEvidenceStore()
    pipeline = _build_pipeline(chunker=_ProducingChunker())
    pipeline.evidence_extractor = extractor
    pipeline.graph_store = graph_store

    result = pipeline.ingest("test.txt", b"hello")

    assert result.status == "indexed"
    assert extractor.calls == 1
    assert len(graph_store.upserts) == 1
    assert graph_store.upserts[0].document_id == result.document_id
    assert graph_store.upserts[0].entities[0].source_chunk_ids


def test_ingest_skips_graph_evidence_when_chunker_returns_no_chunks() -> None:
    extractor = _FakeEvidenceExtractor()
    graph_store = _FakeGraphEvidenceStore()
    pipeline = _build_pipeline()
    pipeline.evidence_extractor = extractor
    pipeline.graph_store = graph_store

    result = pipeline.ingest("test.txt", b"hello")

    assert result.status == "indexed"
    assert extractor.calls == 0
    assert graph_store.upserts == []


def test_graph_evidence_failure_rolls_back_document_and_vector_index() -> None:
    vector_index = _FakeVectorIndex()
    document_store = _FakeDocumentStore()
    pipeline = _build_pipeline(
        vector_index=vector_index,
        document_store=document_store,
        chunker=_ProducingChunker(),
    )
    pipeline.evidence_extractor = _FakeEvidenceExtractor()
    pipeline.graph_store = _FailingGraphEvidenceStore()

    with pytest.raises(ProcessingError, match="Failed to index document"):
        pipeline.ingest("graph.txt", b"graph content")

    assert vector_index.delete_calls == 1
    assert document_store.delete_calls == 1


class TestChunkCacheFingerprint:
    """Tests for _chunk_cache_key() fingerprinting behavior."""

    @staticmethod
    def _make_pipeline(chunker: Any) -> IngestionPipeline:
        return IngestionPipeline(
            document_store=_FakeDocumentStore(),
            parser=_FakeParser(),
            chunker=chunker,
            embedder=_FakeEmbedder(),
            vector_index=_FakeVectorIndex(),
            normalizer=lambda text, filename: text,
        )

    @staticmethod
    def _make_document(text: str = "Some text for testing") -> ParsedDocument:
        return ParsedDocument(
            document_id="doc_abc",
            file_type="txt",
            raw_text=text,
            metadata={"page_spans": [{"start": 0, "end": 22, "page_number": 1}]},
        )

    @pytest.mark.parametrize(
        ("left_chunker", "right_chunker", "expected_same"),
        [
            pytest.param(
                FixedWindowChunker(500, 50),
                RecursiveCharacterChunker(500, 50),
                False,
                id="differs-by-chunker-type",
            ),
            pytest.param(
                RecursiveCharacterChunker(500, 50, separators=["\n\n", "\n"]),
                RecursiveCharacterChunker(500, 50, separators=["\n\n", "\n", "。"]),
                False,
                id="differs-by-separators",
            ),
            pytest.param(
                RecursiveCharacterChunker(500, 50),
                RecursiveCharacterChunker(500, 50),
                True,
                id="stable-with-same-config",
            ),
        ],
    )
    def test_cache_key_fingerprint(
        self,
        left_chunker: Any,
        right_chunker: Any,
        expected_same: bool,
    ) -> None:
        doc = self._make_document()
        left_key = self._make_pipeline(left_chunker)._chunk_cache_key(doc)
        right_key = self._make_pipeline(right_chunker)._chunk_cache_key(doc)

        if expected_same:
            assert left_key == right_key
        else:
            assert left_key != right_key


# ---------------------------------------------------------------------------
# GraphEvidenceSidecarStore rollback test
# ---------------------------------------------------------------------------


def test_graph_evidence_sidecar_failure_rolls_back_sidecar_wrapper() -> None:
    """当 sidecar rebuild 失败时，pipeline rollback 通过 wrapper.delete_document 清理 graph JSON 和 sidecar 数据。"""
    from pathlib import Path

    from ragflow_lite.infrastructure.evidence.graph_candidate_sidecar import (
        GraphCandidateSidecar,
    )
    from ragflow_lite.infrastructure.evidence.graph_evidence_sidecar_store import (
        GraphEvidenceSidecarStore,
    )

    # 使用 _RecordingGraphStore：upsert 成功，记录 delete 调用
    @dataclass
    class _RecordingGraphStore:
        upserts: list[GraphEvidenceBatch] = field(default_factory=list)
        delete_calls: list[str] = field(default_factory=list)

        def upsert_document_evidence(self, batch: GraphEvidenceBatch):
            self.upserts.append(batch)
            return GraphEvidenceWriteResult(
                document_id=batch.document_id,
                entity_count=len(batch.entities),
                relation_count=len(batch.relations),
            )

        def delete_document(self, document_id: str) -> None:
            self.delete_calls.append(document_id)

        def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
            return None

    # 构造一个在 embed_query 时失败的 QueryEmbedder
    class _FailingQueryEmbedder:
        def embed_query(self, query: str) -> list[float]:
            raise RuntimeError("sidecar embed failed")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        inner_store = _RecordingGraphStore()
        sidecar = GraphCandidateSidecar(
            sidecar_dir=Path(tmp_dir),
            embedding_signature={"model": "fake", "dim": 4},
        )
        wrapper = GraphEvidenceSidecarStore(
            graph_store=inner_store,
            sidecar=sidecar,
            embedder=_FailingQueryEmbedder(),
        )

        vector_index = _FakeVectorIndex()
        document_store = _FakeDocumentStore()
        pipeline = _build_pipeline(
            vector_index=vector_index,
            document_store=document_store,
            chunker=_ProducingChunker(),
        )
        pipeline.evidence_extractor = _FakeEvidenceExtractor()
        pipeline.graph_store = wrapper

        with pytest.raises(ProcessingError, match="Failed to index document"):
            pipeline.ingest("sidecar_test.txt", b"sidecar content")

        # rollback 应调用 wrapper.delete_document，进而调用 inner_store.delete
        assert inner_store.delete_calls, (
            "wrapper.delete_document should have been called during rollback"
        )
        assert vector_index.delete_calls == 1
        assert document_store.delete_calls == 1


# ---------------------------------------------------------------------------
# GraphEvidenceInfinityStore rollback test
# ---------------------------------------------------------------------------


def test_graph_evidence_infinity_failure_rolls_back_both_stores() -> None:
    """当 Infinity candidate 写入失败时，GraphEvidenceInfinityStore 回滚 JSON store 和 candidate 行。"""
    from ragflow_lite.infrastructure.evidence.graph_evidence_infinity_store import (
        GraphEvidenceInfinityStore,
    )

    # 记录调用、Infinity 写入时失败的伪依赖
    @dataclass
    class _RecordingGraphStore:
        upserts: list[GraphEvidenceBatch] = field(default_factory=list)
        delete_calls: list[str] = field(default_factory=list)

        def upsert_document_evidence(self, batch: GraphEvidenceBatch):
            self.upserts.append(batch)
            return GraphEvidenceWriteResult(
                document_id=batch.document_id,
                entity_count=len(batch.entities),
                relation_count=len(batch.relations),
            )

        def delete_document(self, document_id: str) -> None:
            self.delete_calls.append(document_id)

        def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
            return None

    @dataclass
    class _FailingCandidateIndex:
        """upsert_document_evidence 总是失败的伪候选索引。"""

        deletes: list[str] = field(default_factory=list)

        def upsert_document_evidence(self, batch: GraphEvidenceBatch) -> None:
            raise RuntimeError("infinity candidate write failed")

        def delete_document(self, document_id: str) -> None:
            self.deletes.append(document_id)

    inner_store = _RecordingGraphStore()
    failing_index = _FailingCandidateIndex()
    wrapper = GraphEvidenceInfinityStore(
        graph_store=inner_store,
        candidate_index=cast(Any, failing_index),
    )

    vector_index = _FakeVectorIndex()
    document_store = _FakeDocumentStore()
    pipeline = _build_pipeline(
        vector_index=vector_index,
        document_store=document_store,
        chunker=_ProducingChunker(),
    )
    pipeline.evidence_extractor = _FakeEvidenceExtractor()
    pipeline.graph_store = wrapper

    with pytest.raises(ProcessingError, match="Failed to index document"):
        pipeline.ingest("infinity_test.txt", b"infinity content")

    # wrapper 回滚：inner_store 和 candidate_index 都收到 delete
    assert inner_store.delete_calls, "JSON store rollback should have been called"
    assert failing_index.deletes, "Infinity candidate rollback should have been called"
    assert vector_index.delete_calls == 1
    assert document_store.delete_calls == 1
