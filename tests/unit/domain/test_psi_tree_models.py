from __future__ import annotations

from ragflow_lite.domain.models.psi_tree import (
    PsiNode,
    PsiNodeSourceMapping,
    PsiTree,
    PsiTreeEdge,
)


def test_psi_tree_models_preserve_node_edge_and_source_mapping_identity() -> None:
    tree = PsiTree(
        build_id="build-1",
        document_id="doc-1",
        max_layer=2,
        highest_queryable_layer=2,
        metadata={"builder": "test"},
    )
    node = PsiNode(
        node_id="psi-node-1",
        build_id="build-1",
        layer=2,
        node_type="root",
        abstract_type="keyword",
        text="latency budget",
        summary_text=None,
        keyword_text="latency budget",
        source_document_id="doc-1",
        metadata={"rank": 1},
    )
    edge = PsiTreeEdge(
        build_id="build-1",
        parent_node_id="psi-node-1",
        child_node_id="psi-node-2",
        child_rank=0,
        edge_score=0.9,
        metadata={"merge": "original-space"},
    )
    mapping = PsiNodeSourceMapping(
        node_id="psi-node-1",
        source_chunk_id="chunk-1",
        source_rank=0,
        evidence_role="descendant",
    )

    assert tree.highest_queryable_layer == 2
    assert node.node_id != mapping.source_chunk_id
    assert edge.parent_node_id == node.node_id
    assert mapping.evidence_role == "descendant"
