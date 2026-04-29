from __future__ import annotations

from ragflow_lite.domain.models import (
    GroundedQuery,
    RetrievedChunk,
    TopologyPath,
    TopologyRetrievalResult,
)


def test_minirag_query_topology_models_preserve_grounding_and_paths() -> None:
    grounded = GroundedQuery(
        query="How does MiniRAG recover chunks?",
        answer_type_keywords=["concept", "mechanism"],
        entities_from_query=["MiniRAG", "chunk recovery"],
        metadata={"grounder": "unit"},
    )
    path = TopologyPath(
        path_id="path_doc1_1",
        document_id="doc1",
        entity_ids=["entity_minirag", "entity_chunk_recovery"],
        relation_ids=["relation_minirag_chunk_recovery"],
        source_chunk_ids=["chunk_doc1_0", "chunk_doc1_1"],
        score=1.5,
        metadata={"hop_count": 1},
    )
    chunk = RetrievedChunk(
        chunk_id="chunk_doc1_1",
        document_id="doc1",
        text="MiniRAG maps graph paths back to chunks.",
        score=0.0,
        metadata={"retrieval_mode": "minirag_topology"},
    )

    result = TopologyRetrievalResult(
        query=grounded.query,
        grounded_query=grounded,
        chunks=[chunk],
        paths=[path],
        metadata={"candidate_count": 4},
    )

    assert result.grounded_query.entities_from_query == [
        "MiniRAG",
        "chunk recovery",
    ]
    assert result.paths[0].source_chunk_ids == ["chunk_doc1_0", "chunk_doc1_1"]
    assert result.chunks[0].metadata["retrieval_mode"] == "minirag_topology"
