from __future__ import annotations

import pytest

from ragflow_lite.application.services.discorag_answer_blueprint_builder import (
    DiscoRAGAnswerBlueprintBuilder,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ChunkDiscourseStructure,
    DiscourseUnit,
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GroundedQuery,
    InterChunkDiscourseGraph,
    InterChunkDiscourseRelation,
    IntraChunkDiscoursePackage,
    IntraChunkDiscourseRelation,
)


def _grounded_query() -> GroundedQuery:
    return GroundedQuery(
        query="How does MiniRAG organize evidence?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
        metadata={"source": "unit"},
    )


def _evidence_item(
    chunk_id: str,
    *,
    order: int,
    text: str = "MiniRAG retrieves evidence.",
    topology_path_ids: list[str] | None = None,
    topology_relation_ids: list[str] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        canonical_chunk_id=chunk_id,
        text=text,
        score=1.0 - (order * 0.1),
        order=order,
        provenance=EvidenceProvenance(
            document_id="doc_alpha",
            filename="alpha.md",
            file_type="markdown",
            chunk_index=order,
        ),
        retained_reasons=["vector", "topology_path"],
        grounded_entities=["MiniRAG"],
        answer_type_keywords=["mechanism"],
        topology_path_ids=topology_path_ids or [],
        topology_relation_ids=topology_relation_ids or [],
        metadata={"rank": order},
    )


def _package(
    *,
    items: list[EvidenceItem] | None = None,
    structures: list[ChunkDiscourseStructure] | None = None,
) -> IntraChunkDiscoursePackage:
    evidence_package = EvidencePackage(
        query="How does MiniRAG organize evidence?",
        grounded_query=_grounded_query(),
        items=items
        if items is not None
        else [
            _evidence_item("chunk_a", order=0, topology_path_ids=["path_a"]),
            _evidence_item("chunk_b", order=1, topology_relation_ids=["rel_b"]),
            _evidence_item("chunk_c", order=2),
        ],
        metadata={"source": "test"},
    )
    return IntraChunkDiscoursePackage(
        query=evidence_package.query,
        evidence_package=evidence_package,
        structures=structures or [],
        metadata={"status": "ok"},
    )


def _unit(
    unit_id: str,
    chunk_id: str,
    role: str,
    *,
    nuclearity: str | None = None,
    rst_relation: str | None = None,
    planning_role: str | None = None,
) -> DiscourseUnit:
    return DiscourseUnit(
        unit_id=unit_id,
        canonical_chunk_id=chunk_id,
        text=f"{role} text",
        order=0,
        role=role,
        nuclearity=nuclearity,
        rst_relation=rst_relation,
        planning_role=planning_role,
    )


def _structure(
    chunk_id: str,
    *,
    main: bool = False,
    support: bool = False,
) -> ChunkDiscourseStructure:
    units = [_unit(f"{chunk_id}_unit_0", chunk_id, "main" if main else "support")]
    return ChunkDiscourseStructure(
        canonical_chunk_id=chunk_id,
        document_id="doc_alpha",
        units=units,
        main_unit_ids=[units[0].unit_id] if main else [],
        supporting_unit_ids=[units[0].unit_id] if support else [],
    )


def _relation(chunk_id: str, relation_type: str) -> IntraChunkDiscourseRelation:
    return IntraChunkDiscourseRelation(
        relation_id=f"{chunk_id}_rel_0",
        canonical_chunk_id=chunk_id,
        source_unit_id=f"{chunk_id}_unit_0",
        target_unit_id=f"{chunk_id}_unit_1",
        relation_type=relation_type,
        weight=1.0,
    )


