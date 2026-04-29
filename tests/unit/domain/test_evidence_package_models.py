from __future__ import annotations

from ragflow_lite.domain.models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GroundedQuery,
)


def test_evidence_provenance_required_fields() -> None:
    prov = EvidenceProvenance(document_id="doc_42")
    assert prov.document_id == "doc_42"
    assert prov.filename is None
    assert prov.file_type is None
    assert prov.chunk_index is None
    assert prov.metadata == {}


def test_evidence_provenance_all_fields() -> None:
    prov = EvidenceProvenance(
        document_id="doc_42",
        filename="report.pdf",
        file_type="pdf",
        chunk_index=3,
        metadata={"page": 5},
    )
    assert prov.filename == "report.pdf"
    assert prov.file_type == "pdf"
    assert prov.chunk_index == 3
    assert prov.metadata == {"page": 5}


def test_evidence_item_with_nested_provenance() -> None:
    prov = EvidenceProvenance(document_id="doc_1")
    item = EvidenceItem(
        canonical_chunk_id="chunk_0",
        text="some text",
        score=0.87,
        order=0,
        provenance=prov,
    )
    assert item.canonical_chunk_id == "chunk_0"
    assert item.text == "some text"
    assert item.score == 0.87
    assert item.order == 0
    assert item.provenance.document_id == "doc_1"
    assert item.retained_reasons == []
    assert item.grounded_entities == []
    assert item.answer_type_keywords == []
    assert item.topology_path_ids == []
    assert item.topology_relation_ids == []
    assert item.metadata == {}


def test_evidence_item_default_lists_are_independent() -> None:
    prov = EvidenceProvenance(document_id="doc_x")
    item_a = EvidenceItem(
        canonical_chunk_id="c1",
        text="a",
        score=0.9,
        order=0,
        provenance=prov,
    )
    item_b = EvidenceItem(
        canonical_chunk_id="c2",
        text="b",
        score=0.8,
        order=1,
        provenance=prov,
    )
    item_a.retained_reasons.append("high_score")
    assert item_b.retained_reasons == []


def test_evidence_item_all_optional_fields() -> None:
    prov = EvidenceProvenance(
        document_id="doc_2",
        filename="notes.md",
        file_type="md",
        chunk_index=1,
    )
    item = EvidenceItem(
        canonical_chunk_id="chunk_1",
        text="text",
        score=0.5,
        order=2,
        provenance=prov,
        retained_reasons=["high_score"],
        grounded_entities=["entity_a"],
        answer_type_keywords=["definition"],
        topology_path_ids=["path_0"],
        topology_relation_ids=["rel_0"],
        metadata={"source": "test"},
    )
    assert item.retained_reasons == ["high_score"]
    assert item.grounded_entities == ["entity_a"]
    assert item.answer_type_keywords == ["definition"]
    assert item.topology_path_ids == ["path_0"]
    assert item.topology_relation_ids == ["rel_0"]
    assert item.metadata == {"source": "test"}


def test_evidence_package_construction() -> None:
    gq = GroundedQuery(
        query="what is MiniRAG?",
        answer_type_keywords=["definition"],
        entities_from_query=["minirag"],
    )
    prov = EvidenceProvenance(document_id="doc_1")
    item = EvidenceItem(
        canonical_chunk_id="chunk_0",
        text="MiniRAG is a lightweight graph retrieval system.",
        score=0.95,
        order=0,
        provenance=prov,
    )
    pkg = EvidencePackage(
        query="what is MiniRAG?",
        grounded_query=gq,
        items=[item],
    )
    assert pkg.query == "what is MiniRAG?"
    assert pkg.grounded_query.query == "what is MiniRAG?"
    assert len(pkg.items) == 1
    assert pkg.items[0].canonical_chunk_id == "chunk_0"
    assert pkg.metadata == {}


def test_evidence_package_default_items_are_independent() -> None:
    gq = GroundedQuery(
        query="q",
        answer_type_keywords=[],
        entities_from_query=[],
    )
    pkg_a = EvidencePackage(query="q", grounded_query=gq)
    pkg_b = EvidencePackage(query="q", grounded_query=gq)
    pkg_a.items.append(
        EvidenceItem(
            canonical_chunk_id="c",
            text="t",
            score=1.0,
            order=0,
            provenance=EvidenceProvenance(document_id="d"),
        )
    )
    assert pkg_b.items == []
