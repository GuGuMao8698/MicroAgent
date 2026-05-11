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


from typing import Protocol

from ragflow_lite.domain.ports.interfaces import (
    ChunkLookup,
    QueryGrounder,
    TopologyContextRetriever,
)


def test_minirag_query_ports_are_protocols() -> None:
    assert issubclass(QueryGrounder, Protocol)
    assert issubclass(ChunkLookup, Protocol)
    assert issubclass(TopologyContextRetriever, Protocol)


from ragflow_lite.domain.models import (
    CoTGroundingResult,
    EnrichedGroundingInput,
    GraphFirstSourceSelection,
    GroundingGateDecision,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
)
from ragflow_lite.domain.ports.interfaces import CoTGroundingRewriter


def test_retrieval_rewrite_models_preserve_snapshot_and_status() -> None:
    grounded = GroundedQuery(
        query="What improves MiniRAG recall?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
    )
    chunk = RetrievedChunk(
        chunk_id="chunk_a",
        document_id="doc1",
        text="MiniRAG uses graph evidence.",
        score=1.0,
        metadata={"selected_for_answer": True},
    )
    selection = GraphFirstSourceSelection(
        sources=[],
        final_context_k=2,
        discourse_selection_k=4,
        context_token_budget=None,
        omitted_source_count=0,
    )

    snapshot = InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=grounded,
        candidates=[chunk],
        source_selection=selection,
        metadata={"source": "initial"},
    )
    gate = GroundingGateDecision(
        should_rewrite=True,
        route="rewrite",
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )
    rewrite = CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify MiniRAG recall mechanisms."],
        attempts=1,
        failure_reason=None,
    )
    enriched = EnrichedGroundingInput(
        original_query=snapshot.query,
        solution_steps=rewrite.solution_steps,
    )
    assessment = PostRewriteAssessment(
        gate_passed=False,
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )

    assert snapshot.candidates == [chunk]
    assert gate.route == "rewrite"
    assert rewrite.solution_steps == ["Identify MiniRAG recall mechanisms."]
    assert enriched.original_query == snapshot.query
    assert assessment.gate_passed is False


def test_cot_grounding_rewriter_is_protocol() -> None:
    assert issubclass(CoTGroundingRewriter, Protocol)