def test_build_preserves_evidence_order_and_assigns_roles() -> None:
    package = _package(
        structures=[
            _structure("chunk_a", main=True),
            _structure("chunk_b", support=True),
        ]
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b", "chunk_c"]
    assert blueprint.chunk_roles == {
        "chunk_a": "main",
        "chunk_b": "support",
        "chunk_c": "detail",
    }
    assert blueprint.metadata["status"] == "ok"
    assert blueprint.metadata["evidence_count"] == 3
    assert blueprint.metadata["structure_count"] == 2
    assert blueprint.metadata["role_counts"] == {
        "main": 1,
        "support": 1,
        "detail": 1,
    }


def test_build_uses_topology_role_when_discourse_structure_is_absent() -> None:
    package = _package(
        items=[
            _evidence_item(
                "chunk_topology",
                order=0,
                topology_path_ids=["path_1"],
                topology_relation_ids=["rel_1"],
            )
        ]
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    assert blueprint.ordered_chunk_ids == ["chunk_topology"]
    assert blueprint.chunk_roles == {"chunk_topology": "context"}
    assert blueprint.metadata["topology_path_ids"] == ["path_1"]
    assert blueprint.metadata["topology_relation_ids"] == ["rel_1"]


def test_build_generates_constraints_and_plan_steps() -> None:
    package = _package(structures=[_structure("chunk_a", main=True)])

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    constraints = " ".join(blueprint.answer_constraints)
    steps = " ".join(blueprint.plan_steps)
    assert "ordered_chunk_ids" in constraints
    assert "citation" in constraints
    assert "support" in constraints
    assert "main" in steps
    assert "mechanism" in steps
    assert "grounded" in steps


def test_build_adds_constraint_for_contrast_like_relations() -> None:
    units = [
        _unit("chunk_a_unit_0", "chunk_a", "main"),
        _unit("chunk_a_unit_1", "chunk_a", "support"),
    ]
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_alpha",
        units=units,
        relations=[_relation("chunk_a", "Conflict")],
        main_unit_ids=[units[0].unit_id],
        supporting_unit_ids=[units[1].unit_id],
    )
    package = _package(structures=[structure])

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "contrast" in constraints
    assert "conflict" in constraints


def test_build_does_not_add_contrast_constraint_for_non_contrast_relations() -> None:
    units = [
        _unit("chunk_a_unit_0", "chunk_a", "main"),
        _unit("chunk_a_unit_1", "chunk_a", "support"),
    ]
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_alpha",
        units=units,
        relations=[_relation("chunk_a", "supports")],
        main_unit_ids=[units[0].unit_id],
        supporting_unit_ids=[units[1].unit_id],
    )
    package = _package(structures=[structure])

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "contrast" not in constraints
    assert "conflict" not in constraints


def test_build_empty_package_returns_empty_blueprint() -> None:
    package = _package(items=[])

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    assert blueprint.ordered_chunk_ids == []
    assert blueprint.chunk_roles == {}
    assert blueprint.answer_constraints == []
    assert blueprint.plan_steps == []
    assert blueprint.metadata["status"] == "empty"
    assert blueprint.metadata["evidence_count"] == 0


def test_build_rejects_duplicate_evidence_chunk_ids() -> None:
    package = _package(
        items=[
            _evidence_item("chunk_dup", order=0),
            _evidence_item("chunk_dup", order=1),
        ]
    )

    with pytest.raises(ProcessingError, match="Duplicate evidence chunk id"):
        DiscoRAGAnswerBlueprintBuilder().build(package)


def test_build_rejects_duplicate_discourse_structure_chunk_ids() -> None:
    package = _package(
        structures=[
            _structure("chunk_a", main=True),
            _structure("chunk_a", support=True),
        ]
    )

    with pytest.raises(
        ProcessingError,
        match="Duplicate discourse structure chunk id",
    ):
        DiscoRAGAnswerBlueprintBuilder().build(package)


def test_build_rejects_unknown_discourse_structure_chunk_id() -> None:
    package = _package(structures=[_structure("chunk_unknown", main=True)])

    with pytest.raises(ProcessingError, match="Unknown discourse structure chunk id"):
        DiscoRAGAnswerBlueprintBuilder().build(package)


def test_build_rejects_structure_role_ids_not_present_in_units() -> None:
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_alpha",
        units=[],
        main_unit_ids=["missing_unit"],
    )
    package = _package(structures=[structure])

    with pytest.raises(ProcessingError, match="unknown unit ids"):
        DiscoRAGAnswerBlueprintBuilder().build(package)


