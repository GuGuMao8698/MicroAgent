from __future__ import annotations

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


def _evidence_package() -> EvidencePackage:
    grounded = GroundedQuery(
        query="How does MiniRAG recover evidence?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
        metadata={"grounder": "unit"},
    )
    item = EvidenceItem(
        canonical_chunk_id="chunk_doc_alpha_0",
        text="MiniRAG first retrieves chunks. Graph paths then explain why they matter.",
        score=0.82,
        order=0,
        provenance=EvidenceProvenance(
            document_id="doc_alpha",
            filename="alpha.md",
            file_type="markdown",
            chunk_index=0,
        ),
        retained_reasons=["topology_path"],
        grounded_entities=["MiniRAG"],
        answer_type_keywords=["mechanism"],
        topology_path_ids=["path_alpha_0"],
        topology_relation_ids=["relation_alpha_0"],
        metadata={"retrieval_mode": "minirag_topology"},
    )
    return EvidencePackage(
        query=grounded.query,
        grounded_query=grounded,
        items=[item],
        metadata={"evidence_count": 1},
    )


def test_intra_chunk_discourse_models_preserve_contract_fields() -> None:
    evidence_package = _evidence_package()
    main = DiscourseUnit(
        unit_id="unit_chunk_doc_alpha_0_0",
        canonical_chunk_id="chunk_doc_alpha_0",
        text="MiniRAG first retrieves chunks.",
        order=0,
        role="main",
        start_char=0,
        end_char=31,
    )
    support = DiscourseUnit(
        unit_id="unit_chunk_doc_alpha_0_1",
        canonical_chunk_id="chunk_doc_alpha_0",
        text="Graph paths then explain why they matter.",
        order=1,
        role="support",
        start_char=32,
        end_char=75,
        metadata={"confidence": "high"},
    )
    relation = IntraChunkDiscourseRelation(
        relation_id="relation_chunk_doc_alpha_0_0_1_supports",
        canonical_chunk_id="chunk_doc_alpha_0",
        source_unit_id=main.unit_id,
        target_unit_id=support.unit_id,
        relation_type="supports",
        weight=1.0,
    )
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_doc_alpha_0",
        document_id="doc_alpha",
        units=[main, support],
        relations=[relation],
        main_unit_ids=[main.unit_id],
        supporting_unit_ids=[support.unit_id],
        metadata={"extractor": "unit"},
    )
    package = IntraChunkDiscoursePackage(
        query=evidence_package.query,
        evidence_package=evidence_package,
        structures=[structure],
        metadata={"status": "ok", "structure_count": 1},
    )

    assert package.evidence_package.items[0].canonical_chunk_id == "chunk_doc_alpha_0"
    assert package.structures[0].units[0].role == "main"
    assert package.structures[0].relations[0].relation_type == "supports"
    assert package.structures[0].main_unit_ids == [main.unit_id]
    assert package.metadata["structure_count"] == 1
