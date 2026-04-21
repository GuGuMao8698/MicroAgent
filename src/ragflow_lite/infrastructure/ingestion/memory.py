"""In-memory implementations of async ingestion contracts."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from ragflow_lite.domain.models import IngestionTaskSnapshot
from ragflow_lite.shared.observability import (
    bind_metrics_state,
    clear_metrics_state,
    log_event,
)

logger = logging.getLogger(__name__)


class InMemoryTaskStore:
    """单进程内存任务存储。"""

    def __init__(self) -> None:
        self._tasks: dict[str, IngestionTaskSnapshot] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = threading.Lock()

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
            snapshot = self._tasks.get(document_id)
            if snapshot is not None and snapshot.idempotency_key == idempotency_key:
                self._tasks.pop(document_id, None)

            if self._idempotency.get(idempotency_key) == document_id:
                self._idempotency.pop(idempotency_key, None)

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
        return snapshot


class InMemoryStageCache:
    """单进程内存阶段缓存。"""

    def __init__(self) -> None:
        self._entries: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._entries.get(key)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = value


class InlineTaskRunner:
    """同步 inline runner（仅用于单元测试等显式同步场景）。"""

    def __init__(self) -> None:
        self._handler: Any = None
        self.submitted: list[str] = []

    def set_handler(self, handler: Any) -> None:
        self._handler = handler

    def submit(self, document_id: str) -> None:
        self.submitted.append(document_id)
        if self._handler is not None:
            self._handler(document_id)


class BackgroundTaskRunner:
    """Single-process background runner backed by an in-memory queue."""

    _STOP = object()

    def __init__(
        self,
        handler: Callable[[str], None] | None = None,
        *,
        max_queue_size: int = 1024,
    ) -> None:
        self._handler = handler
        self._queue: queue.Queue[str | object] = queue.Queue(maxsize=max_queue_size)
        self._closed = False
        self._lock = threading.Lock()
        self._metrics_state: Any = None
        self.submitted: list[str] = []
        self._worker = threading.Thread(
            target=self._run,
            name="ragflow-lite-ingestion",
            daemon=True,
        )
        self._worker.start()

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def set_metrics_state(self, metrics_state: Any) -> None:
        self._metrics_state = metrics_state

    def submit(self, document_id: str) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Background ingestion runner is closed.")
            self.submitted.append(document_id)
            try:
                self._queue.put_nowait(document_id)
            except queue.Full as exc:
                raise RuntimeError("Background ingestion queue is full.") from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(self._STOP)
        self._worker.join(timeout=5)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return

                handler = self._handler
                if handler is None:
                    continue

                token = None
                if self._metrics_state is not None:
                    token = bind_metrics_state(self._metrics_state)
                try:
                    handler(str(item))
                finally:
                    if token is not None:
                        clear_metrics_state(token)
            except Exception as exc:  # pragma: no cover - guarded by integration tests
                log_event(
                    logger,
                    logging.ERROR,
                    "ingestion_task_runner_failed",
                    document_id=str(item),
                    error_type=type(exc).__name__,
                )
            finally:
                self._queue.task_done()
