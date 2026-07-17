from __future__ import annotations

import sqlite3

from ragflow_lite.infrastructure.evidence.artifact_event_recorder import (
    InMemoryArtifactEventRecorder,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_schema import SCHEMA_VERSION


def test_schema_initialization_enables_foreign_keys_and_user_version(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)

    with registry.connect() as conn:
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert foreign_keys == 1
    assert user_version >= 1
    assert {
        "artifact_documents",
        "artifact_builds",
        "active_artifacts",
        "artifact_projections",
    }.issubset(table_names)


def test_schema_initialization_rejects_unsupported_user_version(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 99")

    registry = SqliteArtifactRegistry(db_path)

    try:
        registry.connect()
    except ValueError as exc:
        assert "schema" in str(exc).lower() or "unsupported" in str(exc).lower()
    else:
        raise AssertionError("expected unsupported schema version to raise")


def test_schema_initialization_upgrades_v1_database_with_psi_tables(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version = 1")

    registry = SqliteArtifactRegistry(db_path)
    with registry.connect() as conn:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        table_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert user_version == SCHEMA_VERSION
    assert {
        "psi_trees",
        "psi_tree_nodes",
        "psi_tree_edges",
        "psi_node_source_chunks",
    }.issubset(table_names)


def test_build_project_activate_and_supersede_are_transactional(tmp_path) -> None:
    recorder = InMemoryArtifactEventRecorder()
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3", recorder=recorder)

    first = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(first.build_id)
    projection = registry.create_projection(
        build_id=first.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(first.build_id)

    second = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v2",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(second.build_id)
    second_projection = registry.create_projection(
        build_id=second.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(second_projection.projection_id)
    registry.activate_build(second.build_id)

    active = registry.get_active_build("graph_evidence", "doc-1")
    old = registry.get_build(first.build_id)

    assert active is not None
    assert active.build_id == second.build_id
    assert active.status == "active"
    assert old is not None
    assert old.status == "superseded"
    assert [event.name for event in recorder.events] == [
        "artifact_build_started",
        "artifact_projection_started",
        "active_artifact_switched",
        "artifact_build_started",
        "artifact_projection_started",
        "active_artifact_switched",
    ]
    assert recorder.events[0].payload["document_id"] == "doc-1"
    assert recorder.events[0].payload["artifact_type"] == "graph_evidence"
    assert recorder.events[1].payload["target"] == "infinity_graph_candidate"
    assert recorder.events[-1].payload["build_id"] == second.build_id


def test_failed_projection_preserves_previous_active_build(tmp_path) -> None:
    recorder = InMemoryArtifactEventRecorder()
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3", recorder=recorder)
    first = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(first.build_id)
    projection = registry.create_projection(
        build_id=first.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(first.build_id)

    failed = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v2",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(failed.build_id)
    failed_projection = registry.create_projection(
        build_id=failed.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_failed(
        failed_projection.projection_id,
        failure_code="infinity_projection_failed",
        failure_stage="project_infinity",
        retryable=True,
        error_message="boom",
    )
    registry.mark_build_failed(
        failed.build_id,
        failure_code="infinity_projection_failed",
        failure_stage="project_infinity",
        retryable=True,
        error_message="boom",
    )

    active = registry.get_active_build("graph_evidence", "doc-1")
    failed_record = registry.get_build(failed.build_id)

    assert active is not None
    assert active.build_id == first.build_id
    assert active.status == "active"
    assert failed_record is not None
    assert failed_record.status == "failed"
    assert failed_record.failure_code == "infinity_projection_failed"
    assert failed_record.failure_stage == "project_infinity"
    assert failed_record.failure_retryable is True
    assert failed_record.attempt_count == 1
    assert failed_record.last_attempted_at is not None
    assert recorder.events[-2].name == "artifact_projection_failed"
    assert (
        recorder.events[-2].payload["projection_id"] == failed_projection.projection_id
    )
    assert recorder.events[-1].name == "artifact_build_failed"
    assert recorder.events[-1].payload["build_id"] == failed.build_id


def test_delete_is_tombstone_first_and_retryable(tmp_path) -> None:
    recorder = InMemoryArtifactEventRecorder()
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3", recorder=recorder)
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)
    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)
    psi_build = registry.create_build(
        document_id="doc-1",
        artifact_type="psi_tree",
        builder_version="psi-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(psi_build.build_id)
    psi_projection = registry.create_projection(
        build_id=psi_build.build_id,
        target="infinity_psi_node",
        target_table="psi_nodes",
    )

    registry.mark_document_deleting("doc-1")
    registry.mark_projection_delete_failed(
        projection.projection_id,
        failure_code="infinity_projection_delete_failed",
        failure_stage="delete_projection",
        retryable=True,
        error_message="delete failed",
    )

    document = registry.get_document("doc-1")
    build_record = registry.get_build(build.build_id)
    psi_build_record = registry.get_build(psi_build.build_id)
    projection_record = registry.get_projection(projection.projection_id)
    psi_projection_record = registry.get_projection(psi_projection.projection_id)

    assert document is not None
    assert document.status == "deleting"
    assert build_record is not None
    assert build_record.status == "deleting"
    assert psi_build_record is not None
    assert psi_build_record.status == "deleting"
    assert projection_record is not None
    assert projection_record.status == "failed"
    assert projection_record.failure_code == "infinity_projection_delete_failed"
    assert projection_record.failure_retryable is True
    assert projection_record.attempt_count == 1
    assert projection_record.last_attempted_at is not None
    assert psi_projection_record is not None
    assert psi_projection_record.status == "deleting"
    delete_started = [
        event for event in recorder.events if event.name == "artifact_delete_started"
    ]
    assert len(delete_started) == 2
    assert {event.payload["artifact_type"] for event in delete_started} == {
        "graph_evidence",
        "psi_tree",
    }
    assert recorder.events[-1].name == "artifact_delete_failed"
    assert recorder.events[-1].payload["projection_id"] == projection.projection_id


def test_active_pointer_inconsistency_is_recorded_before_serviceability(
    tmp_path,
) -> None:
    recorder = InMemoryArtifactEventRecorder()
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3", recorder=recorder)
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)

    registry.record_active_pointer_inconsistent(
        document_id="doc-1",
        artifact_type="graph_evidence",
        build_id=build.build_id,
        failure_stage="activate_build",
        error_message="could not prove active pointer switch",
    )

    active = registry.get_active_build("graph_evidence", "doc-1")
    failed = registry.get_build(build.build_id)

    assert active is None
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_code == "active_pointer_inconsistent"
    assert failed.attempt_count == 1
    assert failed.last_attempted_at is not None
    assert recorder.events[-1].name == "artifact_build_failed"
    assert recorder.events[-1].payload["failure_stage"] == "activate_build"


def test_orphan_projection_detection_marks_projection_repair_required(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")

    registry.record_orphan_projection(
        target="infinity_graph_candidate",
        target_table="graph_candidates",
        owner_build_id="missing-build",
        failure_stage="reconcile_projection",
    )

    orphan = registry.list_orphan_projection_failures()[0]
    assert orphan.target == "infinity_graph_candidate"
    assert orphan.target_table == "graph_candidates"
    assert orphan.owner_build_id == "missing-build"
    assert orphan.failure_code == "orphan_projection_detected"
    assert orphan.failure_stage == "reconcile_projection"


def test_projection_inconsistency_marks_payload_build_repair_pending(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)
    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)

    registry.mark_projection_repair_required(
        projection.projection_id,
        failure_code="projection_inconsistent",
        failure_stage="reconcile_projection",
        error_message="projection rows do not match sqlite payload truth",
    )

    assert registry.get_projection(projection.projection_id).status == "repair_pending"
    assert registry.get_build(build.build_id).status == "repair_pending"


def test_active_pointer_inconsistency_rejects_mismatched_owner_without_touching_other_active(
    tmp_path,
) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")

    doc1 = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(doc1.build_id)
    doc1_projection = registry.create_projection(
        build_id=doc1.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(doc1_projection.projection_id)
    registry.activate_build(doc1.build_id)

    doc2 = registry.create_build(
        document_id="doc-2",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(doc2.build_id)
    doc2_projection = registry.create_projection(
        build_id=doc2.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(doc2_projection.projection_id)
    registry.activate_build(doc2.build_id)

    try:
        registry.record_active_pointer_inconsistent(
            document_id="doc-2",
            artifact_type="graph_evidence",
            build_id=doc1.build_id,
            failure_stage="activate_build",
            error_message="mismatch",
        )
    except ValueError as exc:
        assert "mismatch" in str(exc).lower()
    else:
        raise AssertionError("expected mismatched owner to raise")

    active1 = registry.get_active_build("graph_evidence", "doc-1")
    active2 = registry.get_active_build("graph_evidence", "doc-2")

    assert active1 is not None
    assert active1.build_id == doc1.build_id
    assert active2 is not None
    assert active2.build_id == doc2.build_id


def test_create_projection_requires_projection_pending_state(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )

    try:
        registry.create_projection(
            build_id=build.build_id,
            target="infinity_graph_candidate",
            target_table="graph_candidates",
        )
    except ValueError as exc:
        assert "projection_pending" in str(exc)
    else:
        raise AssertionError(
            "expected create_projection before payload complete to raise"
        )


def test_mark_projection_projected_rejects_unknown_projection_id(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")

    try:
        registry.mark_projection_projected("missing-projection")
    except ValueError as exc:
        assert "projection" in str(exc).lower()
    else:
        raise AssertionError("expected unknown projection_id to raise")


def test_mark_projection_projected_rejects_failed_projection(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)
    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_failed(
        projection.projection_id,
        failure_code="infinity_projection_failed",
        failure_stage="project_infinity",
        retryable=True,
        error_message="boom",
    )

    try:
        registry.mark_projection_projected(projection.projection_id)
    except ValueError as exc:
        assert "status" in str(exc).lower()
    else:
        raise AssertionError("expected projected transition from failed to raise")


def test_activate_build_requires_projection_success(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)

    try:
        registry.activate_build(build.build_id)
    except ValueError as exc:
        assert "projected" in str(exc).lower()
    else:
        raise AssertionError(
            "expected activate_build before projection success to raise"
        )


def test_create_projection_rejects_wrong_target_for_artifact_type(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")

    graph_build = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(graph_build.build_id)
    try:
        registry.create_projection(
            build_id=graph_build.build_id,
            target="infinity_psi_node",
            target_table="psi_nodes",
        )
    except ValueError as exc:
        assert "graph_evidence" in str(exc)
    else:
        raise AssertionError("expected wrong graph target to raise")

    psi_build = registry.create_build(
        document_id="doc-2",
        artifact_type="psi_tree",
        builder_version="psi-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(psi_build.build_id)
    try:
        registry.create_projection(
            build_id=psi_build.build_id,
            target="infinity_graph_candidate",
            target_table="graph_candidates",
        )
    except ValueError as exc:
        assert "psi_tree" in str(exc)
    else:
        raise AssertionError("expected wrong psi target to raise")
