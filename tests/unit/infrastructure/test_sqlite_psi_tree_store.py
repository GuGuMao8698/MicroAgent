from __future__ import annotations

import pytest

from ragflow_lite.domain.models.psi_tree import (
    PsiNode,
    PsiNodeSourceMapping,
    PsiTree,
    PsiTreeEdge,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_psi_tree_store import (
    SqlitePsiTreeStore,
)


def _tree_payload(
    build_id: str,
) -> tuple[PsiTree, list[PsiNode], list[PsiTreeEdge], list[PsiNodeSourceMapping]]:
    tree = PsiTree(
        build_id=build_id,
        document_id="doc-1",
        max_layer=2,
        highest_queryable_layer=2,
        metadata={"mode": "keyword"},
    )
    nodes = [
        PsiNode(
            node_id=f"{build_id}-root",
            build_id=build_id,
            layer=2,
            node_type="root",
            abstract_type="keyword",
            text="latency budget",
            summary_text=None,
            keyword_text="latency budget",
            source_document_id="doc-1",
        ),
        PsiNode(
            node_id=f"{build_id}-leaf",
            build_id=build_id,
            layer=0,
            node_type="leaf",
            abstract_type=None,
            text="source chunk text",
            summary_text=None,
            keyword_text=None,
            source_document_id="doc-1",
        ),
    ]
    edges = [
        PsiTreeEdge(
            build_id=build_id,
            parent_node_id=nodes[0].node_id,
            child_node_id=nodes[1].node_id,
            child_rank=0,
            edge_score=0.9,
        )
    ]
    mappings = [
        PsiNodeSourceMapping(
            build_id=build_id,
            node_id=nodes[0].node_id,
            source_chunk_id="chunk-1",
            source_rank=0,
            evidence_role="descendant",
        )
    ]
    return tree, nodes, edges, mappings


def _new_psi_build(registry: SqliteArtifactRegistry):
    return registry.create_build(
        document_id="doc-1",
        artifact_type="psi_tree",
        builder_version="psi-v1",
        embedding_signature="emb-v1",
    )


def test_store_and_load_document_scoped_psi_tree_payload(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    build = _new_psi_build(registry)
    tree, nodes, edges, mappings = _tree_payload(build.build_id)
    store = SqlitePsiTreeStore(db_path, registry=registry)

    store.upsert_tree(tree, nodes=nodes, edges=edges, mappings=mappings)

    assert store.get_tree(build.build_id) == tree
    assert store.get_nodes(build.build_id) == nodes
    assert store.get_children(build.build_id, nodes[0].node_id) == edges
    assert store.get_source_chunk_ids(build.build_id, nodes[0].node_id) == ["chunk-1"]


def test_active_tree_query_uses_active_artifact_and_projected_pointer(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    build = _new_psi_build(registry)
    tree, nodes, edges, mappings = _tree_payload(build.build_id)
    store = SqlitePsiTreeStore(db_path, registry=registry)
    store.upsert_tree(tree, nodes=nodes, edges=edges, mappings=mappings)

    assert store.list_active_queryable_trees() == []

    registry.mark_payload_complete(build.build_id)
    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_psi_node",
        target_table="psi_nodes",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)

    assert store.list_active_queryable_trees() == [tree]


def test_store_rejects_cross_build_or_dangling_tree_structure(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    build = _new_psi_build(registry)
    tree, nodes, _, mappings = _tree_payload(build.build_id)
    store = SqlitePsiTreeStore(db_path, registry=registry)
    bad_edge = PsiTreeEdge(
        build_id=build.build_id,
        parent_node_id=nodes[0].node_id,
        child_node_id="missing-node",
        child_rank=0,
        edge_score=0.1,
    )

    with pytest.raises(ValueError, match="outside its tree"):
        store.upsert_tree(tree, nodes=nodes, edges=[bad_edge], mappings=mappings)

    assert store.get_tree(build.build_id) is None


def test_replacing_build_payload_removes_stale_nodes_and_mappings(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    registry = SqliteArtifactRegistry(db_path)
    build = _new_psi_build(registry)
    tree, nodes, edges, mappings = _tree_payload(build.build_id)
    store = SqlitePsiTreeStore(db_path, registry=registry)
    store.upsert_tree(tree, nodes=nodes, edges=edges, mappings=mappings)

    replacement_tree = PsiTree(
        build_id=build.build_id,
        document_id="doc-1",
        max_layer=0,
        highest_queryable_layer=None,
        metadata={"mode": "leaf-only"},
    )
    replacement_node = PsiNode(
        node_id=f"{build.build_id}-replacement",
        build_id=build.build_id,
        layer=0,
        node_type="leaf",
        abstract_type=None,
        text="replacement",
        summary_text=None,
        keyword_text=None,
        source_document_id="doc-1",
    )
    store.upsert_tree(
        replacement_tree,
        nodes=[replacement_node],
        edges=[],
        mappings=[],
    )

    assert store.get_nodes(build.build_id) == [replacement_node]
    assert store.get_source_chunk_ids(build.build_id, nodes[0].node_id) == []
