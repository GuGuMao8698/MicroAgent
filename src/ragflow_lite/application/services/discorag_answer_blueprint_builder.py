from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    ChunkDiscourseStructure,
    EvidenceItem,
    InterChunkDiscourseGraph,
    IntraChunkDiscoursePackage,
)


class DiscoRAGAnswerBlueprintBuilder:
    """Builds a deterministic DiscoRAG answer blueprint from structured evidence."""

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
        items = package.evidence_package.items
        # 从 evidence_package.metadata 中提取 source_selection 摘要
        source_selection = package.evidence_package.metadata.get("source_selection")
        if not isinstance(source_selection, dict):
            source_selection = {}
        selected_answer_chunk_ids = source_selection.get(
            "selected_answer_chunk_ids", []
        )
        if not isinstance(selected_answer_chunk_ids, list):
            selected_answer_chunk_ids = []
        selected_discourse_chunk_ids = source_selection.get(
            "selected_discourse_chunk_ids", []
        )
        if not isinstance(selected_discourse_chunk_ids, list):
            selected_discourse_chunk_ids = []
        fallback_reason = source_selection.get("fallback_reason")
        if fallback_reason is not None and not isinstance(fallback_reason, str):
            fallback_reason = None

        if not items:
            return AnswerBlueprint(
                ordered_chunk_ids=[],
                chunk_roles={},
                answer_constraints=[],
                plan_steps=[],
                metadata={
                    "planner": "discorag_answer_blueprint_builder",
                    "status": "empty",
                    "evidence_count": 0,
                    "structure_count": len(package.structures),
                    "role_counts": {},
                    "topology_path_ids": [],
                    "topology_relation_ids": [],
                    "selected_answer_chunk_ids": [],
                    "selected_discourse_chunk_ids": [],
                    "source_selection_status": "empty",
                    "source_selection_fallback_reason": None,
                    "inter_chunk_relation_count": len(graph.relations)
                    if graph is not None
                    else 0,
                    "inter_chunk_relation_types": self._graph_relation_types(graph),
                    "promoted_chunk_ids": [],
                },
            )

        item_by_chunk_id = self._items_by_chunk_id(items)
        structure_by_chunk_id = self._structures_by_chunk_id(
            package.structures,
            item_by_chunk_id,
        )

        ordered_chunk_ids = [item.canonical_chunk_id for item in items]
        chunk_roles = {
            item.canonical_chunk_id: self._role_for_item(item, structure_by_chunk_id)
            for item in items
        }
        role_counts = dict(Counter(chunk_roles.values()))
        topology_path_ids = self._unique_ids(
            path_id for item in items for path_id in item.topology_path_ids
        )
        topology_relation_ids = self._unique_ids(
            relation_id for item in items for relation_id in item.topology_relation_ids
        )
        promoted_chunk_ids = self._promoted_chunk_ids(package, graph)
        for chunk_id in promoted_chunk_ids:
            if chunk_id not in ordered_chunk_ids:
                ordered_chunk_ids.append(chunk_id)

        return AnswerBlueprint(
            ordered_chunk_ids=ordered_chunk_ids,
            chunk_roles=chunk_roles,
            answer_constraints=self._constraints(
                chunk_roles, package.structures, graph
            ),
            plan_steps=self._plan_steps(package, chunk_roles, graph),
            metadata={
                "planner": "discorag_answer_blueprint_builder",
                "status": "ok",
                "evidence_count": len(items),
                "structure_count": len(package.structures),
                "role_counts": role_counts,
                "topology_path_ids": topology_path_ids,
                "topology_relation_ids": topology_relation_ids,
                "selected_answer_chunk_ids": list(selected_answer_chunk_ids),
                "selected_discourse_chunk_ids": list(selected_discourse_chunk_ids),
                "source_selection_status": package.metadata.get(
                    "selection_source", "unknown"
                ),
                "source_selection_fallback_reason": fallback_reason,
                "inter_chunk_relation_count": len(graph.relations)
                if graph is not None
                else 0,
                "inter_chunk_relation_types": self._graph_relation_types(graph),
                "promoted_chunk_ids": promoted_chunk_ids,
            },
        )

    def _items_by_chunk_id(self, items: list[EvidenceItem]) -> dict[str, EvidenceItem]:
        item_by_chunk_id: dict[str, EvidenceItem] = {}
        for item in items:
            if item.canonical_chunk_id in item_by_chunk_id:
                raise ProcessingError(
                    f"Duplicate evidence chunk id: {item.canonical_chunk_id}"
                )
            item_by_chunk_id[item.canonical_chunk_id] = item
        return item_by_chunk_id

    def _structures_by_chunk_id(
        self,
        structures: list[ChunkDiscourseStructure],
        item_by_chunk_id: dict[str, EvidenceItem],
    ) -> dict[str, ChunkDiscourseStructure]:
        structure_by_chunk_id: dict[str, ChunkDiscourseStructure] = {}
        for structure in structures:
            if structure.canonical_chunk_id not in item_by_chunk_id:
                raise ProcessingError(
                    f"Unknown discourse structure chunk id: {structure.canonical_chunk_id}"
                )
            if structure.canonical_chunk_id in structure_by_chunk_id:
                raise ProcessingError(
                    "Duplicate discourse structure chunk id: "
                    f"{structure.canonical_chunk_id}"
                )
            self._validate_structure_role_ids(structure)
            structure_by_chunk_id[structure.canonical_chunk_id] = structure
        return structure_by_chunk_id

    def _validate_structure_role_ids(self, structure: ChunkDiscourseStructure) -> None:
        unit_ids = {unit.unit_id for unit in structure.units}
        role_ids = set(structure.main_unit_ids) | set(structure.supporting_unit_ids)
        missing = role_ids - unit_ids
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ProcessingError(
                f"Discourse structure {structure.canonical_chunk_id} references "
                f"unknown unit ids: {missing_text}"
            )

    def _role_for_item(
        self,
        item: EvidenceItem,
        structure_by_chunk_id: dict[str, ChunkDiscourseStructure],
    ) -> str:
        structure = structure_by_chunk_id.get(item.canonical_chunk_id)
        if structure is not None:
            if structure.main_unit_ids:
                return "main"
            if structure.supporting_unit_ids:
                return "support"
        if item.topology_path_ids or item.topology_relation_ids:
            return "context"
        return "detail"

    def _constraints(
        self,
        chunk_roles: dict[str, str],
        structures: list[ChunkDiscourseStructure],
        graph: InterChunkDiscourseGraph | None = None,
    ) -> list[str]:
        constraints = [
            "Follow ordered_chunk_ids when presenting evidence.",
            "Preserve citation grounding and provenance for each claim.",
        ]
        if {"support", "context"} & set(chunk_roles.values()):
            constraints.append(
                "Use support and context chunks as supporting evidence, not standalone conclusions."
            )
        if self._has_contrast_like_relation(structures):
            constraints.append(
                "Mention contrast or conflict cautiously when discourse relations support it."
            )
        if self._has_relation_type(graph, {"contradicts"}):
            constraints.append(
                "Explicitly handle inter-chunk contradiction or conflict before giving a final conclusion."
            )
        elif self._has_relation_type(graph, {"qualifies"}):
            constraints.append(
                "Respect inter-chunk qualification before stating final conclusions."
            )
        if self._has_relation_type(
            graph,
            {"supports", "background_for", "elaborates", "example_of"},
        ):
            constraints.append(
                "Use supporting, background, elaborating, or example relations only when grounded in provided contexts."
            )
        return constraints

    def _has_contrast_like_relation(
        self,
        structures: list[ChunkDiscourseStructure],
    ) -> bool:
        contrast_like = {
            "contrast",
            "contrasts",
            "conflict",
            "conflicts",
            "contradiction",
            "contradicts",
        }
        return any(
            " ".join(relation.relation_type.split()).lower() in contrast_like
            for structure in structures
            for relation in structure.relations
        )

    def _plan_steps(
        self,
        package: IntraChunkDiscoursePackage,
        chunk_roles: dict[str, str],
        graph: InterChunkDiscourseGraph | None = None,
    ) -> list[str]:
        keywords = package.evidence_package.grounded_query.answer_type_keywords
        keyword_text = ", ".join(keywords) if keywords else "the user's answer type"
        if "main" in chunk_roles.values():
            first_step = "Start from chunks marked main."
        else:
            first_step = "Start from the first ordered chunk."
        steps = [
            first_step,
            "Use support and context chunks to qualify or elaborate the main claim.",
            f"Preserve answer-type keywords: {keyword_text}.",
            "Do not add claims that are not grounded in the provided contexts.",
        ]
        if graph is not None and graph.relations:
            steps.append(
                "Use supplemental discourse chunks to qualify, support, or constrain answer chunks when graph relations require it."
            )
        return steps

    def _graph_relation_types(
        self,
        graph: InterChunkDiscourseGraph | None,
    ) -> list[str]:
        if graph is None:
            return []
        return self._unique_ids(relation.relation_type for relation in graph.relations)

    def _has_relation_type(
        self,
        graph: InterChunkDiscourseGraph | None,
        relation_types: set[str],
    ) -> bool:
        if graph is None:
            return False
        return any(
            relation.relation_type in relation_types for relation in graph.relations
        )

    def _has_qualification_relation(
        self,
        graph: InterChunkDiscourseGraph | None,
    ) -> bool:
        if graph is None:
            return False
        return any(
            relation.relation_type in {"qualifies", "contradicts"}
            for relation in graph.relations
        )

    def _promoted_chunk_ids(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None,
    ) -> list[str]:
        """识别因 contradicts/qualifies 关系需要提升到最终证据的 supplemental chunk。"""
        if graph is None:
            return []
        item_by_id = {
            item.canonical_chunk_id: item for item in package.evidence_package.items
        }
        promoted: list[str] = []
        for relation in graph.relations:
            if relation.relation_type not in {"contradicts", "qualifies"}:
                continue
            source = item_by_id.get(relation.source_chunk_id)
            if source is None:
                continue
            if source.metadata.get("supplemental_discourse") is not True:
                continue
            if relation.source_chunk_id not in promoted:
                promoted.append(relation.source_chunk_id)
        return promoted

    def _unique_ids(self, values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return unique
