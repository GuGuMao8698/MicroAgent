from __future__ import annotations

import pytest

from ragflow_lite.application.services.inter_chunk_discourse_graph_builder import (
    DeterministicInterChunkDiscourseGraphBuilder,
)
from ragflow_lite.domain.models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GroundedQuery,
    IntraChunkDiscoursePackage,
)


def _item(
    chunk_id: str,
    *,
    order: int,
    selected_for_answer: bool,
    supplemental: bool = False,
    topology_relation_ids: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> EvidenceItem:
    item_metadata: dict[str, object] = {
        "selected_for_answer": selected_for_answer,
        "selected_for_discourse": True,
        "supplemental_discourse": supplemental,
    }
    if metadata is not None:
        item_metadata.update(metadata)
    return EvidenceItem(
        canonical_chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        score=1.0,
        order=order,
        provenance=EvidenceProvenance(document_id="doc1"),
        topology_relation_ids=topology_relation_ids or [],
        metadata=item_metadata,
    )


def _package(items: list[EvidenceItem]) -> IntraChunkDiscoursePackage:
    evidence = EvidencePackage(
        query="q",
        grounded_query=GroundedQuery(
            query="q",
            answer_type_keywords=[],
            entities_from_query=[],
        ),
        items=items,
    )
    return IntraChunkDiscoursePackage(
        query="q",
        evidence_package=evidence,
        structures=[],
    )


def test_build_adds_qualifies_relation_from_supplemental_to_answer_chunk() -> None:
    package = _package(
        [
            _item(
                "chunk_answer",
                order=0,
                selected_for_answer=True,
                topology_relation_ids=["rel_shared"],
            ),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                topology_relation_ids=["rel_shared"],
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert graph.chunk_ids == ["chunk_answer", "chunk_supplemental"]
    assert len(graph.relations) == 1
    relation = graph.relations[0]
    assert relation.source_chunk_id == "chunk_supplemental"
    assert relation.target_chunk_id == "chunk_answer"
    assert relation.relation_type == "qualifies"
    assert relation.metadata["shared_topology_relation_ids"] == ["rel_shared"]


def test_build_returns_empty_sparse_graph_without_relation_signal() -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item("chunk_other", order=1, selected_for_answer=False, supplemental=True),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert graph.chunk_ids == ["chunk_answer", "chunk_other"]
    assert graph.relations == []
    assert graph.metadata["builder"] == "deterministic_inter_chunk_discourse"


def test_builder_uses_explicit_inter_chunk_relation_metadata() -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "contradicts",
                    "inter_chunk_target_chunk_id": "chunk_answer",
                    "inter_chunk_relation_rationale": "Opposing conclusions",
                    "inter_chunk_relation_confidence": 0.9,
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert len(graph.relations) == 1
    relation = graph.relations[0]
    assert relation.source_chunk_id == "chunk_supplemental"
    assert relation.target_chunk_id == "chunk_answer"
    assert relation.relation_type == "contradicts"
    assert relation.confidence == 0.9
    assert relation.metadata["source"] == "explicit_inter_chunk_relation_metadata"


def test_builder_ignores_explicit_relation_to_unknown_target() -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "supports",
                    "inter_chunk_target_chunk_id": "missing_chunk",
                    "inter_chunk_relation_confidence": 0.8,
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert graph.relations == []


def test_builder_rejects_explicit_self_referential_relation() -> None:
    package = _package(
        [
            _item(
                "chunk_both",
                order=0,
                selected_for_answer=True,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "supports",
                    "inter_chunk_target_chunk_id": "chunk_both",
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert graph.relations == []


@pytest.mark.parametrize(
    "raw_confidence, expected",
    [
        (-0.5, 0.0),
        (1.5, 1.0),
    ],
)
def test_builder_clamps_explicit_confidence_to_valid_range(
    raw_confidence: float, expected: float
) -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "supports",
                    "inter_chunk_target_chunk_id": "chunk_answer",
                    "inter_chunk_relation_confidence": raw_confidence,
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert len(graph.relations) == 1
    assert graph.relations[0].confidence == expected


def test_builder_uses_default_rationale_when_empty() -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "supports",
                    "inter_chunk_target_chunk_id": "chunk_answer",
                    "inter_chunk_relation_rationale": "",
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert len(graph.relations) == 1
    assert (
        graph.relations[0].rationale
        == "Explicit metadata marks an inter-chunk discourse relation."
    )


def test_builder_ignores_invalid_explicit_relation_type() -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": "invalid_type",
                    "inter_chunk_target_chunk_id": "chunk_answer",
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert graph.relations == []


@pytest.mark.parametrize(
    "relation_type",
    ["supports", "background_for", "elaborates", "example_of"],
)
def test_builder_accepts_non_promoting_relation_types(relation_type: str) -> None:
    package = _package(
        [
            _item("chunk_answer", order=0, selected_for_answer=True),
            _item(
                "chunk_supplemental",
                order=1,
                selected_for_answer=False,
                supplemental=True,
                metadata={
                    "inter_chunk_relation_type": relation_type,
                    "inter_chunk_target_chunk_id": "chunk_answer",
                },
            ),
        ]
    )

    graph = DeterministicInterChunkDiscourseGraphBuilder().build(package)

    assert [relation.relation_type for relation in graph.relations] == [relation_type]
