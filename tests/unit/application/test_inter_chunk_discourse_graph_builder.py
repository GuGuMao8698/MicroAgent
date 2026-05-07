from __future__ import annotations

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
) -> EvidenceItem:
    return EvidenceItem(
        canonical_chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        score=1.0,
        order=order,
        provenance=EvidenceProvenance(document_id="doc1"),
        topology_relation_ids=topology_relation_ids or [],
        metadata={
            "selected_for_answer": selected_for_answer,
            "selected_for_discourse": True,
            "supplemental_discourse": supplemental,
        },
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
