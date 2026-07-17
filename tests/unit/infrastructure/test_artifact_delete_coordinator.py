from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.evidence.artifact_delete_coordinator import (
    ArtifactDeleteCoordinator,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)


class _ArtifactLifecycle:
    def __init__(
        self,
        registry: SqliteArtifactRegistry,
        *,
        artifact_type: str,
        target: str,
    ) -> None:
        self.registry = registry
        self.artifact_type = artifact_type
        self.target = target
        self.calls: list[str] = []
        self.fail = False

    def delete_document(self, document_id: str) -> None:
        self.calls.append(document_id)
        if self.fail:
            raise RuntimeError(f"{self.artifact_type} delete failed")
        self.registry.mark_projection_deleted_for_document(
            document_id, target=self.target
        )
        self.registry.mark_builds_deleted_for_document(
            document_id, artifact_type=self.artifact_type
        )


class _MainChunkLifecycle:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def delete_document(self, document_id: str) -> None:
        self.calls.append(document_id)
        if self.fail:
            raise RuntimeError("main chunk delete failed")


def _active_build(
    registry: SqliteArtifactRegistry, artifact_type: str, target: str
) -> None:
    build = registry.create_build(
        document_id="doc-1",
        artifact_type=artifact_type,
        builder_version=f"{artifact_type}-v1",
        embedding_signature="emb-v1",
    )
    registry.mark_payload_complete(build.build_id)
    projection = registry.create_projection(
        build_id=build.build_id,
        target=target,
        target_table=target,
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)


def _coordinator(tmp_path):
    registry = SqliteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    _active_build(registry, "graph_evidence", "infinity_graph_candidate")
    _active_build(registry, "psi_tree", "infinity_psi_node")
    graph = _ArtifactLifecycle(
        registry,
        artifact_type="graph_evidence",
        target="infinity_graph_candidate",
    )
    psi = _ArtifactLifecycle(
        registry, artifact_type="psi_tree", target="infinity_psi_node"
    )
    main = _MainChunkLifecycle()
    coordinator = ArtifactDeleteCoordinator(
        registry=registry,
        graph_lifecycle=graph,
        psi_lifecycle=psi,
        main_chunk_lifecycle=main,
    )
    return registry, graph, psi, main, coordinator


def test_document_delete_finalizes_only_after_all_lifecycles(tmp_path) -> None:
    registry, graph, psi, main, coordinator = _coordinator(tmp_path)

    coordinator.delete_document("doc-1")

    assert graph.calls == psi.calls == main.calls == ["doc-1"]
    document = registry.get_document("doc-1")
    assert document is not None and document.status == "deleted"


def test_psi_delete_failure_is_persisted_and_skips_main_chunks(tmp_path) -> None:
    registry, _, psi, main, coordinator = _coordinator(tmp_path)
    psi.fail = True

    with pytest.raises(RuntimeError, match="psi_tree delete failed"):
        coordinator.delete_document("doc-1")

    document = registry.get_document("doc-1")
    assert document is not None
    assert document.status == "deleting"
    assert document.failure_code == "infinity_projection_delete_failed"
    assert document.failure_stage == "delete_psi_projection"
    assert main.calls == []


def test_main_chunk_failure_is_persisted_and_retry_resumes(tmp_path) -> None:
    registry, _, _, main, coordinator = _coordinator(tmp_path)
    main.fail = True

    with pytest.raises(RuntimeError, match="main chunk delete failed"):
        coordinator.delete_document("doc-1")

    document = registry.get_document("doc-1")
    assert document is not None
    assert document.failure_code == "main_chunk_delete_failed"
    main.fail = False

    coordinator.retry_delete_document("doc-1")

    document = registry.get_document("doc-1")
    assert document is not None and document.status == "deleted"
