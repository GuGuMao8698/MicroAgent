from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ragflow_lite.domain.models import (
    GroundedAuxiliaryQuery,
    PsiRetrievalStatus,
    PsiTree,
)
from ragflow_lite.infrastructure.evidence.infinity_psi_node_index import PsiNodeHit
from ragflow_lite.infrastructure.retrievers.psi_node_scorer import PsiNodeRef


@dataclass(frozen=True, slots=True)
class PsiTraversalConfig:
    max_start_nodes_global: int = 20
    max_start_nodes_per_document: int = 3
    max_documents_per_query: int = 10
    max_children_per_parent_per_layer: int = 5
    max_total_scored_nodes: int = 200

    def __post_init__(self) -> None:
        if (
            min(
                self.max_start_nodes_global,
                self.max_start_nodes_per_document,
                self.max_documents_per_query,
                self.max_children_per_parent_per_layer,
                self.max_total_scored_nodes,
            )
            < 1
        ):
            raise ValueError("Psi traversal budgets must be positive")


@dataclass(slots=True)
class PsiTraversalResult:
    selected_nodes: list[PsiNodeRef]
    source_chunk_ids: list[str]
    status: PsiRetrievalStatus

    @property
    def selected_node_ids(self) -> list[str]:
        return [node.node_id for node in self.selected_nodes]


class PsiTraversalTreeStore(Protocol):
    def list_active_queryable_trees(self) -> list[PsiTree]: ...

    def get_node_ids(self, build_id: str, *, layer: int) -> list[str]: ...

    def get_child_node_ids(self, build_id: str, parent_node_id: str) -> list[str]: ...

    def get_source_chunk_ids(self, build_id: str, node_id: str) -> list[str]: ...


class PsiTraversalScorer(Protocol):
    def score(
        self,
        request: GroundedAuxiliaryQuery,
        *,
        allowed_nodes: list[PsiNodeRef],
        top_k: int,
    ) -> list[PsiNodeHit]: ...


class PsiProjectionInconsistentError(RuntimeError):
    def __init__(self, build_id: str, message: str) -> None:
        super().__init__(message)
        self.build_id = build_id


class PsiTopDownTraverser:
    def __init__(
        self,
        *,
        tree_store: PsiTraversalTreeStore,
        scorer: PsiTraversalScorer,
        config: PsiTraversalConfig | None = None,
    ) -> None:
        self._tree_store = tree_store
        self._scorer = scorer
        self._config = config or PsiTraversalConfig()

    def traverse(
        self, request: GroundedAuxiliaryQuery, top_k: int
    ) -> PsiTraversalResult:
        trees = self._tree_store.list_active_queryable_trees()[
            : self._config.max_documents_per_query
        ]
        if not trees:
            return self._empty_result(request, "no_active_tree", state="skipped")

        start_nodes = self._start_nodes(trees)
        if not start_nodes:
            return self._empty_result(request, "no_queryable_start_nodes", trees=trees)
        budget_exhausted = len(start_nodes) > self._config.max_total_scored_nodes
        start_nodes = start_nodes[: self._config.max_total_scored_nodes]
        scored_count = len(start_nodes)
        allowed = {(node.build_id, node.node_id) for node in start_nodes}
        queue = self._scorer.score(
            request,
            allowed_nodes=start_nodes,
            top_k=min(self._config.max_start_nodes_global, len(start_nodes)),
        )
        self._validate_hits(queue, allowed)

        selected: list[PsiNodeRef] = []
        source_ids: list[str] = []
        source_seen: set[str] = set()
        missing_mapping = False
        min_layer: int | None = None
        selected_builds: set[str] = set()

        while queue:
            hit = queue.pop(0)
            ref = PsiNodeRef(hit.build_id, hit.psi_node_id)
            selected.append(ref)
            selected_builds.add(hit.build_id)
            min_layer = hit.layer if min_layer is None else min(min_layer, hit.layer)
            children = self._tree_store.get_child_node_ids(
                hit.build_id, hit.psi_node_id
            )[: self._config.max_children_per_parent_per_layer]
            if children:
                remaining = self._config.max_total_scored_nodes - scored_count
                if remaining <= 0:
                    budget_exhausted = True
                    children = []
                elif len(children) > remaining:
                    budget_exhausted = True
                    children = children[:remaining]
                if children:
                    child_refs = [
                        PsiNodeRef(hit.build_id, node_id) for node_id in children
                    ]
                    child_allowed = {
                        (node.build_id, node.node_id) for node in child_refs
                    }
                    child_hits = self._scorer.score(
                        request,
                        allowed_nodes=child_refs,
                        top_k=len(child_refs),
                    )
                    self._validate_hits(child_hits, child_allowed)
                    scored_count += len(child_refs)
                    queue.extend(child_hits)
                    continue

            mapped = self._tree_store.get_source_chunk_ids(
                hit.build_id, hit.psi_node_id
            )
            if not mapped:
                missing_mapping = True
            for chunk_id in mapped:
                if chunk_id not in source_seen:
                    source_seen.add(chunk_id)
                    source_ids.append(chunk_id)

        if budget_exhausted:
            state, stop_reason, failure_code = (
                "degraded",
                "budget_exhausted",
                "budget_exhausted",
            )
        elif missing_mapping:
            state, stop_reason, failure_code = (
                "degraded",
                "source_mapping_missing",
                "source_mapping_missing",
            )
        else:
            state, stop_reason, failure_code = "success", "leaf_reached", None
        return PsiTraversalResult(
            selected_nodes=selected,
            source_chunk_ids=source_ids,
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state=state,
                stop_reason=stop_reason,
                fallback_source="none",
                failure_code=failure_code,
                trees_considered=len(trees),
                selected_tree_count=len(selected_builds),
                start_nodes_scored=min(len(start_nodes), scored_count),
                nodes_traversed=len(selected),
                max_layer_reached=min_layer,
                mapped_source_chunk_count=len(source_ids),
            ),
        )

    def _start_nodes(self, trees: list[PsiTree]) -> list[PsiNodeRef]:
        result: list[PsiNodeRef] = []
        for tree in trees:
            layer = tree.highest_queryable_layer
            if layer is None:
                continue
            node_ids = self._tree_store.get_node_ids(tree.build_id, layer=layer)
            result.extend(
                PsiNodeRef(tree.build_id, node_id)
                for node_id in node_ids[: self._config.max_start_nodes_per_document]
            )
            if len(result) >= self._config.max_start_nodes_global:
                return result[: self._config.max_start_nodes_global]
        return result

    @staticmethod
    def _validate_hits(hits: list[PsiNodeHit], allowed: set[tuple[str, str]]) -> None:
        for hit in hits:
            if (hit.build_id, hit.psi_node_id) not in allowed:
                raise PsiProjectionInconsistentError(
                    hit.build_id,
                    "Psi projection returned a node outside the build-scoped allowlist",
                )

    @staticmethod
    def _empty_result(
        request: GroundedAuxiliaryQuery,
        stop_reason: str,
        *,
        state: str = "failed",
        trees: list[PsiTree] | None = None,
    ) -> PsiTraversalResult:
        return PsiTraversalResult(
            selected_nodes=[],
            source_chunk_ids=[],
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state=state,  # type: ignore[arg-type]
                stop_reason=stop_reason,
                fallback_source="none",
                failure_code=None if state == "skipped" else stop_reason,
                trees_considered=len(trees or []),
            ),
        )
