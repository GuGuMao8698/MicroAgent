from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ragflow_lite.infrastructure.evidence.artifact_event_recorder import (
    ArtifactEvent,
    ArtifactEventRecorder,
    InMemoryArtifactEventRecorder,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_schema import (
    ARTIFACT_TYPES,
    PROJECTION_TARGETS,
    connect_artifact_db,
)

_ALLOWED_PROJECTION_TARGETS_BY_ARTIFACT_TYPE = {
    "graph_evidence": "infinity_graph_candidate",
    "psi_tree": "infinity_psi_node",
}


@dataclass(slots=True)
class ArtifactDocumentRecord:
    document_id: str
    status: str
    failure_code: str | None
    failure_stage: str | None
    failure_retryable: bool | None
    error_message: str | None
    attempt_count: int
    last_attempted_at: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(slots=True)
class ArtifactBuildRecord:
    build_id: str
    document_id: str
    artifact_type: str
    builder_version: str
    embedding_signature: str
    status: str
    failure_code: str | None
    failure_stage: str | None
    failure_retryable: bool | None
    error_message: str | None
    attempt_count: int
    last_attempted_at: str | None
    created_at: str
    projected_at: str | None
    activated_at: str | None
    failed_at: str | None


@dataclass(slots=True)
class ProjectionRecord:
    projection_id: str
    build_id: str
    target: str
    target_table: str
    status: str
    failure_code: str | None
    failure_stage: str | None
    failure_retryable: bool | None
    error_message: str | None
    attempt_count: int
    last_attempted_at: str | None
    projected_at: str | None
    failed_at: str | None


@dataclass(slots=True)
class OrphanProjectionFailureRecord:
    orphan_failure_id: str
    target: str
    target_table: str
    owner_build_id: str
    status: str
    failure_code: str
    failure_stage: str
    detected_at: str


class SqliteArtifactRegistry:
    def __init__(
        self,
        db_path: Path,
        *,
        recorder: ArtifactEventRecorder | None = None,
    ) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._recorder = recorder or InMemoryArtifactEventRecorder()

    def connect(self) -> sqlite3.Connection:
        return connect_artifact_db(self._db_path)

    def create_build(
        self,
        *,
        document_id: str,
        artifact_type: str,
        builder_version: str,
        embedding_signature: str,
    ) -> ArtifactBuildRecord:
        self._validate_artifact_type(artifact_type)
        build_id = str(uuid.uuid4())
        now = _now_iso()
        with self.connect() as conn:
            self._ensure_document(conn, document_id)
            conn.execute(
                """
                INSERT INTO artifact_builds (
                    build_id,
                    document_id,
                    artifact_type,
                    builder_version,
                    embedding_signature,
                    status,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    build_id,
                    document_id,
                    artifact_type,
                    builder_version,
                    embedding_signature,
                    "building",
                    now,
                ),
            )
        self._record_event(
            "artifact_build_started",
            {
                "document_id": document_id,
                "artifact_type": artifact_type,
                "build_id": build_id,
            },
        )
        build = self.get_build(build_id)
        assert build is not None
        return build

    def mark_payload_complete(self, build_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, projected_at = NULL
                WHERE build_id = ?
                """,
                ("projection_pending", build_id),
            )

    def create_projection(
        self,
        *,
        build_id: str,
        target: str,
        target_table: str,
    ) -> ProjectionRecord:
        self._validate_projection_target(target)
        projection_id = str(uuid.uuid4())
        with self.connect() as conn:
            build_row = self._fetch_build_context(conn, build_id)
            expected_target = _ALLOWED_PROJECTION_TARGETS_BY_ARTIFACT_TYPE[
                str(build_row["artifact_type"])
            ]
            if str(build_row["status"]) != "projection_pending":
                msg = (
                    "create_projection requires build status projection_pending; "
                    f"got {build_row['status']}"
                )
                raise ValueError(msg)
            if target != expected_target:
                msg = (
                    "unsupported projection target for artifact_type "
                    f"{build_row['artifact_type']}: expected {expected_target}, got {target}"
                )
                raise ValueError(msg)
            conn.execute(
                """
                INSERT INTO artifact_projections (
                    projection_id,
                    build_id,
                    target,
                    target_table,
                    status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (projection_id, build_id, target, target_table, "pending"),
            )
        self._record_event(
            "artifact_projection_started",
            {
                "document_id": str(build_row["document_id"]),
                "artifact_type": str(build_row["artifact_type"]),
                "build_id": build_id,
                "projection_id": projection_id,
                "target": target,
            },
        )
        projection = self.get_projection(projection_id)
        assert projection is not None
        return projection

    def mark_projection_projected(self, projection_id: str) -> None:
        now = _now_iso()
        with self.connect() as conn:
            projection_row = conn.execute(
                """
                SELECT projection_id, build_id, status
                FROM artifact_projections
                WHERE projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
            if projection_row is None:
                msg = f"unknown projection_id: {projection_id}"
                raise ValueError(msg)
            if str(projection_row["status"]) not in {"pending", "projecting"}:
                msg = (
                    "mark_projection_projected requires pending/projecting status; "
                    f"got {projection_row['status']}"
                )
                raise ValueError(msg)
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?, projected_at = ?, failure_code = NULL,
                    failure_stage = NULL, failure_retryable = NULL, error_message = NULL,
                    failed_at = NULL
                WHERE projection_id = ?
                """,
                ("projected", now, projection_id),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, projected_at = ?, failed_at = NULL,
                    failure_code = NULL, failure_stage = NULL,
                    failure_retryable = NULL, error_message = NULL
                WHERE build_id = (
                    SELECT build_id FROM artifact_projections WHERE projection_id = ?
                )
                """,
                ("projected", now, projection_id),
            )

    def activate_build(self, build_id: str) -> list[str]:
        now = _now_iso()
        superseded_build_ids: list[str] = []
        with self.connect() as conn:
            build_row = self._fetch_build_context(conn, build_id)
            document_id = str(build_row["document_id"])
            artifact_type = str(build_row["artifact_type"])
            if str(build_row["status"]) != "projected":
                msg = (
                    "activate_build requires projected build status; "
                    f"got {build_row['status']}"
                )
                raise ValueError(msg)
            previous = conn.execute(
                """
                SELECT active_build_id
                FROM active_artifacts
                WHERE artifact_type = ? AND document_id = ?
                """,
                (artifact_type, document_id),
            ).fetchone()
            if previous is not None and str(previous["active_build_id"]) != build_id:
                superseded_build_ids.append(str(previous["active_build_id"]))
                conn.execute(
                    """
                    UPDATE artifact_builds
                    SET status = ?
                    WHERE build_id = ?
                    """,
                    ("superseded", str(previous["active_build_id"])),
                )
            conn.execute(
                """
                INSERT INTO active_artifacts (
                    artifact_type,
                    document_id,
                    active_build_id,
                    activated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(artifact_type, document_id)
                DO UPDATE SET active_build_id = excluded.active_build_id,
                              activated_at = excluded.activated_at
                """,
                (artifact_type, document_id, build_id, now),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, activated_at = ?, failure_code = NULL,
                    failure_stage = NULL, failure_retryable = NULL,
                    error_message = NULL, failed_at = NULL
                WHERE build_id = ?
                """,
                ("active", now, build_id),
            )
        self._record_event(
            "active_artifact_switched",
            {
                "document_id": document_id,
                "artifact_type": artifact_type,
                "build_id": build_id,
            },
        )
        return superseded_build_ids

    def record_active_pointer_inconsistent(
        self,
        *,
        document_id: str,
        artifact_type: str,
        build_id: str,
        failure_stage: str,
        error_message: str,
    ) -> None:
        self._validate_artifact_type(artifact_type)
        now = _now_iso()
        with self.connect() as conn:
            build_row = self._fetch_build_context(conn, build_id)
            if (
                str(build_row["document_id"]) != document_id
                or str(build_row["artifact_type"]) != artifact_type
            ):
                msg = "mismatched build owner for active pointer inconsistency"
                raise ValueError(msg)
            conn.execute(
                """
                DELETE FROM active_artifacts
                WHERE artifact_type = ? AND document_id = ?
                """,
                (artifact_type, document_id),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, failure_code = ?, failure_stage = ?,
                    failure_retryable = ?, error_message = ?, failed_at = ?,
                    attempt_count = attempt_count + 1, last_attempted_at = ?
                WHERE build_id = ?
                """,
                (
                    "failed",
                    "active_pointer_inconsistent",
                    failure_stage,
                    0,
                    error_message,
                    now,
                    now,
                    build_id,
                ),
            )
        self._record_event(
            "artifact_build_failed",
            {
                "document_id": document_id,
                "artifact_type": artifact_type,
                "build_id": build_id,
                "failure_code": "active_pointer_inconsistent",
                "failure_stage": failure_stage,
            },
        )

    def mark_build_failed(
        self,
        build_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        with self.connect() as conn:
            build_row = self._fetch_build_context(conn, build_id)
            now = _now_iso()
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, failure_code = ?, failure_stage = ?,
                    failure_retryable = ?, error_message = ?, failed_at = ?,
                    attempt_count = attempt_count + 1, last_attempted_at = ?
                WHERE build_id = ?
                """,
                (
                    "failed",
                    failure_code,
                    failure_stage,
                    int(retryable),
                    error_message,
                    now,
                    now,
                    build_id,
                ),
            )
        self._record_event(
            "artifact_build_failed",
            {
                "document_id": str(build_row["document_id"]),
                "artifact_type": str(build_row["artifact_type"]),
                "build_id": build_id,
                "failure_code": failure_code,
                "failure_stage": failure_stage,
            },
        )

    def mark_projection_failed(
        self,
        projection_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        self._mark_projection_failed(
            projection_id=projection_id,
            failure_code=failure_code,
            failure_stage=failure_stage,
            retryable=retryable,
            error_message=error_message,
            delete_failure=False,
        )

    def mark_projection_delete_failed(
        self,
        projection_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        self._mark_projection_failed(
            projection_id=projection_id,
            failure_code=failure_code,
            failure_stage=failure_stage,
            retryable=retryable,
            error_message=error_message,
            delete_failure=True,
        )

    def mark_document_deleting(self, document_id: str) -> None:
        with self.connect() as conn:
            self._ensure_document(conn, document_id)
            now = _now_iso()
            artifact_rows = conn.execute(
                """
                SELECT DISTINCT artifact_type
                FROM artifact_builds
                WHERE document_id = ? AND deleted_at IS NULL AND status != ?
                """,
                (document_id, "deleted"),
            ).fetchall()
            conn.execute(
                """
                UPDATE artifact_documents
                SET status = ?, updated_at = ?
                WHERE document_id = ?
                """,
                ("deleting", now, document_id),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?
                WHERE document_id = ? AND deleted_at IS NULL AND status != ?
                """,
                ("deleting", document_id, "deleted"),
            )
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?
                WHERE build_id IN (
                    SELECT build_id
                    FROM artifact_builds
                    WHERE document_id = ? AND deleted_at IS NULL
                ) AND deleted_at IS NULL AND status != ?
                """,
                ("deleting", document_id, "deleted"),
            )
        for row in artifact_rows:
            self._record_event(
                "artifact_delete_started",
                {
                    "document_id": document_id,
                    "artifact_type": str(row["artifact_type"]),
                },
            )

    def mark_graph_projection_deleting(self, document_id: str) -> None:
        self.mark_projection_deleting_for_document(
            document_id,
            artifact_type="graph_evidence",
            target="infinity_graph_candidate",
        )

    def mark_projection_deleting_for_document(
        self,
        document_id: str,
        *,
        artifact_type: str,
        target: str,
    ) -> None:
        self._validate_artifact_type(artifact_type)
        self._validate_projection_target(target)
        expected_target = _ALLOWED_PROJECTION_TARGETS_BY_ARTIFACT_TYPE[artifact_type]
        if target != expected_target:
            raise ValueError(
                f"unsupported projection target for {artifact_type}: {target}"
            )
        now = _now_iso()
        with self.connect() as conn:
            self._ensure_document(conn, document_id)
            conn.execute(
                """
                UPDATE artifact_documents
                SET status = ?, updated_at = ?
                WHERE document_id = ?
                """,
                ("deleting", now, document_id),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?
                WHERE document_id = ? AND artifact_type = ? AND deleted_at IS NULL
                  AND status != ?
                """,
                ("deleting", document_id, artifact_type, "deleted"),
            )
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?
                WHERE projection_id IN (
                    SELECT p.projection_id
                    FROM artifact_projections p
                    JOIN artifact_builds b ON b.build_id = p.build_id
                    WHERE b.document_id = ? AND b.artifact_type = ?
                      AND p.target = ? AND p.deleted_at IS NULL
                ) AND status != ?
                """,
                (
                    "deleting",
                    document_id,
                    artifact_type,
                    target,
                    "deleted",
                ),
            )
        self._record_event(
            "artifact_delete_started",
            {
                "document_id": document_id,
                "artifact_type": artifact_type,
            },
        )

    def list_undeleted_build_ids(
        self, document_id: str, *, artifact_type: str
    ) -> list[str]:
        self._validate_artifact_type(artifact_type)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT build_id
                FROM artifact_builds
                WHERE document_id = ? AND artifact_type = ? AND deleted_at IS NULL
                ORDER BY created_at DESC, rowid DESC
                """,
                (document_id, artifact_type),
            ).fetchall()
        return [str(row["build_id"]) for row in rows]

    def mark_projection_delete_failed_for_document(
        self,
        document_id: str,
        *,
        target: str,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        for projection_id in self._projection_ids_for_document(
            document_id, target=target
        ):
            self.mark_projection_delete_failed(
                projection_id,
                failure_code=failure_code,
                failure_stage=failure_stage,
                retryable=retryable,
                error_message=error_message,
            )

    def mark_projection_delete_failed_for_build(
        self,
        build_id: str,
        *,
        target: str,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        for projection_id in self._projection_ids_for_build(build_id, target=target):
            self.mark_projection_delete_failed(
                projection_id,
                failure_code=failure_code,
                failure_stage=failure_stage,
                retryable=retryable,
                error_message=error_message,
            )

    def mark_projection_deleted_for_document(
        self, document_id: str, *, target: str
    ) -> None:
        now = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?, deleted_at = ?, failure_code = NULL,
                    failure_stage = NULL, failure_retryable = NULL,
                    error_message = NULL, failed_at = NULL
                WHERE projection_id IN (
                    SELECT p.projection_id
                    FROM artifact_projections p
                    JOIN artifact_builds b ON b.build_id = p.build_id
                    WHERE b.document_id = ? AND p.target = ? AND p.deleted_at IS NULL
                )
                """,
                ("deleted", now, document_id, target),
            )

    def mark_builds_deleted_for_document(
        self, document_id: str, *, artifact_type: str
    ) -> None:
        self._validate_artifact_type(artifact_type)
        now = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM active_artifacts
                WHERE artifact_type = ? AND document_id = ?
                """,
                (artifact_type, document_id),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, deleted_at = ?, failure_code = NULL,
                    failure_stage = NULL, failure_retryable = NULL,
                    error_message = NULL, failed_at = NULL
                WHERE document_id = ? AND artifact_type = ? AND deleted_at IS NULL
                """,
                ("deleted", now, document_id, artifact_type),
            )

    def mark_document_delete_failed(
        self,
        document_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
    ) -> None:
        now = _now_iso()
        with self.connect() as conn:
            self._ensure_document(conn, document_id)
            conn.execute(
                """
                UPDATE artifact_documents
                SET status = 'deleting', failure_code = ?, failure_stage = ?,
                    failure_retryable = ?, error_message = ?,
                    attempt_count = attempt_count + 1, last_attempted_at = ?,
                    updated_at = ?
                WHERE document_id = ?
                """,
                (
                    failure_code,
                    failure_stage,
                    int(retryable),
                    error_message,
                    now,
                    now,
                    document_id,
                ),
            )
        self._record_event(
            "artifact_delete_failed",
            {
                "document_id": document_id,
                "artifact_type": "document",
                "failure_code": failure_code,
                "failure_stage": failure_stage,
            },
        )

    def mark_sqlite_payloads_deleted_for_document(self, document_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM psi_node_source_chunks
                WHERE build_id IN (
                    SELECT build_id FROM artifact_builds WHERE document_id = ?
                )
                """,
                (document_id,),
            )
            conn.execute(
                """
                DELETE FROM psi_tree_edges
                WHERE build_id IN (
                    SELECT build_id FROM artifact_builds WHERE document_id = ?
                )
                """,
                (document_id,),
            )
            conn.execute(
                """
                DELETE FROM psi_tree_nodes
                WHERE build_id IN (
                    SELECT build_id FROM artifact_builds WHERE document_id = ?
                )
                """,
                (document_id,),
            )
            conn.execute("DELETE FROM psi_trees WHERE document_id = ?", (document_id,))
            for table_name in (
                "graph_entity_source_chunks",
                "graph_relationship_source_chunks",
                "graph_entities",
                "graph_relationships",
                "graph_evidence_batches",
            ):
                conn.execute(
                    f"DELETE FROM {table_name} WHERE document_id = ?", (document_id,)
                )

    def mark_document_deleted(self, document_id: str) -> None:
        now = _now_iso()
        with self.connect() as conn:
            active_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM active_artifacts WHERE document_id = ?",
                    (document_id,),
                ).fetchone()[0]
            )
            incomplete_build_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM artifact_builds
                    WHERE document_id = ? AND status != 'deleted'
                    """,
                    (document_id,),
                ).fetchone()[0]
            )
            incomplete_projection_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM artifact_projections AS projection
                    JOIN artifact_builds AS build ON build.build_id = projection.build_id
                    WHERE build.document_id = ? AND projection.status != 'deleted'
                    """,
                    (document_id,),
                ).fetchone()[0]
            )
            payload_count = sum(
                int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE document_id = ?",
                        (document_id,),
                    ).fetchone()[0]
                )
                for table_name in (
                    "psi_trees",
                    "graph_entities",
                    "graph_relationships",
                    "graph_evidence_batches",
                )
            )
            if (
                active_count
                or incomplete_build_count
                or incomplete_projection_count
                or payload_count
            ):
                raise ValueError(
                    "document delete cannot finalize before all artifacts and "
                    "projections are deleted and payloads are cleaned"
                )
            cursor = conn.execute(
                """
                UPDATE artifact_documents
                SET status = 'deleted', deleted_at = ?, updated_at = ?,
                    failure_code = NULL, failure_stage = NULL,
                    failure_retryable = NULL, error_message = NULL
                WHERE document_id = ?
                """,
                (now, now, document_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown artifact document: {document_id}")

    def mark_projection_repair_required(
        self,
        projection_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        error_message: str,
    ) -> None:
        now = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?, repair_required_at = ?, failure_code = ?,
                    failure_stage = ?, error_message = ?
                WHERE projection_id = ?
                """,
                (
                    "repair_pending",
                    now,
                    failure_code,
                    failure_stage,
                    error_message,
                    projection_id,
                ),
            )
            conn.execute(
                """
                UPDATE artifact_builds
                SET status = ?, repair_required_at = ?, failure_code = ?,
                    failure_stage = ?, error_message = ?
                WHERE build_id = (
                    SELECT build_id
                    FROM artifact_projections
                    WHERE projection_id = ?
                )
                """,
                (
                    "repair_pending",
                    now,
                    failure_code,
                    failure_stage,
                    error_message,
                    projection_id,
                ),
            )

    def record_orphan_projection(
        self,
        *,
        target: str,
        target_table: str,
        owner_build_id: str,
        failure_stage: str,
    ) -> None:
        self._validate_projection_target(target)
        now = _now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO orphan_projection_failures (
                    orphan_failure_id,
                    target,
                    target_table,
                    owner_build_id,
                    status,
                    failure_code,
                    failure_stage,
                    detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    target,
                    target_table,
                    owner_build_id,
                    "repair_pending",
                    "orphan_projection_detected",
                    failure_stage,
                    now,
                ),
            )

    def list_orphan_projection_failures(
        self,
    ) -> list[OrphanProjectionFailureRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    orphan_failure_id,
                    target,
                    target_table,
                    owner_build_id,
                    status,
                    failure_code,
                    failure_stage,
                    detected_at
                FROM orphan_projection_failures
                ORDER BY detected_at, rowid
                """
            ).fetchall()
        return [
            OrphanProjectionFailureRecord(
                orphan_failure_id=str(row["orphan_failure_id"]),
                target=str(row["target"]),
                target_table=str(row["target_table"]),
                owner_build_id=str(row["owner_build_id"]),
                status=str(row["status"]),
                failure_code=str(row["failure_code"]),
                failure_stage=str(row["failure_stage"]),
                detected_at=str(row["detected_at"]),
            )
            for row in rows
        ]

    def get_document(self, document_id: str) -> ArtifactDocumentRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT document_id, status, created_at, updated_at, deleted_at
                       , failure_code, failure_stage, failure_retryable,
                       error_message, attempt_count, last_attempted_at
                FROM artifact_documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return _document_from_row(row)

    def get_build(self, build_id: str) -> ArtifactBuildRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    build_id,
                    document_id,
                    artifact_type,
                    builder_version,
                    embedding_signature,
                    status,
                    failure_code,
                    failure_stage,
                    failure_retryable,
                    error_message,
                    attempt_count,
                    last_attempted_at,
                    created_at,
                    projected_at,
                    activated_at,
                    failed_at
                FROM artifact_builds
                WHERE build_id = ?
                """,
                (build_id,),
            ).fetchone()
        if row is None:
            return None
        return _build_from_row(row)

    def get_latest_build(
        self, artifact_type: str, document_id: str
    ) -> ArtifactBuildRecord | None:
        self._validate_artifact_type(artifact_type)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    build_id,
                    document_id,
                    artifact_type,
                    builder_version,
                    embedding_signature,
                    status,
                    failure_code,
                    failure_stage,
                    failure_retryable,
                    error_message,
                    attempt_count,
                    last_attempted_at,
                    created_at,
                    projected_at,
                    activated_at,
                    failed_at
                FROM artifact_builds
                WHERE artifact_type = ? AND document_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (artifact_type, document_id),
            ).fetchone()
        if row is None:
            return None
        return _build_from_row(row)

    def get_active_build(
        self, artifact_type: str, document_id: str
    ) -> ArtifactBuildRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    b.build_id,
                    b.document_id,
                    b.artifact_type,
                    b.builder_version,
                    b.embedding_signature,
                    b.status,
                    b.failure_code,
                    b.failure_stage,
                    b.failure_retryable,
                    b.error_message,
                    b.attempt_count,
                    b.last_attempted_at,
                    b.created_at,
                    b.projected_at,
                    b.activated_at,
                    b.failed_at
                FROM active_artifacts a
                JOIN artifact_builds b
                  ON b.build_id = a.active_build_id
                WHERE a.artifact_type = ? AND a.document_id = ?
                """,
                (artifact_type, document_id),
            ).fetchone()
        if row is None:
            return None
        return _build_from_row(row)

    def get_projection(self, projection_id: str) -> ProjectionRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    projection_id,
                    build_id,
                    target,
                    target_table,
                    status,
                    failure_code,
                    failure_stage,
                    failure_retryable,
                    error_message,
                    attempt_count,
                    last_attempted_at,
                    projected_at,
                    failed_at
                FROM artifact_projections
                WHERE projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
        if row is None:
            return None
        return _projection_from_row(row)

    def get_projection_for_build(
        self, build_id: str, *, target: str
    ) -> ProjectionRecord | None:
        self._validate_projection_target(target)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    projection_id,
                    build_id,
                    target,
                    target_table,
                    status,
                    failure_code,
                    failure_stage,
                    failure_retryable,
                    error_message,
                    attempt_count,
                    last_attempted_at,
                    projected_at,
                    failed_at
                FROM artifact_projections
                WHERE build_id = ? AND target = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (build_id, target),
            ).fetchone()
        if row is None:
            return None
        return _projection_from_row(row)

    def _mark_projection_failed(
        self,
        *,
        projection_id: str,
        failure_code: str,
        failure_stage: str,
        retryable: bool,
        error_message: str,
        delete_failure: bool,
    ) -> None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    p.build_id,
                    b.document_id,
                    b.artifact_type
                FROM artifact_projections p
                JOIN artifact_builds b ON b.build_id = p.build_id
                WHERE p.projection_id = ?
                """,
                (projection_id,),
            ).fetchone()
            if row is None:
                msg = f"unknown projection_id: {projection_id}"
                raise ValueError(msg)
            now = _now_iso()
            conn.execute(
                """
                UPDATE artifact_projections
                SET status = ?, failure_code = ?, failure_stage = ?,
                    failure_retryable = ?, error_message = ?, failed_at = ?,
                    attempt_count = attempt_count + 1, last_attempted_at = ?
                WHERE projection_id = ?
                """,
                (
                    "failed",
                    failure_code,
                    failure_stage,
                    int(retryable),
                    error_message,
                    now,
                    now,
                    projection_id,
                ),
            )
        self._record_event(
            "artifact_delete_failed"
            if delete_failure
            else "artifact_projection_failed",
            {
                "document_id": str(row["document_id"]),
                "artifact_type": str(row["artifact_type"]),
                "build_id": str(row["build_id"]),
                "projection_id": projection_id,
                "failure_code": failure_code,
                "failure_stage": failure_stage,
            },
        )

    def _validate_artifact_type(self, artifact_type: str) -> None:
        if artifact_type not in ARTIFACT_TYPES:
            msg = f"unsupported artifact_type: {artifact_type}"
            raise ValueError(msg)

    def _validate_projection_target(self, target: str) -> None:
        if target not in PROJECTION_TARGETS:
            msg = f"unsupported projection target: {target}"
            raise ValueError(msg)

    def _fetch_build_context(
        self, conn: sqlite3.Connection, build_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT build_id, document_id, artifact_type, status
            FROM artifact_builds
            WHERE build_id = ?
            """,
            (build_id,),
        ).fetchone()
        if row is None:
            msg = f"unknown build_id: {build_id}"
            raise ValueError(msg)
        return row

    def _ensure_document(self, conn: sqlite3.Connection, document_id: str) -> None:
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO artifact_documents (
                document_id,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(document_id) DO NOTHING
            """,
            (document_id, "active", now, now),
        )

    def _record_event(self, name: str, payload: dict[str, object]) -> None:
        self._recorder.record(ArtifactEvent(name=name, payload=payload))

    def _projection_ids_for_document(
        self, document_id: str, *, target: str
    ) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.projection_id
                FROM artifact_projections p
                JOIN artifact_builds b ON b.build_id = p.build_id
                WHERE b.document_id = ? AND p.target = ? AND p.deleted_at IS NULL
                """,
                (document_id, target),
            ).fetchall()
        return [str(row["projection_id"]) for row in rows]

    def _projection_ids_for_build(self, build_id: str, *, target: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT projection_id
                FROM artifact_projections
                WHERE build_id = ? AND target = ? AND deleted_at IS NULL
                """,
                (build_id, target),
            ).fetchall()
        return [str(row["projection_id"]) for row in rows]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _document_from_row(row: sqlite3.Row) -> ArtifactDocumentRecord:
    return ArtifactDocumentRecord(
        document_id=str(row["document_id"]),
        status=str(row["status"]),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        failure_stage=(
            None if row["failure_stage"] is None else str(row["failure_stage"])
        ),
        failure_retryable=(
            None if row["failure_retryable"] is None else bool(row["failure_retryable"])
        ),
        error_message=(
            None if row["error_message"] is None else str(row["error_message"])
        ),
        attempt_count=int(row["attempt_count"]),
        last_attempted_at=(
            None if row["last_attempted_at"] is None else str(row["last_attempted_at"])
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        deleted_at=None if row["deleted_at"] is None else str(row["deleted_at"]),
    )


def _build_from_row(row: sqlite3.Row) -> ArtifactBuildRecord:
    return ArtifactBuildRecord(
        build_id=str(row["build_id"]),
        document_id=str(row["document_id"]),
        artifact_type=str(row["artifact_type"]),
        builder_version=str(row["builder_version"]),
        embedding_signature=str(row["embedding_signature"]),
        status=str(row["status"]),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        failure_stage=None
        if row["failure_stage"] is None
        else str(row["failure_stage"]),
        failure_retryable=None
        if row["failure_retryable"] is None
        else bool(row["failure_retryable"]),
        error_message=None
        if row["error_message"] is None
        else str(row["error_message"]),
        attempt_count=int(row["attempt_count"]),
        last_attempted_at=None
        if row["last_attempted_at"] is None
        else str(row["last_attempted_at"]),
        created_at=str(row["created_at"]),
        projected_at=None if row["projected_at"] is None else str(row["projected_at"]),
        activated_at=None if row["activated_at"] is None else str(row["activated_at"]),
        failed_at=None if row["failed_at"] is None else str(row["failed_at"]),
    )


def _projection_from_row(row: sqlite3.Row) -> ProjectionRecord:
    return ProjectionRecord(
        projection_id=str(row["projection_id"]),
        build_id=str(row["build_id"]),
        target=str(row["target"]),
        target_table=str(row["target_table"]),
        status=str(row["status"]),
        failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        failure_stage=None
        if row["failure_stage"] is None
        else str(row["failure_stage"]),
        failure_retryable=None
        if row["failure_retryable"] is None
        else bool(row["failure_retryable"]),
        error_message=None
        if row["error_message"] is None
        else str(row["error_message"]),
        attempt_count=int(row["attempt_count"]),
        last_attempted_at=None
        if row["last_attempted_at"] is None
        else str(row["last_attempted_at"]),
        projected_at=None if row["projected_at"] is None else str(row["projected_at"]),
        failed_at=None if row["failed_at"] is None else str(row["failed_at"]),
    )
