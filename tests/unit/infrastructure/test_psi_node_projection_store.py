from __future__ import annotations

from typing import Any

import pytest

from ragflow_lite.domain.models.psi_tree import (
    PsiNode,
    PsiNodeSourceMapping,
    PsiTree,
)
from ragflow_lite.infrastructure.evidence.psi_node_fields import (
    PsiNodeProjectionError,
)
from ragflow_lite.infrastructure.evidence.psi_node_projection_store import (
    PsiNodeProjectionStore,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_psi_tree_store import (
    SqlitePsiTreeStore,
)


class _Embedder:
    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


class _RecordingProjectionIndex:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.inconsistent = False
        self.deleted_builds: list[str] = []

    def upsert_nodes(self, rows: list[dict[str, Any]]) -> None:
        build_id = str(rows[0]["build_id"])
        self.rows = [row for row in self.rows if row["build_id"] != build_id]
        self.rows.extend(rows)

    def delete_build(self, build_id: str) -> None:
        self.deleted_builds.append(build_id)
        self.rows = [row for row in self.rows if row["build_id"] != build_id]

    def delete_document(self, document_id: str) -> None:
        self.rows = [row for row in self.rows if row["document_id"] != document_id]

    def get_projected_node_ids(
        self, build_id: str, *, layer: int | None = None
    ) -> list[str]:
        if self.inconsistent:
            return []
        return sorted(
            str(row["psi_node_id"])
            for row in self.rows
            if row["build_id"] == build_id and (layer is None or row["layer"] == layer)
        )


def _write_tree(
    registry: SqliteArtifactRegistry,
    store: SqlitePsiTreeStore,
    *,
    keyword_text: str = "latency budget",
) -> str:
    build = registry.create_build(
        document_id="doc-1",
        artifact_type="psi_tree",
        builder_version="psi-v1",
        embedding_signature="emb-v1",
    )
    nodes = [
        PsiNode(
            node_id="root",
            build_id=build.build_id,
            layer=1,
            node_type="root",
            abstract_type="keyword",
            text="",
            summary_text=None,
            keyword_text=keyword_text,
            source_document_id="doc-1",
        ),
        PsiNode(
            node_id="leaf",
            build_id=build.build_id,
            layer=0,
            node_type="leaf",
            abstract_type=None,
            text="original source",
            summary_text=None,
            keyword_text=None,
            source_document_id="doc-1",
        ),
    ]
    mappings = [
        PsiNodeSourceMapping(
            build_id=build.build_id,
            node_id=node.node_id,
            source_chunk_id=f"chunk-{node.node_id}",
            source_rank=0,
            evidence_role="leaf" if node.node_type == "leaf" else "descendant",
        )
        for node in nodes
    ]
    store.upsert_tree(
        PsiTree(
            build_id=build.build_id,
            document_id="doc-1",
            max_layer=1,
            highest_queryable_layer=None,
        ),
        nodes=nodes,
        edges=[],
        mappings=mappings,
    )
    return build.build_id


def _projection_store(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    tree_store = SqlitePsiTreeStore(db_path, registry=registry)
    index = _RecordingProjectionIndex()
    projection_store = PsiNodeProjectionStore(
        tree_store=tree_store,
        psi_node_index=index,
        embedder=_Embedder(),
        registry=registry,
        target_table="psi_nodes",
    )
    return registry, tree_store, index, projection_store


def test_successful_projection_persists_layer_and_activates_build(tmp_path) -> None:
    registry, tree_store, index, projection_store = _projection_store(tmp_path)
    build_id = _write_tree(registry, tree_store)

    projection_store.project_tree(build_id)

    assert registry.get_active_build("psi_tree", "doc-1").build_id == build_id  # type: ignore[union-attr]
    assert tree_store.get_tree(build_id).highest_queryable_layer == 1  # type: ignore[union-attr]
    assert {row["projection_row_id"] for row in index.rows} == {
        f"{build_id}:root",
        f"{build_id}:leaf",
    }


def test_queryable_text_failure_is_explicit_and_does_not_activate(tmp_path) -> None:
    registry, tree_store, _, projection_store = _projection_store(tmp_path)
    build_id = _write_tree(registry, tree_store, keyword_text=" ")

    with pytest.raises(PsiNodeProjectionError, match="keyword_text"):
        projection_store.project_tree(build_id)

    build = registry.get_build(build_id)
    assert build is not None
    assert build.status == "failed"
    assert build.failure_code == "queryable_text_missing"
    assert registry.get_active_build("psi_tree", "doc-1") is None


def test_projection_inconsistency_marks_repair_pending(tmp_path) -> None:
    registry, tree_store, index, projection_store = _projection_store(tmp_path)
    build_id = _write_tree(registry, tree_store)
    index.inconsistent = True

    with pytest.raises(RuntimeError, match="does not match"):
        projection_store.project_tree(build_id)

    build = registry.get_build(build_id)
    assert build is not None
    assert build.status == "repair_pending"
    assert build.failure_code == "projection_inconsistent"


def test_rebuild_can_reuse_semantic_node_ids_before_active_switch(tmp_path) -> None:
    registry, tree_store, index, projection_store = _projection_store(tmp_path)
    first_build_id = _write_tree(registry, tree_store)
    projection_store.project_tree(first_build_id)
    second_build_id = _write_tree(registry, tree_store)

    projection_store.project_tree(second_build_id)

    active = registry.get_active_build("psi_tree", "doc-1")
    assert active is not None and active.build_id == second_build_id
    assert index.deleted_builds == [first_build_id]
    assert {row["build_id"] for row in index.rows} == {second_build_id}
