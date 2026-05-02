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


def _unit(unit_id: str, chunk_id: str, role: str) -> DiscourseUnit:
    return DiscourseUnit(
        unit_id=unit_id,
        canonical_chunk_id=chunk_id,
        text=f"{role} text",
        order=0,
        role=role,
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


def test_blueprint_builder_is_exported_from_application_services() -> None:
    from ragflow_lite.application.services import (
        DiscoRAGAnswerBlueprintBuilder as Exported,
    )

    assert Exported is DiscoRAGAnswerBlueprintBuilder
