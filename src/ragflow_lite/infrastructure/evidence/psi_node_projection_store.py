from __future__ import annotations

from typing import Any, Protocol

from ragflow_lite.infrastructure.evidence.psi_node_fields import (
    PsiNodeProjectionError,
    build_psi_node_projection_row,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_psi_tree_store import (
    SqlitePsiTreeStore,
)


class PsiNodeProjectionIndex(Protocol):
    def upsert_nodes(self, rows: list[dict[str, Any]]) -> None: ...

    def delete_build(self, build_id: str) -> None: ...

    def delete_document(self, document_id: str) -> None: ...

    def get_projected_node_ids(
        self, build_id: str, *, layer: int | None = None
    ) -> list[str]: ...


class QueryEmbedder(Protocol):
    def embed_query(self, query: str) -> list[float]: ...


class PsiNodeProjectionStore:
    def __init__(
        self,
        *,
        tree_store: SqlitePsiTreeStore,
        psi_node_index: PsiNodeProjectionIndex,
        embedder: QueryEmbedder,
        registry: SqliteArtifactRegistry,
        target_table: str,
    ) -> None:
        self._tree_store = tree_store
        self._psi_node_index = psi_node_index
        self._embedder = embedder
        self._registry = registry
        self._target_table = target_table

    def project_tree(self, build_id: str) -> None:
        build = self._registry.get_build(build_id)
        tree = self._tree_store.get_tree(build_id)
        if build is None or build.artifact_type != "psi_tree" or tree is None:
            raise ValueError(f"unknown Psi tree build: {build_id}")
        nodes = self._tree_store.get_nodes(build_id)
        if not nodes:
            self._fail_build(
                build_id,
                failure_code="highest_queryable_layer_missing",
                failure_stage="validate_payload",
                error_message="Psi tree has no queryable nodes",
            )
            raise PsiNodeProjectionError("Psi tree has no queryable nodes")

        rows: list[dict[str, Any]] = []
        try:
            for node in nodes:
                source_chunk_ids = self._tree_store.get_source_chunk_ids(
                    build_id, node.node_id
                )
                if not source_chunk_ids:
                    raise PsiNodeProjectionError(
                        f"Psi node missing source mapping: {node.node_id}"
                    )
                fields = build_psi_node_projection_row(
                    node,
                    document_id=tree.document_id,
                    source_chunk_ids=source_chunk_ids,
                    vector=[],
                )
                fields["vec"] = self._embedder.embed_query(
                    str(fields["embedding_text"])
                )
                rows.append(fields)
        except PsiNodeProjectionError as exc:
            failure_code = (
                "source_mapping_missing"
                if "source mapping" in str(exc)
                else "queryable_text_missing"
            )
            self._fail_build(
                build_id,
                failure_code=failure_code,
                failure_stage="validate_payload",
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            self._fail_build(
                build_id,
                failure_code="unexpected_exception",
                failure_stage="project_infinity",
                error_message=str(exc),
            )
            raise

        highest_layer = max(node.layer for node in nodes)
        self._tree_store.set_highest_queryable_layer(build_id, highest_layer)
        self._registry.mark_payload_complete(build_id)
        projection = self._registry.create_projection(
            build_id=build_id,
            target="infinity_psi_node",
            target_table=self._target_table,
        )
        try:
            self._psi_node_index.upsert_nodes(rows)
        except Exception as exc:
            self._registry.mark_projection_failed(
                projection.projection_id,
                failure_code="infinity_projection_failed",
                failure_stage="project_infinity",
                retryable=True,
                error_message=str(exc),
            )
            self._fail_build(
                build_id,
                failure_code="infinity_projection_failed",
                failure_stage="project_infinity",
                error_message=str(exc),
            )
            raise

        expected_ids = sorted(
            node.node_id for node in nodes if node.layer == highest_layer
        )
        projected_ids = self._psi_node_index.get_projected_node_ids(
            build_id, layer=highest_layer
        )
        if projected_ids != expected_ids:
            message = "highest queryable layer projection does not match SQLite truth"
            self._registry.mark_projection_repair_required(
                projection.projection_id,
                failure_code="projection_inconsistent",
                failure_stage="project_infinity",
                error_message=message,
            )
            raise RuntimeError(message)

        self._registry.mark_projection_projected(projection.projection_id)
        superseded_build_ids = self._registry.activate_build(build_id)
        for superseded_build_id in superseded_build_ids:
            try:
                self._psi_node_index.delete_build(superseded_build_id)
            except Exception as exc:
                self._registry.mark_projection_delete_failed_for_build(
                    superseded_build_id,
                    target="infinity_psi_node",
                    failure_code="infinity_projection_delete_failed",
                    failure_stage="delete_projection",
                    retryable=True,
                    error_message=str(exc),
                )
                raise

    def mark_repair_required(
        self,
        *,
        build_id: str,
        failure_code: str,
        failure_stage: str,
        error_message: str,
    ) -> None:
        projection = self._registry.get_projection_for_build(
            build_id, target="infinity_psi_node"
        )
        if projection is None:
            raise ValueError(f"Psi projection missing for build: {build_id}")
        self._registry.mark_projection_repair_required(
            projection.projection_id,
            failure_code=failure_code,
            failure_stage=failure_stage,
            error_message=error_message,
        )

    def delete_document(self, document_id: str) -> None:
        self._registry.mark_projection_deleting_for_document(
            document_id,
            artifact_type="psi_tree",
            target="infinity_psi_node",
        )
        try:
            self._psi_node_index.delete_document(document_id)
        except Exception as exc:
            self._registry.mark_projection_delete_failed_for_document(
                document_id,
                target="infinity_psi_node",
                failure_code="infinity_projection_delete_failed",
                failure_stage="delete_projection",
                retryable=True,
                error_message=str(exc),
            )
            raise
        self._registry.mark_projection_deleted_for_document(
            document_id, target="infinity_psi_node"
        )
        self._registry.mark_builds_deleted_for_document(
            document_id, artifact_type="psi_tree"
        )

    def retry_delete_document(self, document_id: str) -> None:
        self.delete_document(document_id)

    def _fail_build(
        self,
        build_id: str,
        *,
        failure_code: str,
        failure_stage: str,
        error_message: str,
    ) -> None:
        self._registry.mark_build_failed(
            build_id,
            failure_code=failure_code,
            failure_stage=failure_stage,
            retryable=True,
            error_message=error_message,
        )
