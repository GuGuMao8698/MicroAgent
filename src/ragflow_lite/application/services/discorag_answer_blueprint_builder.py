from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    ChunkDiscourseStructure,
    DiscourseUnit,
    EvidenceItem,
    InterChunkDiscourseGraph,
    IntraChunkDiscoursePackage,
)

# ---------------------------------------------------------------------------
# Relation-semantics mapping for the 20 materialized inter-chunk labels.
# Source: paper relation set minus "unrelated" (see
# infrastructure/evidence/llm_inter_chunk_graph_parser.py).
# ---------------------------------------------------------------------------

# Conflict / update / caution — these signal tension or replacement.
_CONFLICT_RELATION_TYPES: frozenset[str] = frozenset(
    {"contradicts", "contrasts_with", "replaces"}
)

# Support — these directly back up a claim.
_SUPPORT_RELATION_TYPES: frozenset[str] = frozenset({"supports", "justifies"})

# Background — contextual framing.
_BACKGROUND_RELATION_TYPES: frozenset[str] = frozenset({"background_for"})

# Elaboration / supplement — detail-oriented enrichment.
_ELABORATION_RELATION_TYPES: frozenset[str] = frozenset(
    {"elaborates", "supplements", "specifies", "exemplifies"}
)

# Qualification constraint triggers — labels that indicate a caveat or
# restriction on the target, useful for constraint generation but broader
# than the promotion triggers.
_QUALIFICATION_CONSTRAINT_TYPES: frozenset[str] = frozenset(
    {"specifies", "replaces", "contrasts_with"}
)

# Promotion triggers — only these relation types promote a supplemental
# discourse chunk into the final ordered evidence list.  ``qualifies`` is
# NOT in the paper relation set; the paper-faithful labels that carry
# equivalent semantics are listed here.
_PROMOTION_RELATION_TYPES: frozenset[str] = frozenset(
    {"contradicts", "contrasts_with", "replaces"}
)

# Labels that should NOT trigger promotion — everything else in the 20
# materialized set that is not in _PROMOTION_RELATION_TYPES.
_NO_PROMOTION_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "supports",
        "elaborates",
        "exemplifies",
        "causes",
        "results_from",
        "enables",
        "prevents",
        "precedes",
        "follows",
        "simultaneous",
        "background_for",
        "generalizes",
        "compares_with",
        "supplements",
        "specifies",
        "motivates",
        "justifies",
    }
)

# ---------------------------------------------------------------------------
# RST planning roles and relation labels (from Task 6).
# ---------------------------------------------------------------------------

# Planning roles that signal caveat/qualification constraints.
_RST_QUALIFICATION_ROLES: frozenset[str] = frozenset({"qualification", "condition"})

# Planning roles and RST relations that signal caution/comparison.
_RST_CONTRAST_ROLES: frozenset[str] = frozenset({"contrast"})
_RST_CONTRAST_RELATIONS: frozenset[str] = frozenset({"contrasts"})