def test_build_records_source_selection_metadata() -> None:
    evidence_package = EvidencePackage(
        query="How does MiniRAG organize evidence?",
        grounded_query=_grounded_query(),
        items=[
            _evidence_item(
                "chunk_a",
                order=0,
                topology_path_ids=["path_a"],
            ),
            _evidence_item("chunk_b", order=1),
        ],
        metadata={
            "source_selection": {
                "selected_answer_chunk_ids": ["chunk_a", "chunk_b"],
                "selected_discourse_chunk_ids": ["chunk_a"],
                "fallback_reason": None,
            }
        },
    )
    package = IntraChunkDiscoursePackage(
        query=evidence_package.query,
        evidence_package=evidence_package,
        structures=[],
        metadata={"selection_source": "source_selection"},
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

    assert blueprint.metadata["selected_answer_chunk_ids"] == ["chunk_a", "chunk_b"]
    assert blueprint.metadata["selected_discourse_chunk_ids"] == ["chunk_a"]
    assert blueprint.metadata["source_selection_status"] == "source_selection"
    assert blueprint.metadata["source_selection_fallback_reason"] is None


@pytest.mark.parametrize(
    "relation_type",
    ["specifies", "replaces", "contrasts_with"],
)
def test_build_adds_graph_aware_constraints_for_qualification(
    relation_type: str,
) -> None:
    """Qualification constraint fires for paper-faithful labels, not old qualifies."""
    package = _package(
        items=[
            _evidence_item(
                "chunk_answer",
                order=0,
                topology_relation_ids=["rel_shared"],
            ),
            _evidence_item(
                "chunk_supplemental",
                order=1,
                topology_relation_ids=["rel_shared"],
            ),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supplemental"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supplemental",
                target_chunk_id="chunk_answer",
                relation_type=relation_type,
                rationale="supplemental limits answer",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    steps = " ".join(blueprint.plan_steps).lower()
    assert "qualification" in constraints
    assert "supplemental" in steps
    assert blueprint.metadata["inter_chunk_relation_count"] == 1
    assert blueprint.metadata["inter_chunk_relation_types"] == [relation_type]


def test_build_marks_supplemental_chunk_for_promotion_when_it_contradicts_answer() -> (
    None
):
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supplemental", order=1),
        ]
    )
    package.evidence_package.items[0].metadata["selected_for_answer"] = True
    package.evidence_package.items[1].metadata["selected_for_answer"] = False
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supplemental"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supplemental",
                target_chunk_id="chunk_answer",
                relation_type="contradicts",
                rationale="supplemental changes the conclusion",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.metadata["promoted_chunk_ids"] == ["chunk_supplemental"]
    assert "chunk_supplemental" in blueprint.ordered_chunk_ids
    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "contradiction" in constraints


def test_build_with_empty_inter_chunk_graph_preserves_existing_order() -> None:
    package = _package()
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b", "chunk_c"],
        relations=[],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b", "chunk_c"]
    assert blueprint.metadata["inter_chunk_relation_count"] == 0


def test_blueprint_supports_relation_does_not_promote_supplemental_chunk() -> None:
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supplemental", order=1),
        ]
    )
    package.evidence_package.items[0].metadata["selected_for_answer"] = True
    package.evidence_package.items[1].metadata["selected_for_answer"] = False
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supplemental"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supplemental",
                target_chunk_id="chunk_answer",
                relation_type="supports",
                rationale="Supplemental reinforces answer.",
                confidence=0.7,
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.metadata["promoted_chunk_ids"] == []
    assert "supports" in blueprint.metadata["inter_chunk_relation_types"]


