from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence import LocalJsonGraphEvidenceStore


def _batch(document_id: str = "doc_alpha") -> GraphEvidenceBatch:
    entity = EntityEvidence(
        entity_id="entity_alpha_minirag",
        document_id=document_id,
        name="MiniRAG",
        entity_type="concept",
        description="Lightweight graph retrieval.",
        source_chunk_ids=["chunk_doc_alpha_0"],
        metadata={"source_id": "chunk_doc_alpha_0"},
    )
    relation = RelationEvidence(
        relation_id="relation_alpha_minirag_chunk",
        document_id=document_id,
        source_entity_id="entity_alpha_minirag",
        target_entity_id="entity_alpha_chunk",
        source_entity_name="MiniRAG",
        target_entity_name="chunk",
        description="MiniRAG links evidence back to chunks.",
        keywords=["provenance"],
        weight=1.0,
        source_chunk_ids=["chunk_doc_alpha_0"],
        metadata={"source_id": "chunk_doc_alpha_0"},
    )
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[entity],
        relations=[relation],
        metadata={"extractor": "unit"},
    )


def test_local_graph_evidence_store_round_trips_document_evidence(
    tmp_path: Path,
) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)

    result = store.upsert_document_evidence(_batch())
    loaded = store.get_document_evidence("doc_alpha")

    assert result.document_id == "doc_alpha"
    assert result.entity_count == 1
    assert result.relation_count == 1
    assert loaded == _batch()


def test_local_graph_evidence_store_replaces_document_evidence(
    tmp_path: Path,
) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(_batch())
    replacement = GraphEvidenceBatch(
        document_id="doc_alpha",
        entities=[],
        relations=[],
        metadata={"extractor": "replacement"},
    )

    store.upsert_document_evidence(replacement)

    assert store.get_document_evidence("doc_alpha") == replacement


def test_local_graph_evidence_store_deletes_document_evidence(tmp_path: Path) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(_batch())

    store.delete_document("doc_alpha")

    assert store.get_document_evidence("doc_alpha") is None
