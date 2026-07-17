from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ragflow_lite.domain.models.psi_tree import (
    PsiNode,
    PsiNodeSourceMapping,
    PsiTree,
    PsiTreeEdge,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)


class SqlitePsiTreeStore:
    def __init__(
        self,
        db_path: Path,
        *,
        registry: SqliteArtifactRegistry | None = None,
    ) -> None:
        self._registry = registry or SqliteArtifactRegistry(db_path)

    def upsert_tree(
        self,
        tree: PsiTree,
        *,
        nodes: list[PsiNode],
        edges: list[PsiTreeEdge],
        mappings: list[PsiNodeSourceMapping],
    ) -> None:
        _validate_tree_payload(tree, nodes=nodes, edges=edges, mappings=mappings)
        build = self._registry.get_build(tree.build_id)
        if build is None:
            raise ValueError(f"unknown Psi build: {tree.build_id}")
        if build.artifact_type != "psi_tree":
            raise ValueError(f"build is not a Psi tree build: {tree.build_id}")
        if build.document_id != tree.document_id:
            raise ValueError("Psi tree document_id does not match its artifact build")

        with self._registry.connect() as conn:
            conn.execute(
                """
                DELETE FROM psi_node_source_chunks
                WHERE build_id = ?
                """,
                (tree.build_id,),
            )
            conn.execute(
                "DELETE FROM psi_tree_edges WHERE build_id = ?", (tree.build_id,)
            )
            conn.execute(
                "DELETE FROM psi_tree_nodes WHERE build_id = ?", (tree.build_id,)
            )
            conn.execute("DELETE FROM psi_trees WHERE build_id = ?", (tree.build_id,))
            conn.execute(
                """
                INSERT INTO psi_trees (
                    build_id,
                    document_id,
                    max_layer,
                    highest_queryable_layer,
                    created_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tree.build_id,
                    tree.document_id,
                    tree.max_layer,
                    tree.highest_queryable_layer,
                    build.created_at,
                    _to_json(tree.metadata),
                ),
            )
            conn.executemany(
                """
                INSERT INTO psi_tree_nodes (
                    node_id,
                    build_id,
                    layer,
                    node_type,
                    abstract_type,
                    text,
                    summary_text,
                    keyword_text,
                    source_document_id,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.node_id,
                        node.build_id,
                        node.layer,
                        node.node_type,
                        node.abstract_type,
                        node.text,
                        node.summary_text,
                        node.keyword_text,
                        node.source_document_id,
                        _to_json(node.metadata),
                    )
                    for node in nodes
                ],
            )
            conn.executemany(
                """
                INSERT INTO psi_tree_edges (
                    build_id,
                    parent_node_id,
                    child_node_id,
                    child_rank,
                    edge_score,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.build_id,
                        edge.parent_node_id,
                        edge.child_node_id,
                        edge.child_rank,
                        edge.edge_score,
                        _to_json(edge.metadata),
                    )
                    for edge in edges
                ],
            )
            conn.executemany(
                """
                INSERT INTO psi_node_source_chunks (
                    build_id,
                    node_id,
                    source_chunk_id,
                    source_rank,
                    evidence_role
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        mapping.build_id,
                        mapping.node_id,
                        mapping.source_chunk_id,
                        mapping.source_rank,
                        mapping.evidence_role,
                    )
                    for mapping in mappings
                ],
            )

    def get_tree(self, build_id: str) -> PsiTree | None:
        with self._registry.connect() as conn:
            row = conn.execute(
                """
                SELECT build_id, document_id, max_layer, highest_queryable_layer,
                       metadata_json
                FROM psi_trees
                WHERE build_id = ?
                """,
                (build_id,),
            ).fetchone()
        return None if row is None else _tree_from_row(row)

    def get_nodes(self, build_id: str) -> list[PsiNode]:
        with self._registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT node_id, build_id, layer, node_type, abstract_type, text,
                       summary_text, keyword_text, source_document_id, metadata_json
                FROM psi_tree_nodes
                WHERE build_id = ?
                ORDER BY layer DESC, node_id ASC
                """,
                (build_id,),
            ).fetchall()
        return [_node_from_row(row) for row in rows]

    def get_children(self, build_id: str, parent_node_id: str) -> list[PsiTreeEdge]:
        with self._registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT build_id, parent_node_id, child_node_id, child_rank,
                       edge_score, metadata_json
                FROM psi_tree_edges
                WHERE build_id = ? AND parent_node_id = ?
                ORDER BY child_rank ASC, child_node_id ASC
                """,
                (build_id, parent_node_id),
            ).fetchall()
        return [_edge_from_row(row) for row in rows]

    def get_source_mappings(
        self, build_id: str, node_id: str
    ) -> list[PsiNodeSourceMapping]:
        with self._registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT build_id, node_id, source_chunk_id, source_rank, evidence_role
                FROM psi_node_source_chunks
                WHERE build_id = ? AND node_id = ?
                ORDER BY source_rank ASC, source_chunk_id ASC
                """,
                (build_id, node_id),
            ).fetchall()
        return [
            PsiNodeSourceMapping(
                build_id=str(row["build_id"]),
                node_id=str(row["node_id"]),
                source_chunk_id=str(row["source_chunk_id"]),
                source_rank=int(row["source_rank"]),
                evidence_role=str(row["evidence_role"]),  # type: ignore[arg-type]
            )
            for row in rows
        ]

    def get_source_chunk_ids(self, build_id: str, node_id: str) -> list[str]:
        return [
            mapping.source_chunk_id
            for mapping in self.get_source_mappings(build_id, node_id)
        ]

    def set_highest_queryable_layer(self, build_id: str, layer: int) -> None:
        with self._registry.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE psi_trees
                SET highest_queryable_layer = ?
                WHERE build_id = ?
                """,
                (layer, build_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown Psi tree build: {build_id}")

    def list_active_queryable_trees(self) -> list[PsiTree]:
        with self._registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT tree.build_id, tree.document_id, tree.max_layer,
                       tree.highest_queryable_layer, tree.metadata_json
                FROM psi_trees AS tree
                JOIN artifact_builds AS build ON build.build_id = tree.build_id
                JOIN active_artifacts AS active
                  ON active.active_build_id = tree.build_id
                 AND active.artifact_type = 'psi_tree'
                 AND active.document_id = tree.document_id
                JOIN artifact_documents AS document
                  ON document.document_id = tree.document_id
                WHERE build.artifact_type = 'psi_tree'
                  AND build.status = 'active'
                  AND document.status = 'active'
                  AND tree.highest_queryable_layer IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM artifact_projections AS projection
                      WHERE projection.build_id = tree.build_id
                        AND projection.target = 'infinity_psi_node'
                        AND projection.status = 'projected'
                  )
                ORDER BY tree.document_id ASC, tree.build_id ASC
                """
            ).fetchall()
        return [_tree_from_row(row) for row in rows]


def _validate_tree_payload(
    tree: PsiTree,
    *,
    nodes: list[PsiNode],
    edges: list[PsiTreeEdge],
    mappings: list[PsiNodeSourceMapping],
) -> None:
    if not tree.build_id or not tree.document_id:
        raise ValueError("Psi tree requires build_id and document_id")
    if tree.max_layer < 0:
        raise ValueError("Psi tree max_layer must be non-negative")
    if tree.highest_queryable_layer is not None and not (
        0 <= tree.highest_queryable_layer <= tree.max_layer
    ):
        raise ValueError("highest_queryable_layer must be within the tree layers")

    nodes_by_id = {node.node_id: node for node in nodes}
    if len(nodes_by_id) != len(nodes):
        raise ValueError("Psi tree node ids must be unique")
    allowed_node_types = {"root", "internal", "leaf"}
    allowed_abstract_types = {None, "summative", "keyword"}
    for node in nodes:
        if not node.node_id:
            raise ValueError("Psi node requires node_id")
        if node.build_id != tree.build_id:
            raise ValueError("Psi node build_id does not match its tree")
        if node.source_document_id != tree.document_id:
            raise ValueError("Psi node source_document_id does not match its tree")
        if not 0 <= node.layer <= tree.max_layer:
            raise ValueError("Psi node layer is outside its tree")
        if node.node_type not in allowed_node_types:
            raise ValueError(f"unsupported Psi node_type: {node.node_type}")
        if node.abstract_type not in allowed_abstract_types:
            raise ValueError(f"unsupported Psi abstract_type: {node.abstract_type}")

    edge_keys: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.build_id != tree.build_id:
            raise ValueError("Psi edge build_id does not match its tree")
        parent = nodes_by_id.get(edge.parent_node_id)
        child = nodes_by_id.get(edge.child_node_id)
        if parent is None or child is None:
            raise ValueError("Psi edge references a node outside its tree")
        if parent.layer <= child.layer:
            raise ValueError("Psi edge parent must be on a higher layer than its child")
        if edge.child_rank < 0:
            raise ValueError("Psi edge child_rank must be non-negative")
        edge_key = (edge.parent_node_id, edge.child_node_id)
        if edge_key in edge_keys:
            raise ValueError("Psi tree edges must be unique")
        edge_keys.add(edge_key)

    mapping_keys: set[tuple[str, str]] = set()
    allowed_evidence_roles = {"leaf", "descendant", "summary_source"}
    for mapping in mappings:
        if mapping.build_id != tree.build_id:
            raise ValueError("Psi source mapping build_id does not match its tree")
        if mapping.node_id not in nodes_by_id:
            raise ValueError("Psi source mapping references a node outside its tree")
        if not mapping.source_chunk_id:
            raise ValueError("Psi source mapping requires source_chunk_id")
        if mapping.source_rank < 0:
            raise ValueError("Psi source mapping rank must be non-negative")
        if mapping.evidence_role not in allowed_evidence_roles:
            raise ValueError(f"unsupported Psi evidence_role: {mapping.evidence_role}")
        mapping_key = (mapping.node_id, mapping.source_chunk_id)
        if mapping_key in mapping_keys:
            raise ValueError("Psi source mappings must be unique")
        mapping_keys.add(mapping_key)


def _tree_from_row(row: Any) -> PsiTree:
    return PsiTree(
        build_id=str(row["build_id"]),
        document_id=str(row["document_id"]),
        max_layer=int(row["max_layer"]),
        highest_queryable_layer=(
            None
            if row["highest_queryable_layer"] is None
            else int(row["highest_queryable_layer"])
        ),
        metadata=_metadata_from_json(row["metadata_json"]),
    )


def _node_from_row(row: Any) -> PsiNode:
    return PsiNode(
        node_id=str(row["node_id"]),
        build_id=str(row["build_id"]),
        layer=int(row["layer"]),
        node_type=str(row["node_type"]),  # type: ignore[arg-type]
        abstract_type=(
            None if row["abstract_type"] is None else str(row["abstract_type"])
        ),  # type: ignore[arg-type]
        text=str(row["text"]),
        summary_text=None if row["summary_text"] is None else str(row["summary_text"]),
        keyword_text=None if row["keyword_text"] is None else str(row["keyword_text"]),
        source_document_id=str(row["source_document_id"]),
        metadata=_metadata_from_json(row["metadata_json"]),
    )


def _edge_from_row(row: Any) -> PsiTreeEdge:
    return PsiTreeEdge(
        build_id=str(row["build_id"]),
        parent_node_id=str(row["parent_node_id"]),
        child_node_id=str(row["child_node_id"]),
        child_rank=int(row["child_rank"]),
        edge_score=float(row["edge_score"]),
        metadata=_metadata_from_json(row["metadata_json"]),
    )


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _metadata_from_json(value: object) -> dict[str, Any]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        raise ValueError("Psi metadata must decode to an object")
    return loaded
