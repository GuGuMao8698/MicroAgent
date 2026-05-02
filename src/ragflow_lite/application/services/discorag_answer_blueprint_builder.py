from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    ChunkDiscourseStructure,
    EvidenceItem,
    IntraChunkDiscoursePackage,
)


class DiscoRAGAnswerBlueprintBuilder:
    """Builds a deterministic DiscoRAG answer blueprint from structured evidence."""

    def build(self, package: IntraChunkDiscoursePackage) -> AnswerBlueprint:
        items = package.evidence_package.items
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

        return AnswerBlueprint(
            ordered_chunk_ids=ordered_chunk_ids,
            chunk_roles=chunk_roles,
            answer_constraints=self._constraints(chunk_roles, package.structures),
            plan_steps=self._plan_steps(package, chunk_roles),
            metadata={
                "planner": "discorag_answer_blueprint_builder",
                "status": "ok",
                "evidence_count": len(items),
                "structure_count": len(package.structures),
                "role_counts": role_counts,
                "topology_path_ids": topology_path_ids,
                "topology_relation_ids": topology_relation_ids,
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
    ) -> list[str]:
        keywords = package.evidence_package.grounded_query.answer_type_keywords
        keyword_text = ", ".join(keywords) if keywords else "the user's answer type"
        if "main" in chunk_roles.values():
            first_step = "Start from chunks marked main."
        else:
            first_step = "Start from the first ordered chunk."
        return [
            first_step,
            "Use support and context chunks to qualify or elaborate the main claim.",
            f"Preserve answer-type keywords: {keyword_text}.",
            "Do not add claims that are not grounded in the provided contexts.",
        ]

    def _unique_ids(self, values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return unique