def test_blueprint_adds_both_contradiction_and_qualification_constraints() -> None:
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_qualifier", order=1),
            _evidence_item("chunk_contradiction", order=2),
        ]
    )
    package.evidence_package.items[0].metadata["selected_for_answer"] = True
    package.evidence_package.items[1].metadata["selected_for_answer"] = False
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    package.evidence_package.items[2].metadata["selected_for_answer"] = False
    package.evidence_package.items[2].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_qualifier", "chunk_contradiction"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_qualifier",
                target_chunk_id="chunk_answer",
                relation_type="specifies",
                rationale="Qualifier narrows the answer.",
                confidence=0.7,
            ),
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_contradiction",
                target_chunk_id="chunk_answer",
                relation_type="contradicts",
                rationale="Contradiction changes the conclusion.",
                confidence=0.8,
            ),
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "contradiction" in constraints or "conflict" in constraints
    assert "qualification" in constraints
    # specifies triggers promotion (it's in _PROMOTION_RELATION_TYPES? No —
    # specifies is in _QUALIFICATION_CONSTRAINT_TYPES but NOT in
    # _PROMOTION_RELATION_TYPES.  Only contradicts promotes here.
    assert blueprint.metadata["promoted_chunk_ids"] == [
        "chunk_contradiction",
    ]


def test_blueprint_adds_caution_for_contradiction_relation() -> None:
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supplemental", order=1),
        ]
    )
    package.evidence_package.items[0].metadata["selected_for_answer"] = True
    package.evidence_package.items[1].metadata["selected_for_answer"] = False
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supplemental"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supplemental",
                target_chunk_id="chunk_answer",
                relation_type="contradicts",
                rationale="Supplemental changes the conclusion.",
                confidence=0.8,
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert "chunk_supplemental" in blueprint.metadata["promoted_chunk_ids"]
    assert any(
        "contradiction" in constraint.lower() or "conflict" in constraint.lower()
        for constraint in blueprint.answer_constraints
    )


# ---------------------------------------------------------------------------
# New tests for expanded 20-label relation coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relation_type",
    ["contradicts", "contrasts_with", "replaces"],
)
def test_conflict_relation_triggers_conflict_constraint(relation_type: str) -> None:
    """All three conflict labels generate a conflict constraint."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type=relation_type,
                rationale="conflict detected",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "contradiction" in constraints or "conflict" in constraints


@pytest.mark.parametrize(
    "relation_type",
    ["contradicts", "contrasts_with", "replaces"],
)
def test_conflict_relation_promotes_supplemental_chunk(relation_type: str) -> None:
    """All three promotion triggers promote supplemental chunks."""
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supp", order=1),
        ]
    )
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supp"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supp",
                target_chunk_id="chunk_answer",
                relation_type=relation_type,
                rationale="tension",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.metadata["promoted_chunk_ids"] == ["chunk_supp"]
    assert "chunk_supp" in blueprint.ordered_chunk_ids


@pytest.mark.parametrize(
    "relation_type",
    [
        "supports",
        "justifies",
        "elaborates",
        "supplements",
        "specifies",
        "exemplifies",
        "background_for",
        "causes",
        "results_from",
        "enables",
        "prevents",
        "precedes",
        "follows",
        "simultaneous",
        "generalizes",
        "compares_with",
        "motivates",
    ],
)
def test_non_promotion_relation_does_not_promote_supplemental(
    relation_type: str,
) -> None:
    """Non-promotion labels must not promote supplemental chunks."""
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supp", order=1),
        ]
    )
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supp"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supp",
                target_chunk_id="chunk_answer",
                relation_type=relation_type,
                rationale="non-promotion relation",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.metadata["promoted_chunk_ids"] == []


@pytest.mark.parametrize(
    "relation_type",
    ["supports", "justifies"],
)
def test_support_relation_triggers_support_constraint(relation_type: str) -> None:
    """Support labels generate the grounded-use constraint."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type=relation_type,
                rationale="support",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "grounded" in constraints


def test_background_relation_triggers_support_constraint() -> None:
    """background_for generates the grounded-use constraint."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type="background_for",
                rationale="background context",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "grounded" in constraints


@pytest.mark.parametrize(
    "relation_type",
    ["elaborates", "supplements", "specifies", "exemplifies"],
)
def test_elaboration_relation_triggers_support_constraint(relation_type: str) -> None:
    """Elaboration/supplement labels generate the grounded-use constraint."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type=relation_type,
                rationale="elaboration",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "grounded" in constraints


