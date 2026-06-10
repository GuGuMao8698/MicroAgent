from __future__ import annotations

import sqlite3
import uuid

import pytest

from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence import sqlite_artifact_registry
from ragflow_lite.infrastructure.evidence import sqlite_graph_evidence_store
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_store import (
    SqliteGraphEvidenceStore,
)


def _batch(document_id: str, suffix: str = "a") -> GraphEvidenceBatch:
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[
            EntityEvidence(
                entity_id=f"ent-{suffix}",
                document_id=document_id,
                name="Latency Budget",
                entity_type="concept",
                description="A budget for query latency.",
                source_chunk_ids=[f"chunk-{suffix}-1", f"chunk-{suffix}-2"],
                metadata={"rank": 1, "aliases": ["latency"]},
            )
        ],
        relations=[
            RelationEvidence(
                relation_id=f"rel-{suffix}",
                document_id=document_id,
                source_entity_id=f"ent-{suffix}",
                target_entity_id=f"ent-{suffix}-target",
                source_entity_name="Latency Budget",
                target_entity_name="Query Planner",
                description="The planner consumes the latency budget.",
                keywords=["latency", "planner"],
                weight=0.75,
                source_chunk_ids=[f"chunk-{suffix}-2"],
                metadata={"confidence": 0.9},
            )
        ],
        metadata={"extractor": "test", "nested": {"ok": True}},
    )


def test_upsert_and_get_round_trips_raw_graph_evidence(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    store = SqliteGraphEvidenceStore(tmp_path / "artifacts.sqlite3")
    batch = _batch("doc-1")

    result = store.upsert_document_evidence(batch)
    build = registry.get_latest_build("graph_evidence", "doc-1")

    assert build is not None

    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)

    loaded = store.get_document_evidence("doc-1")

    assert result.document_id == "doc-1"
    assert result.entity_count == 1
    assert result.relation_count == 1
    assert loaded == batch


def test_replacement_is_atomic_at_document_scope(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    store = SqliteGraphEvidenceStore(tmp_path / "artifacts.sqlite3", registry=registry)

    store.upsert_document_evidence(_batch("doc-1", suffix="old"))
    old_build = registry.get_latest_build("graph_evidence", "doc-1")

    assert old_build is not None

    old_projection = registry.create_projection(
        build_id=old_build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(old_projection.projection_id)
    registry.activate_build(old_build.build_id)

    replacement = _batch("doc-1", suffix="new")
    store.upsert_document_evidence(replacement)

    assert store.get_document_evidence("doc-1") == _batch("doc-1", suffix="old")

    new_build = registry.get_latest_build("graph_evidence", "doc-1")

    assert new_build is not None
    assert new_build.build_id != old_build.build_id
    assert store.get_build_evidence(new_build.build_id) == replacement


def test_delete_tombstones_document_payload_for_graph_store_port(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    store = SqliteGraphEvidenceStore(tmp_path / "artifacts.sqlite3", registry=registry)

    store.upsert_document_evidence(_batch("doc-1"))
    store.delete_document("doc-1")

    assert store.get_document_evidence("doc-1") is None

    document = registry.get_document("doc-1")

    assert document is not None
    assert document.status == "deleting"


def test_payload_write_failure_marks_build_failed_and_reraises(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    store = SqliteGraphEvidenceStore(tmp_path / "artifacts.sqlite3", registry=registry)

    def _boom(*args, **kwargs) -> None:
        raise sqlite3.IntegrityError("forced sqlite failure")

    monkeypatch.setattr(sqlite_graph_evidence_store, "_insert_entity_source_chunks", _boom)

    with pytest.raises(sqlite3.IntegrityError, match="forced sqlite failure"):
        store.upsert_document_evidence(_batch("doc-1"))

    build = registry.get_latest_build("graph_evidence", "doc-1")

    assert build is not None
    assert build.status == "failed"
    assert build.failure_code == "sqlite_write_failed"
    assert build.failure_stage == "write_sqlite"
    assert build.failure_retryable is True
    assert build.error_message == "forced sqlite failure"
    assert build.attempt_count == 1
    assert build.last_attempted_at is not None


def test_round_trip_preserves_entity_relation_and_source_chunk_order(tmp_path) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    store = SqliteGraphEvidenceStore(tmp_path / "artifacts.sqlite3", registry=registry)
    batch = GraphEvidenceBatch(
        document_id="doc-1",
        entities=[
            EntityEvidence(
                entity_id="entity-z",
                document_id="doc-1",
                name="Second",
                entity_type="concept",
                description="Second entity in raw order.",
                source_chunk_ids=["chunk-2", "chunk-2", "chunk-1"],
                metadata={"rank": 2},
            ),
            EntityEvidence(
                entity_id="entity-a",
                document_id="doc-1",
                name="First",
                entity_type="concept",
                description="First entity in raw order.",
                source_chunk_ids=["chunk-3", "chunk-3"],
                metadata={"rank": 1},
            ),
        ],
        relations=[
            RelationEvidence(
                relation_id="relation-z",
                document_id="doc-1",
                source_entity_id="entity-z",
                target_entity_id="entity-a",
                source_entity_name="Second",
                target_entity_name="First",
                description="Second relation in raw order.",
                keywords=["beta", "alpha"],
                weight=0.2,
                source_chunk_ids=["rel-chunk-2", "rel-chunk-2", "rel-chunk-1"],
                metadata={"rank": 2},
            ),
            RelationEvidence(
                relation_id="relation-a",
                document_id="doc-1",
                source_entity_id="entity-a",
                target_entity_id="entity-z",
                source_entity_name="First",
                target_entity_name="Second",
                description="First relation in raw order.",
                keywords=["gamma"],
                weight=0.8,
                source_chunk_ids=["rel-chunk-3", "rel-chunk-3"],
                metadata={"rank": 1},
            ),
        ],
        metadata={"extractor": "test"},
    )

    store.upsert_document_evidence(batch)
    build = registry.get_latest_build("graph_evidence", "doc-1")

    assert build is not None

    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)

    assert store.get_document_evidence("doc-1") == batch


def test_get_latest_build_prefers_second_insert_when_created_at_ties(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    build_ids = iter(
        [
            uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
            uuid.UUID("00000000-0000-0000-0000-000000000000"),
        ]
    )
    monkeypatch.setattr(
        sqlite_artifact_registry,
        "_now_iso",
        lambda: "2026-06-10T00:00:00+00:00",
    )
    monkeypatch.setattr(sqlite_artifact_registry.uuid, "uuid4", lambda: next(build_ids))

    first = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v1",
        embedding_signature="emb-v1",
    )
    second = registry.create_build(
        document_id="doc-1",
        artifact_type="graph_evidence",
        builder_version="graph-v2",
        embedding_signature="emb-v1",
    )

    latest = registry.get_latest_build("graph_evidence", "doc-1")

    assert latest is not None
    assert first.created_at == second.created_at
    assert latest.build_id == second.build_id
