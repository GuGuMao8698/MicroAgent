from __future__ import annotations

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_evidence_index import (
    LocalJsonGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.evidence.local_json_store import (
    LocalJsonGraphEvidenceStore,
)


def _write_batch(tmp_path) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc1",
            entities=[
                EntityEvidence(
                    entity_id="entity_minirag",
                    document_id="doc1",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval mode.",
                    source_chunk_ids=["chunk_a"],
                ),
                EntityEvidence(
                    entity_id="entity_sources",
                    document_id="doc1",
                    name="Sources",
                    entity_type="evidence",
                    description="Recovered chunks.",
                    source_chunk_ids=["chunk_b"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="relation_minirag_sources",
                    document_id="doc1",
                    source_entity_id="entity_minirag",
                    target_entity_id="entity_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Sources",
                    description="MiniRAG recovers source chunks.",
                    keywords=["mechanism"],
                    weight=1.0,
                    source_chunk_ids=["chunk_a", "chunk_b"],
                )
            ],
        )
    )


def test_local_json_graph_index_queries_entities_relationships_and_paths(
    tmp_path,
) -> None:
    _write_batch(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path)

    entity_candidates = index.query_entities(["MiniRAG"], top_k=3)
    relationship_candidates = index.query_relationships(
        "How does MiniRAG recover sources?",
        ["mechanism"],
        top_k=3,
    )
    paths = index.expand_paths(
        seed_entity_ids=[entity_candidates[0].entity.entity_id],
        seed_relation_ids=[relationship_candidates[0].relation.relation_id],
        max_hops=2,
    )

    assert [candidate.entity.entity_id for candidate in entity_candidates] == [
        "entity_minirag"
    ]
    assert [
        candidate.relation.relation_id for candidate in relationship_candidates
    ] == ["relation_minirag_sources"]
    assert paths[0].candidate_group_id == "entity_minirag"
    assert paths[0].candidate_rank == 0
    assert paths[0].source_chunk_ids == ["chunk_a", "chunk_b"]
    assert paths[0].metadata["hop_count"] == 1
