from __future__ import annotations

from ragflow_lite.domain.models import GraphEvidenceBatch, GraphEvidenceWriteResult
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    InfinityGraphCandidateIndex,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_store import (
    SqliteGraphEvidenceStore,
)


class SqliteGraphProjectionStore:
    """协调 SQLite 图证据与 Infinity 候选投影。"""

    def __init__(
        self,
        *,
        graph_store: SqliteGraphEvidenceStore,
        candidate_index: InfinityGraphCandidateIndex,
        registry: SqliteArtifactRegistry,
        target_table: str,
    ) -> None:
        self._graph_store = graph_store
        self._candidate_index = candidate_index
        self._registry = registry
        self._target_table = target_table

    def upsert_document_evidence(
        self, batch: GraphEvidenceBatch
    ) -> GraphEvidenceWriteResult:
        result = self._graph_store.upsert_document_evidence(batch)
        build = self._registry.get_latest_build("graph_evidence", batch.document_id)
        if build is None:
            raise RuntimeError("latest graph build missing after sqlite graph write")
        projection = self._registry.create_projection(
            build_id=build.build_id,
            target="infinity_graph_candidate",
            target_table=self._target_table,
        )
        try:
            self._candidate_index.upsert_build_evidence(build.build_id, batch)
        except Exception as exc:
            self._registry.mark_projection_failed(
                projection.projection_id,
                failure_code="infinity_projection_failed",
                failure_stage="project_infinity",
                retryable=True,
                error_message=str(exc),
            )
            self._registry.mark_build_failed(
                build.build_id,
                failure_code="infinity_projection_failed",
                failure_stage="project_infinity",
                retryable=True,
                error_message=str(exc),
            )
            raise

        self._registry.mark_projection_projected(projection.projection_id)
        superseded_build_ids = self._registry.activate_build(build.build_id)
        for superseded_build_id in superseded_build_ids:
            try:
                self._candidate_index.delete_build(superseded_build_id)
            except Exception as exc:
                self._registry.mark_projection_delete_failed_for_build(
                    superseded_build_id,
                    target="infinity_graph_candidate",
                    failure_code="infinity_projection_delete_failed",
                    failure_stage="delete_projection",
                    retryable=True,
                    error_message=str(exc),
                )
                raise
        return result

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        active = self._registry.get_active_build("graph_evidence", document_id)
        if active is None:
            return None
        return self._graph_store.get_build_evidence(active.build_id)

    def delete_document(self, document_id: str) -> None:
        self._registry.mark_graph_projection_deleting(document_id)
        build_ids = self._graph_build_ids_for_document(document_id)
        try:
            for build_id in build_ids:
                self._candidate_index.delete_build(build_id)
        except Exception as exc:
            self._registry.mark_projection_delete_failed_for_document(
                document_id,
                target="infinity_graph_candidate",
                failure_code="infinity_projection_delete_failed",
                failure_stage="delete_projection",
                retryable=True,
                error_message=str(exc),
            )
            raise
        self._registry.mark_projection_deleted_for_document(
            document_id, target="infinity_graph_candidate"
        )
        self._registry.mark_builds_deleted_for_document(
            document_id, artifact_type="graph_evidence"
        )

    def _graph_build_ids_for_document(self, document_id: str) -> list[str]:
        with self._registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT build_id
                FROM artifact_builds
                WHERE document_id = ? AND artifact_type = ? AND deleted_at IS NULL
                ORDER BY created_at DESC, rowid DESC
                """,
                (document_id, "graph_evidence"),
            ).fetchall()
        return [str(row["build_id"]) for row in rows]
