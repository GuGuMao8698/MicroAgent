from __future__ import annotations

from dataclasses import dataclass

from ragflow_lite.application.services.minirag_topology_retriever import (
    MiniRAGTopologyRetriever,
)
from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    GroundedQuery,
    RelationEvidence,
    RetrievedChunk,
)


def _chunk(
    chunk_id: str,
    text: str,
    *,
    score: float = 0.5,
    document_id: str = "doc1",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        score=score,
        metadata={"filename": "doc.md"},
    )


@dataclass
class _FakeBaseRetriever:
    chunks: list[RetrievedChunk]

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.chunks[:top_k]


@dataclass
class _FakeGrounder:
    grounded: GroundedQuery

    def ground(self, query: str) -> GroundedQuery:
        return self.grounded


class _FakeGraphStore:
    def __init__(self, batch: GraphEvidenceBatch | None) -> None:
        self.batch = batch

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        return (
            self.batch if self.batch and self.batch.document_id == document_id else None
        )


class _FakeChunkLookup:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunks(self, chunk_ids: list[str]) -> list[RetrievedChunk]:
        return [
            self.chunks_by_id[chunk_id]
            for chunk_id in chunk_ids
            if chunk_id in self.chunks_by_id
        ]


def _batch() -> GraphEvidenceBatch:
    mini = EntityEvidence(
        entity_id="entity_minirag",
        document_id="doc1",
        name="MiniRAG",
        entity_type="concept",
        description="Graph retrieval method.",
        source_chunk_ids=["chunk_doc1_0"],
    )
    recovery = EntityEvidence(
        entity_id="entity_chunk_recovery",
        document_id="doc1",
        name="chunk recovery",
        entity_type="mechanism",
        description="Mapping graph paths back to source chunks.",
        source_chunk_ids=["chunk_doc1_1"],
    )
    relation = RelationEvidence(
        relation_id="relation_minirag_recovery",
        document_id="doc1",
        source_entity_id=mini.entity_id,
        target_entity_id=recovery.entity_id,
        source_entity_name=mini.name,
        target_entity_name=recovery.name,
        description="MiniRAG recovers chunks from graph paths.",
        keywords=["path", "chunk recovery"],
        weight=1.0,
        source_chunk_ids=["chunk_doc1_0", "chunk_doc1_1"],
    )
    return GraphEvidenceBatch(
        document_id="doc1",
        entities=[mini, recovery],
        relations=[relation],
    )


def test_topology_retriever_recovers_graph_chunks_before_baseline_chunks() -> None:
    base_chunk = _chunk("chunk_doc1_0", "MiniRAG grounds queries.", score=0.8)
    graph_chunk = _chunk("chunk_doc1_1", "Graph paths recover source chunks.")
    retriever = MiniRAGTopologyRetriever(
        base_retriever=_FakeBaseRetriever([base_chunk]),
        query_grounder=_FakeGrounder(
            GroundedQuery(
                query="How does MiniRAG recover chunks?",
                answer_type_keywords=["mechanism"],
                entities_from_query=["MiniRAG"],
            )
        ),
        graph_store=_FakeGraphStore(_batch()),
        chunk_lookup=_FakeChunkLookup([base_chunk, graph_chunk]),
        candidate_multiplier=2,
        max_hops=2,
    )

    chunks = retriever.retrieve("How does MiniRAG recover chunks?", top_k=2)

    assert [chunk.chunk_id for chunk in chunks] == ["chunk_doc1_0", "chunk_doc1_1"]
    assert chunks[0].metadata["retrieval_mode"] == "minirag_topology"
    assert chunks[0].metadata["grounded_entities"] == ["MiniRAG"]
    assert chunks[0].metadata["answer_type_keywords"] == ["mechanism"]
    assert "relation_minirag_recovery" in chunks[0].metadata["topology_relation_ids"]


def test_topology_retriever_falls_back_when_graph_evidence_missing() -> None:
    base_chunk = _chunk("chunk_doc1_0", "Baseline result.", score=0.8)
    retriever = MiniRAGTopologyRetriever(
        base_retriever=_FakeBaseRetriever([base_chunk]),
        query_grounder=_FakeGrounder(
            GroundedQuery(
                query="What is MiniRAG?",
                answer_type_keywords=["concept"],
                entities_from_query=["MiniRAG"],
            )
        ),
        graph_store=_FakeGraphStore(None),
        chunk_lookup=_FakeChunkLookup([base_chunk]),
    )

    chunks = retriever.retrieve("What is MiniRAG?", top_k=1)

    assert chunks == [base_chunk]
    assert "retrieval_mode" not in chunks[0].metadata


def test_sequential_queries_do_not_leak_per_request_state() -> None:
    """Two sequential retrieve calls must not interfere with each other."""
    grounder_query_a = GroundedQuery(
        query="find alpha",
        entities_from_query=["EntityAlpha"],
        answer_type_keywords=["definition"],
    )
    grounder_query_b = GroundedQuery(
        query="find beta",
        entities_from_query=["EntityBeta"],
        answer_type_keywords=["comparison"],
    )

    class _VariableGrounder:
        def ground(self, query: str) -> GroundedQuery:
            if "alpha" in query:
                return grounder_query_a
            return grounder_query_b

    retriever = MiniRAGTopologyRetriever(
        base_retriever=_FakeBaseRetriever(
            [_chunk("c1", "alpha text", document_id="doc1")]
        ),
        query_grounder=_VariableGrounder(),
        graph_store=_FakeGraphStore(None),
        chunk_lookup=_FakeChunkLookup([]),
    )

    result_a = retriever.retrieve_context("find alpha", top_k=4)
    result_b = retriever.retrieve_context("find beta", top_k=4)

    # Each result should reflect only its own query grounding.
    assert result_a.grounded_query is grounder_query_a
    assert result_b.grounded_query is grounder_query_b
    assert result_a.query == "find alpha"
    assert result_b.query == "find beta"
