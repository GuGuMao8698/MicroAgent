from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_store import (
    SqliteGraphEvidenceStore,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_projection_store import (
    SqliteGraphProjectionStore,
)


@dataclass
class _FakeCandidateIndex:
    projected_by_build: dict[str, GraphEvidenceBatch] = field(default_factory=dict)
    deleted_builds: list[str] = field(default_factory=list)
    deleted_documents: list[str] = field(default_factory=list)
    fail_next_upsert: bool = False
    fail_next_delete_build: bool = False
    fail_next_delete_document: bool = False

    def upsert_build_evidence(self, build_id: str, batch: GraphEvidenceBatch) -> None:
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("candidate upsert failed")
        self.projected_by_build[build_id] = batch

    def delete_build(self, build_id: str) -> None:
        if self.fail_next_delete_build:
            self.fail_next_delete_build = False
            raise RuntimeError("candidate delete failed")
        self.deleted_builds.append(build_id)
        self.projected_by_build.pop(build_id, None)

    def delete_document(self, document_id: str) -> None:
        if self.fail_next_delete_document:
            self.fail_next_delete_document = False
            raise RuntimeError("candidate delete document failed")
        self.deleted_documents.append(document_id)
        for build_id, batch in list(self.projected_by_build.items()):
            if batch.document_id == document_id:
                self.projected_by_build.pop(build_id)


def _batch(document_id: str, *, suffix: str) -> GraphEvidenceBatch:
    entity = EntityEvidence(
        entity_id=f"entity-{suffix}",
        document_id=document_id,
        name=f"Python {suffix}",
        entity_type="language",
        description=f"description {suffix}",
        source_chunk_ids=[f"chunk-{suffix}"],
    )
    relation = RelationEvidence(
        relation_id=f"relation-{suffix}",
        document_id=document_id,
        source_entity_id=entity.entity_id,
        target_entity_id=f"target-{suffix}",
        source_entity_name=entity.name,
        target_entity_name=f"Target {suffix}",
        description=f"relation {suffix}",
        keywords=[f"keyword-{suffix}"],
        weight=1.0,
        source_chunk_ids=[f"chunk-{suffix}"],
    )
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[entity],
        relations=[relation],
    )


def _build_store(
    tmp_path: Path, candidate_index: _FakeCandidateIndex | None = None
) -> tuple[SqliteGraphProjectionStore, SqliteArtifactRegistry, _FakeCandidateIndex]:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    graph_store = SqliteGraphEvidenceStore(db_path, registry=registry)
    fake_index = candidate_index or _FakeCandidateIndex()
    store = SqliteGraphProjectionStore(
        graph_store=graph_store,
        candidate_index=fake_index,
        registry=registry,
        target_table="graph_candidates",
    )
    return store, registry, fake_index


def test_successful_projection_activates_a_new_graph_evidence_build(
    tmp_path: Path,
) -> None:
    store, registry, candidate_index = _build_store(tmp_path)

    result = store.upsert_document_evidence(_batch("doc-1", suffix="a"))

    assert result == GraphEvidenceWriteResult(
        document_id="doc-1",
        entity_count=1,
        relation_count=1,
    )
    active = registry.get_active_build("graph_evidence", "doc-1")
    assert active is not None
    assert active.status == "active"
    assert set(candidate_index.projected_by_build) == {active.build_id}
    assert candidate_index.deleted_builds == []
    projections = []
    with registry.connect() as conn:
        projections = conn.execute(
            """
            SELECT target_table
            FROM artifact_projections
            WHERE build_id = ?
            """,
            (active.build_id,),
        ).fetchall()
    assert [row["target_table"] for row in projections] == ["graph_candidates"]


def test_projection_failure_preserves_previous_active_build_and_candidate_rows(
    tmp_path: Path,
) -> None:
    store, registry, candidate_index = _build_store(tmp_path)
    store.upsert_document_evidence(_batch("doc-1", suffix="old"))
    previous_active = registry.get_active_build("graph_evidence", "doc-1")
    assert previous_active is not None

    candidate_index.fail_next_upsert = True
    with pytest.raises(RuntimeError, match="candidate upsert failed"):
        store.upsert_document_evidence(_batch("doc-1", suffix="new"))

    failed = registry.get_latest_build("graph_evidence", "doc-1")
    active = registry.get_active_build("graph_evidence", "doc-1")
    assert failed is not None
    assert failed.build_id != previous_active.build_id
    assert failed.status == "failed"
    assert failed.failure_code == "infinity_projection_failed"
    assert failed.failure_stage == "project_infinity"
    assert active is not None
    assert active.build_id == previous_active.build_id
    assert set(candidate_index.projected_by_build) == {previous_active.build_id}
    current = store.get_document_evidence("doc-1")
    assert current is not None
    assert current.entities[0].name == "Python old"


def test_delete_marks_tombstone_before_projection_cleanup_and_clears_active_graph_build(
    tmp_path: Path,
) -> None:
    store, registry, candidate_index = _build_store(tmp_path)
    store.upsert_document_evidence(_batch("doc-1", suffix="a"))
    active = registry.get_active_build("graph_evidence", "doc-1")
    assert active is not None

    store.delete_document("doc-1")

    document = registry.get_document("doc-1")
    deleted_build = registry.get_build(active.build_id)
    assert document is not None
    assert document.status == "deleting"
    assert deleted_build is not None
    assert deleted_build.status == "deleted"
    assert registry.get_active_build("graph_evidence", "doc-1") is None
    assert candidate_index.deleted_builds == [active.build_id]
    assert candidate_index.deleted_documents == []


def test_superseded_projection_cleanup_failure_is_recorded_after_activation(
    tmp_path: Path,
) -> None:
    candidate_index = _FakeCandidateIndex()
    store, registry, candidate_index = _build_store(tmp_path, candidate_index)
    store.upsert_document_evidence(_batch("doc-1", suffix="old"))
    old_active = registry.get_active_build("graph_evidence", "doc-1")
    assert old_active is not None

    candidate_index.fail_next_delete_build = True
    with pytest.raises(RuntimeError, match="candidate delete failed"):
        store.upsert_document_evidence(_batch("doc-1", suffix="new"))

    new_active = registry.get_active_build("graph_evidence", "doc-1")
    old_build = registry.get_build(old_active.build_id)
    assert new_active is not None
    assert new_active.build_id != old_active.build_id
    assert new_active.status == "active"
    assert old_build is not None
    assert old_build.status == "superseded"
    assert old_active.build_id in candidate_index.projected_by_build
    with registry.connect() as conn:
        projection_row = conn.execute(
            """
            SELECT status, failure_code, failure_stage
            FROM artifact_projections
            WHERE build_id = ? AND target = ?
            """,
            (old_active.build_id, "infinity_graph_candidate"),
        ).fetchone()
    assert projection_row is not None
    assert str(projection_row["status"]) in {"failed", "repair_pending"}
    assert str(projection_row["failure_code"]) == "infinity_projection_delete_failed"
    assert str(projection_row["failure_stage"]) == "delete_projection"
