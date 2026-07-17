from __future__ import annotations

from typing import Protocol

from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)


class DocumentArtifactLifecycle(Protocol):
    def delete_document(self, document_id: str) -> None: ...


class ArtifactDeleteCoordinator:
    def __init__(
        self,
        *,
        registry: SqliteArtifactRegistry,
        graph_lifecycle: DocumentArtifactLifecycle,
        psi_lifecycle: DocumentArtifactLifecycle,
        main_chunk_lifecycle: DocumentArtifactLifecycle,
    ) -> None:
        self._registry = registry
        self._graph_lifecycle = graph_lifecycle
        self._psi_lifecycle = psi_lifecycle
        self._main_chunk_lifecycle = main_chunk_lifecycle

    def delete_document(self, document_id: str) -> None:
        self._registry.mark_document_deleting(document_id)
        self._delete_artifacts(
            document_id,
            lifecycle=self._graph_lifecycle,
            failure_stage="delete_graph_projection",
            failure_code="infinity_projection_delete_failed",
        )
        self._delete_artifacts(
            document_id,
            lifecycle=self._psi_lifecycle,
            failure_stage="delete_psi_projection",
            failure_code="infinity_projection_delete_failed",
        )
        self._delete_artifacts(
            document_id,
            lifecycle=self._main_chunk_lifecycle,
            failure_stage="delete_main_chunks",
            failure_code="main_chunk_delete_failed",
        )
        self._registry.mark_sqlite_payloads_deleted_for_document(document_id)
        self._registry.mark_document_deleted(document_id)

    def retry_delete_document(self, document_id: str) -> None:
        self.delete_document(document_id)

    def _delete_artifacts(
        self,
        document_id: str,
        *,
        lifecycle: DocumentArtifactLifecycle,
        failure_stage: str,
        failure_code: str,
    ) -> None:
        try:
            lifecycle.delete_document(document_id)
        except Exception as exc:
            self._registry.mark_document_delete_failed(
                document_id,
                failure_code=failure_code,
                failure_stage=failure_stage,
                retryable=True,
                error_message=str(exc),
            )
            raise