# Planning roles indicating a claim suitable for lead/main selection.
_RST_CLAIM_ROLE: str = "claim"
_RST_NUCLEUS: str = "nucleus"


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
        # RST-aware lead selection: when multiple chunks are equally eligible
        # for the main role and no graph-derived ordering exists, prefer chunks
        # whose discourse structure has a nucleus claim unit.  Do not override
        # explicit graph-derived ordering.
        main_chunk_ids = [cid for cid, role in chunk_roles.items() if role == "main"]
        if len(main_chunk_ids) > 1 and not self._has_relation_type(
            graph, _CONFLICT_RELATION_TYPES | _PROMOTION_RELATION_TYPES
        ):
            rst_lead = self._rst_preferred_lead(main_chunk_ids, structure_by_chunk_id)
            if rst_lead is not None and rst_lead != ordered_chunk_ids[0]:
                idx = ordered_chunk_ids.index(rst_lead)
                ordered_chunk_ids.insert(0, ordered_chunk_ids.pop(idx))
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

    def _rst_preferred_lead(
        self,
        main_chunk_ids: list[str],
        structure_by_chunk_id: dict[str, ChunkDiscourseStructure],
    ) -> str | None:
        """Among *main_chunk_ids*, return the one whose structure contains a
        nucleus unit with planning_role == "claim", or ``None`` if no such
        chunk exists.  When multiple match, prefer the first in the input
        order (i.e. original retrieval ranking).
        """
        for chunk_id in main_chunk_ids:
            structure = structure_by_chunk_id.get(chunk_id)
            if structure is None:
                continue
            for unit in structure.units:
                if (
                    unit.nuclearity == _RST_NUCLEUS
                    and unit.planning_role == _RST_CLAIM_ROLE
                ):
                    return chunk_id
        return None

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
        has_intra_contrast = self._has_contrast_like_relation(structures)
        if has_intra_contrast:
            constraints.append(
                "Mention contrast or conflict cautiously when discourse relations support it."
            )
        # --- inter-chunk graph constraints (20 materialized labels) ---
        has_graph_conflict = self._has_relation_type(graph, _CONFLICT_RELATION_TYPES)
        if has_graph_conflict:
            constraints.append(
                "Explicitly handle inter-chunk contradiction, contrast, or replacement before giving a final conclusion."
            )
        has_graph_qualification = self._has_relation_type(
            graph, _QUALIFICATION_CONSTRAINT_TYPES
        )
        if has_graph_qualification:
            constraints.append(
                "Respect inter-chunk qualification (specification, replacement, or contrast) before stating final conclusions."
            )
        if self._has_relation_type(
            graph,
            _SUPPORT_RELATION_TYPES
            | _BACKGROUND_RELATION_TYPES
            | _ELABORATION_RELATION_TYPES,
        ):
            constraints.append(
                "Use supporting, background, elaborating, supplementing, specifying, or exemplifying relations only when grounded in provided contexts."
            )
        # --- RST-derived constraints (Task 7) ---
        # Collect all units across structures for RST signal analysis.
        all_units: list[DiscourseUnit] = [
            unit for structure in structures for unit in structure.units
        ]
        has_rst_qualification = self._has_rst_qualification(all_units)
        has_rst_contrast = self._has_rst_contrast(all_units, structures)
        # Deduplicate: only add RST constraints when no equivalent graph/intra
        # constraint already covers the same semantic slot.
        if has_rst_qualification and not has_graph_qualification:
            constraints.append(
                "Respect qualifications and conditions from discourse structure before stating final conclusions."
            )
        if has_rst_contrast and not has_intra_contrast and not has_graph_conflict:
            constraints.append(
                "Note contrasting perspectives or comparisons from discourse structure when relevant."
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

    def _has_rst_qualification(
        self,
        units: list[DiscourseUnit],
    ) -> bool:
        """Check if any unit has a qualification/condition planning_role."""
        return any(unit.planning_role in _RST_QUALIFICATION_ROLES for unit in units)

    def _has_rst_contrast(
        self,
        units: list[DiscourseUnit],
        structures: list[ChunkDiscourseStructure],
    ) -> bool:
        """Check if any unit has a contrast planning_role or any intra-chunk
        relation has an RST contrasts relation."""
        if any(unit.planning_role in _RST_CONTRAST_ROLES for unit in units):
            return True
        return any(
            " ".join(relation.relation_type.split()).lower() in _RST_CONTRAST_RELATIONS
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
        relation_types: set[str] | frozenset[str],
    ) -> bool:
        if graph is None:
            return False
        return any(
            relation.relation_type in relation_types for relation in graph.relations
        )

    def _promoted_chunk_ids(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None,
    ) -> list[str]:
        """Identify supplemental chunks promoted via conflict/qualification relations.

        Promotion triggers use paper-faithful labels: ``contradicts``,
        ``contrasts_with``, ``replaces``.  The old ``qualifies`` label is not
        in the paper set and is no longer a trigger.
        """
        if graph is None:
            return []
        item_by_id = {
            item.canonical_chunk_id: item for item in package.evidence_package.items
        }
        promoted: list[str] = []
        for relation in graph.relations:
            if relation.relation_type not in _PROMOTION_RELATION_TYPES:
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
