from __future__ import annotations

from typing import Protocol

from ragflow_lite.domain.models import (
    STEP_GRAPH_EVIDENCE,
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    RelationEvidence,
)
from ragflow_lite.domain.ports.interfaces import (
    EvidenceExtractor,
    GraphEvidenceStore,
)


def test_graph_evidence_models_preserve_source_chunks() -> None:
    entity = EntityEvidence(
        entity_id="entity_doc_alpha_minirag",
        document_id="doc_alpha",
        name="MiniRAG",
        entity_type="concept",
        description="Lightweight graph retrieval.",
        source_chunk_ids=["chunk_doc_alpha_0"],
        metadata={"source_id": "chunk_doc_alpha_0"},
    )
    relation = RelationEvidence(
        relation_id="relation_doc_alpha_minirag_chunk",
        document_id="doc_alpha",
        source_entity_id="entity_doc_alpha_minirag",
        target_entity_id="entity_doc_alpha_chunk",
        source_entity_name="MiniRAG",
        target_entity_name="chunk",
        description="MiniRAG links extracted entities back to chunks.",
        keywords=["provenance"],
        weight=1.0,
        source_chunk_ids=["chunk_doc_alpha_0"],
        metadata={"source_id": "chunk_doc_alpha_0"},
    )

    batch = GraphEvidenceBatch(
        document_id="doc_alpha",
        entities=[entity],
        relations=[relation],
        metadata={"extractor": "unit"},
    )
    result = GraphEvidenceWriteResult(
        document_id="doc_alpha",
        entity_count=1,
        relation_count=1,
    )

    assert STEP_GRAPH_EVIDENCE == "graph_evidence"
    assert batch.entities[0].source_chunk_ids == ["chunk_doc_alpha_0"]
    assert batch.relations[0].metadata["source_id"] == "chunk_doc_alpha_0"
    assert result.entity_count == 1
    assert result.relation_count == 1


def test_graph_evidence_ports_are_protocols() -> None:
    assert issubclass(EvidenceExtractor, Protocol)
    assert issubclass(GraphEvidenceStore, Protocol)