def test_qualifies_no_longer_triggers_promotion() -> None:
    """The old qualifies label must not promote or generate qualification constraint."""
    package = _package(
        items=[
            _evidence_item("chunk_answer", order=0),
            _evidence_item("chunk_supp", order=1),
        ]
    )
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_answer", "chunk_supp"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_supp",
                target_chunk_id="chunk_answer",
                relation_type="qualifies",
                rationale="old label",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    assert blueprint.metadata["promoted_chunk_ids"] == []
    constraints = " ".join(blueprint.answer_constraints).lower()
    assert "qualification" not in constraints


def test_promotion_is_replacement_not_append() -> None:
    """Promoted chunks replace, not append, within the ordered list bounds."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    # chunk_b is supplemental and contradicts chunk_a — it gets promoted
    package.evidence_package.items[1].metadata["supplemental_discourse"] = True
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type="contradicts",
                rationale="conflict",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    # chunk_b is already in ordered_chunk_ids so it should not appear twice
    assert blueprint.ordered_chunk_ids.count("chunk_b") == 1


def test_deduplicated_constraints_for_overlapping_labels() -> None:
    """When contrasts_with fires both conflict and qualification constraints,
    the constraint list should not contain duplicate wording."""
    package = _package(
        items=[
            _evidence_item("chunk_a", order=0),
            _evidence_item("chunk_b", order=1),
        ]
    )
    graph = InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=["chunk_a", "chunk_b"],
        relations=[
            InterChunkDiscourseRelation(
                source_chunk_id="chunk_b",
                target_chunk_id="chunk_a",
                relation_type="contrasts_with",
                rationale="contrast with qualification",
            )
        ],
    )

    blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

    constraints = blueprint.answer_constraints
    # Should have both conflict and qualification constraints, but each only once
    conflict_count = sum(
        1
        for c in constraints
        if "contradiction" in c.lower() or "conflict" in c.lower()
    )
    qual_count = sum(1 for c in constraints if "qualification" in c.lower())
    assert conflict_count == 1
    assert qual_count == 1


# ---------------------------------------------------------------------------
# Task 7: RST-derived constraints, deduplication, and lead selection
# ---------------------------------------------------------------------------


def _rst_structure(
    chunk_id: str,
    *,
    main: bool = False,
    support: bool = False,
    units: list[DiscourseUnit] | None = None,
    relations: list[IntraChunkDiscourseRelation] | None = None,
) -> ChunkDiscourseStructure:
    """Build a ChunkDiscourseStructure with explicit units for RST testing."""
    if units is None:
        units = [_unit(f"{chunk_id}_unit_0", chunk_id, "main" if main else "support")]
    return ChunkDiscourseStructure(
        canonical_chunk_id=chunk_id,
        document_id="doc_alpha",
        units=units,
        relations=relations or [],
        main_unit_ids=[units[0].unit_id] if main else [],
        supporting_unit_ids=[units[0].unit_id] if support else [],
    )


class TestRSTQualificationConstraint:
    """planning_role == qualification or condition triggers caveat constraint."""

    @pytest.mark.parametrize("role", ["qualification", "condition"])
    def test_rst_qualification_role_adds_caveat_constraint(self, role: str) -> None:
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role=role),
        ]
        structure = _rst_structure("chunk_a", main=True, units=units)
        package = _package(structures=[structure])

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        constraints = " ".join(blueprint.answer_constraints).lower()
        assert "qualifications" in constraints or "conditions" in constraints

    def test_no_rst_qualification_when_no_qualifying_units(self) -> None:
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role="claim"),
        ]
        structure = _rst_structure("chunk_a", main=True, units=units)
        package = _package(structures=[structure])

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        constraints = blueprint.answer_constraints
        # Should NOT contain the RST qualification constraint
        rst_constraint_present = any(
            "qualifications and conditions" in c.lower() for c in constraints
        )
        assert not rst_constraint_present


class TestRSTContrastConstraint:
    """planning_role == contrast or rst_relation == contrasts triggers
    caution/comparison constraint."""

    def test_rst_contrast_planning_role_adds_constraint(self) -> None:
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role="contrast"),
        ]
        structure = _rst_structure("chunk_a", main=True, units=units)
        package = _package(structures=[structure])

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        constraints = " ".join(blueprint.answer_constraints).lower()
        assert "contrasting perspectives" in constraints

    def test_rst_contrasts_relation_captured_by_intra_contrast(self) -> None:
        """An intra-chunk relation with type "contrasts" is caught by the
        existing intra-chunk contrast check, not the RST-specific one.
        This verifies correct deduplication: only one contrast constraint."""
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main"),
            _unit("chunk_a_unit_1", "chunk_a", "support"),
        ]
        relation = IntraChunkDiscourseRelation(
            relation_id="chunk_a_rel_0",
            canonical_chunk_id="chunk_a",
            source_unit_id="chunk_a_unit_0",
            target_unit_id="chunk_a_unit_1",
            relation_type="contrasts",
            weight=1.0,
        )
        structure = _rst_structure(
            "chunk_a", main=True, units=units, relations=[relation]
        )
        package = _package(structures=[structure])

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        constraints = " ".join(blueprint.answer_constraints).lower()
        # Intra-chunk contrast constraint should be present
        assert "contrast" in constraints
        # But only one contrast constraint (intra, not RST duplicate)
        contrast_count = sum(
            1
            for c in blueprint.answer_constraints
            if "contrast" in c.lower() or "contrasting" in c.lower()
        )
        assert contrast_count == 1


class TestRSTDeduplication:
    """RST constraints are suppressed when graph/intra already covers the
    same semantic slot."""

    def test_rst_qualification_deduplicated_when_graph_has_qualification(self) -> None:
        """Graph specifies relation already adds qualification constraint;
        RST qualification should not add a second one."""
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role="qualification"),
        ]
        structure = _rst_structure("chunk_a", main=True, units=units)
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[structure],
        )
        graph = InterChunkDiscourseGraph(
            query=package.query,
            chunk_ids=["chunk_a", "chunk_b"],
            relations=[
                InterChunkDiscourseRelation(
                    source_chunk_id="chunk_b",
                    target_chunk_id="chunk_a",
                    relation_type="specifies",
                    rationale="graph qualification",
                )
            ],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

        constraints = blueprint.answer_constraints
        # Should have graph qualification but NOT RST qualification
        qual_count = sum(
            1
            for c in constraints
            if "qualification" in c.lower() or "qualifications" in c.lower()
        )
        # At most 1 qualification constraint (the graph one)
        assert qual_count == 1

    def test_rst_contrast_deduplicated_when_intra_has_contrast(self) -> None:
        """Intra-chunk contrast relation already adds contrast constraint;
        RST contrast should not add a second one."""
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role="contrast"),
            _unit("chunk_a_unit_1", "chunk_a", "support"),
        ]
        relation = IntraChunkDiscourseRelation(
            relation_id="chunk_a_rel_0",
            canonical_chunk_id="chunk_a",
            source_unit_id="chunk_a_unit_0",
            target_unit_id="chunk_a_unit_1",
            relation_type="contrast",
            weight=1.0,
        )
        structure = _rst_structure(
            "chunk_a", main=True, units=units, relations=[relation]
        )
        package = _package(structures=[structure])

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        constraints = blueprint.answer_constraints
        # Should have exactly 1 contrast-related constraint (the intra one)
        contrast_count = sum(
            1
            for c in constraints
            if "contrast" in c.lower() or "contrasting" in c.lower()
        )
        assert contrast_count == 1

    def test_rst_contrast_deduplicated_when_graph_has_conflict(self) -> None:
        """Graph conflict already adds conflict constraint; RST contrast
        should not add a second one."""
        units = [
            _unit("chunk_a_unit_0", "chunk_a", "main", planning_role="contrast"),
        ]
        structure = _rst_structure("chunk_a", main=True, units=units)
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[structure],
        )
        graph = InterChunkDiscourseGraph(
            query=package.query,
            chunk_ids=["chunk_a", "chunk_b"],
            relations=[
                InterChunkDiscourseRelation(
                    source_chunk_id="chunk_b",
                    target_chunk_id="chunk_a",
                    relation_type="contradicts",
                    rationale="conflict",
                )
            ],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

        constraints = blueprint.answer_constraints
        # Should have graph conflict constraint but NOT RST contrast constraint
        conflict_count = sum(
            1
            for c in constraints
            if "contradiction" in c.lower()
            or "conflict" in c.lower()
            or "contrasting perspectives" in c.lower()
        )
        assert conflict_count == 1
        # The one that exists should be the graph conflict one
        assert any(
            "inter-chunk" in c.lower() and "contradiction" in c.lower()
            for c in constraints
        )


class TestRSTLeadSelection:
    """Nucleus claim units influence lead/main selection."""

    def test_nucleus_claim_promoted_to_first_position(self) -> None:
        """When two chunks are both main, the one with a nucleus claim unit
        should be placed first."""
        units_a = [_unit("chunk_a_unit_0", "chunk_a", "main", planning_role="evidence")]
        units_b = [
            _unit(
                "chunk_b_unit_0",
                "chunk_b",
                "main",
                nuclearity="nucleus",
                planning_role="claim",
            )
        ]
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[
                _rst_structure("chunk_a", main=True, units=units_a),
                _rst_structure("chunk_b", main=True, units=units_b),
            ],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        # chunk_b should be promoted to first position
        assert blueprint.ordered_chunk_ids[0] == "chunk_b"
        assert blueprint.ordered_chunk_ids[1] == "chunk_a"

    def test_lead_selection_no_override_when_graph_has_conflict(self) -> None:
        """When graph has conflict/promotion relations, RST lead selection
        should not reorder."""
        units_a = [_unit("chunk_a_unit_0", "chunk_a", "main", planning_role="evidence")]
        units_b = [
            _unit(
                "chunk_b_unit_0",
                "chunk_b",
                "main",
                nuclearity="nucleus",
                planning_role="claim",
            )
        ]
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[
                _rst_structure("chunk_a", main=True, units=units_a),
                _rst_structure("chunk_b", main=True, units=units_b),
            ],
        )
        graph = InterChunkDiscourseGraph(
            query=package.query,
            chunk_ids=["chunk_a", "chunk_b"],
            relations=[
                InterChunkDiscourseRelation(
                    source_chunk_id="chunk_b",
                    target_chunk_id="chunk_a",
                    relation_type="contradicts",
                    rationale="conflict ordering",
                )
            ],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package, graph=graph)

        # Original retrieval order should be preserved
        assert blueprint.ordered_chunk_ids[0] == "chunk_a"

    def test_single_main_chunk_not_reordered(self) -> None:
        """When there is only one main chunk, no reordering occurs regardless
        of RST signals."""
        units = [
            _unit(
                "chunk_a_unit_0",
                "chunk_a",
                "main",
                nuclearity="nucleus",
                planning_role="claim",
            )
        ]
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[_rst_structure("chunk_a", main=True, units=units)],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b"]

    def test_lead_selection_ignores_satellite_claim(self) -> None:
        """A claim unit that is satellite (not nucleus) should not influence
        lead selection."""
        units_a = [_unit("chunk_a_unit_0", "chunk_a", "main", planning_role="evidence")]
        units_b = [
            _unit(
                "chunk_b_unit_0",
                "chunk_b",
                "main",
                nuclearity="satellite",
                planning_role="claim",
            )
        ]
        package = _package(
            items=[
                _evidence_item("chunk_a", order=0),
                _evidence_item("chunk_b", order=1),
            ],
            structures=[
                _rst_structure("chunk_a", main=True, units=units_a),
                _rst_structure("chunk_b", main=True, units=units_b),
            ],
        )

        blueprint = DiscoRAGAnswerBlueprintBuilder().build(package)

        # Original order preserved: satellite claim does not override
        assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b"]
