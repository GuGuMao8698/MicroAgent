from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services.mini_graph_first_retriever import (
    MiniGraphFirstRetriever,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.models import (
    CoTGroundingResult,
    EntityEvidence,
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RelationEvidence,
    RetrievedChunk,
    SourceChunkSupport,
    TopologyPath,
    TopologyRetrievalResult,
)


@dataclass
class RecordingGrounder:
    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        )


@dataclass
class RecordingEntityIndex:
    calls: list[list[str]] = field(default_factory=list)

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        self.calls.append(entity_texts)
        return [
            MiniEntityCandidate(
                entity=EntityEvidence(
                    entity_id="entity_minirag",
                    document_id="doc1",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval.",
                    source_chunk_ids=["chunk_a"],
                ),
                score=1.0,
                matched_terms=["MiniRAG"],
            )
        ]


@dataclass
class RecordingRelationshipIndex:
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        self.calls.append((query, tuple(answer_type_keywords)))
        return [
            MiniRelationshipCandidate(
                relation=RelationEvidence(
                    relation_id="relation_minirag_sources",
                    document_id="doc1",
                    source_entity_id="entity_minirag",
                    target_entity_id="entity_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Sources",
                    description="MiniRAG recovers source chunks from graph paths.",
                    keywords=["mechanism"],
                    weight=1.0,
                    source_chunk_ids=["chunk_a", "chunk_b"],
                ),
                score=1.0,
                matched_terms=["mechanism"],
            )
        ]


@dataclass
class RecordingPathExpander:
    calls: list[tuple[tuple[str, ...], tuple[str, ...], int]] = field(
        default_factory=list
    )

    def expand_paths(
        self,
        seed_entity_ids: list[str],
        seed_relation_ids: list[str],
        max_hops: int,
    ) -> list[TopologyPath]:
        self.calls.append((tuple(seed_entity_ids), tuple(seed_relation_ids), max_hops))
        return [
            TopologyPath(
                path_id="path_1",
                document_id="doc1",
                entity_ids=["entity_minirag", "entity_sources"],
                relation_ids=["relation_minirag_sources"],
                source_chunk_ids=["chunk_a", "chunk_b"],
                score=1.0,
                metadata={"hop_count": 1},
            )
        ]


class RecordingChunkLookup:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_chunks(self, chunk_ids: list[str]) -> list[RetrievedChunk]:
        self.calls.append(chunk_ids)
        return [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id="doc1",
                text=f"text for {chunk_id}",
                score=0.0,
                metadata={},
            )
            for chunk_id in chunk_ids
        ]


class RecordingAuxiliaryRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return [
            RetrievedChunk(
                chunk_id="chunk_b",
                document_id="doc1",
                text="auxiliary hit",
                score=0.7,
                metadata={},
            )
        ]


class ManyAuxiliaryRetriever:
    def __init__(self, chunk_count: int) -> None:
        self.chunk_count = chunk_count
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return [
            RetrievedChunk(
                chunk_id=f"chunk_{index}",
                document_id="doc1",
                text=f"auxiliary hit {index}",
                score=float(self.chunk_count - index),
                metadata={},
            )
            for index in range(self.chunk_count)
        ]


class QueryAwareAuxiliaryRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        if "Solution steps:" in query:
            return [
                RetrievedChunk(
                    chunk_id="chunk_enriched",
                    document_id="doc1",
                    text="enriched chunk",
                    score=4.0,
                    metadata={"filename": "enriched.md"},
                ),
                RetrievedChunk(
                    chunk_id="chunk_supplemental_valid",
                    document_id="doc1",
                    text="valid supplemental chunk",
                    score=3.0,
                    metadata={"filename": "supplemental.md"},
                ),
                RetrievedChunk(
                    chunk_id="chunk_supplemental_stale",
                    document_id="doc1",
                    text="stale supplemental chunk",
                    score=2.0,
                    metadata={"filename": "stale.md"},
                ),
            ]
        return [
            RetrievedChunk(
                chunk_id="chunk_initial",
                document_id="doc1",
                text="initial chunk",
                score=5.0,
                metadata={"filename": "initial.md"},
            ),
            RetrievedChunk(
                chunk_id="chunk_initial_supplemental",
                document_id="doc1",
                text="initial supplemental chunk",
                score=1.0,
                metadata={"filename": "initial-supplemental.md"},
            ),
        ]


def _path(
    path_id: str,
    entity_ids: list[str],
    relation_ids: list[str],
    source_chunk_ids: list[str],
    *,
    answer_hit_count: int = 0,
    candidate_group_id: str | None = None,
    candidate_rank: int | None = None,
) -> TopologyPath:
    """构造 TopologyPath 的辅助函数，支持 answer_type_hit_count 元数据。"""
    metadata: dict[str, object] = {"answer_type_hit_count": answer_hit_count}
    return TopologyPath(
        path_id=path_id,
        document_id="doc1",
        entity_ids=entity_ids,
        relation_ids=relation_ids,
        source_chunk_ids=source_chunk_ids,
        score=1.0,
        candidate_group_id=candidate_group_id,
        candidate_rank=candidate_rank,
        metadata=metadata,
    )


def test_mini_graph_first_retriever_without_rewriter_keeps_existing_metadata() -> None:
    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=RecordingAuxiliaryRetriever(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert result.metadata["retrieval_mode"] == "mini_graph_first"
    assert "retrieval_rewrite" not in result.metadata
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_a", "chunk_b"]


def test_mini_graph_first_retriever_grounds_before_auxiliary_chunk_retrieval() -> None:
    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = RecordingAuxiliaryRetriever()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        path_hop_limit=2,
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert grounder.calls == ["How does MiniRAG recover sources?"]
    assert entity_index.calls == [["MiniRAG"]]
    assert relationship_index.calls == [
        ("How does MiniRAG recover sources?", ("mechanism",))
    ]
    assert path_expander.calls == [
        (("entity_minirag",), ("relation_minirag_sources",), 2)
    ]
    # 新预算语义：auxiliary top_k = int(mini_internal_candidate_n / 2) = int(60 / 2) = 30
    assert auxiliary_retriever.calls == [("How does MiniRAG recover sources?", 30)]
    # 新评分：path_weight=2.0, first_candidate=2.0, aux_path=1.0
    # chunk_a 和 chunk_b 均为 4.0，按 chunk_id 升序排列
    assert chunk_lookup.calls == [["chunk_a", "chunk_b"]]
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_a", "chunk_b"]
    assert result.chunks[0].metadata["retrieval_mode"] == "mini_graph_first"
    assert result.chunks[0].metadata["supporting_path_ids"] == ["path_1"]
    # chunk_b 是辅助检索命中的 chunk，现在排在第二位
    assert result.chunks[1].metadata["auxiliary_chunk_hit"] is True


def test_source_chunk_with_more_minirag_counter_support_ranks_first() -> None:
    """拥有更多 MiniRAG Counter 投票支撑的 chunk 应排在前面。"""

    class TwoPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_1",
                    ["entity_minirag"],
                    ["relation_1"],
                    ["chunk_a"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=0,
                ),
                _path(
                    "path_2",
                    ["entity_minirag"],
                    ["relation_2"],
                    ["chunk_a", "chunk_b"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=1,
                ),
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=TwoPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    chunks = retriever.retrieve("How does MiniRAG recover sources?", top_k=2)

    # chunk_a 被 2 条路径支撑（path_1 贡献 1*1*2.0=2.0, path_2 贡献 1*1*1.0=1.0, 总计 3.0）
    # chunk_b 被 1 条路径支撑（path_2 贡献 1*1*1.0=1.0）
    assert [chunk.chunk_id for chunk in chunks] == ["chunk_a", "chunk_b"]
    assert chunks[0].metadata["scoring_policy"] == "minirag_counter_parity"
    assert chunks[0].metadata["source_score_components"]["minirag_counter_score"] == 3.0
    assert chunks[1].metadata["source_score_components"]["minirag_counter_score"] == 1.0


def test_graph_first_source_selection_models_are_exported() -> None:
    """验证 GraphFirstSource / GraphFirstSourceSelection 领域模型可正常导入和构造。"""
    from ragflow_lite.domain.models import (
        GraphFirstSource,
        GraphFirstSourceSelection,
    )

    source = GraphFirstSource(
        chunk_id="chunk_a",
        rank=0,
        score=1.5,
        score_components={"path": 1.0, "relation": 0.5},
        supporting_entity_ids=["entity_a"],
        supporting_relation_ids=["relation_a"],
        supporting_path_ids=["path_a"],
        auxiliary_chunk_hit=False,
        selected_for_answer=True,
        selected_for_discourse=True,
        selection_reason="graph_path_support+graph_relation_support",
    )
    selection = GraphFirstSourceSelection(
        sources=[source],
        final_context_k=1,
        discourse_selection_k=1,
        context_token_budget=None,
        omitted_source_count=0,
        fallback_reason=None,
    )

    assert selection.sources[0].chunk_id == "chunk_a"
    assert selection.sources[0].selected_for_discourse is True


def test_mini_graph_first_retriever_returns_source_selection_budget_metadata() -> None:
    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = RecordingAuxiliaryRetriever()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        path_hop_limit=2,
        discourse_selection_k=1,
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert result.source_selection is not None
    # 验证 source_selection metadata 中包含 scoring_policy
    assert result.metadata["source_selection"]["scoring_policy"] == (
        "minirag_counter_parity"
    )
    selection = result.source_selection
    assert selection.final_context_k == 2
    assert selection.discourse_selection_k == 1
    assert selection.context_token_budget is None
    assert selection.omitted_source_count == 0
    assert selection.fallback_reason is None
    # 新评分：chunk_a 和 chunk_b 均为 4.0，按 chunk_id 升序排列
    assert [source.chunk_id for source in selection.sources] == ["chunk_a", "chunk_b"]
    assert [source.rank for source in selection.sources] == [0, 1]
    assert selection.sources[0].selected_for_answer is True
    assert selection.sources[0].selected_for_discourse is True
    assert selection.sources[1].selected_for_answer is True
    assert selection.sources[1].selected_for_discourse is False
    assert "graph_path_support" in selection.sources[0].selection_reason
    assert "auxiliary_fallback" in selection.sources[1].selection_reason
    assert result.metadata["source_selection"]["selected_answer_chunk_ids"] == [
        "chunk_a",
        "chunk_b",
    ]
    assert result.metadata["source_selection"]["selected_discourse_chunk_ids"] == [
        "chunk_a",
    ]


@dataclass
class FailingCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="failed",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=2,
            failure_reason="invalid structured output",
        )


@dataclass
class EmptyGrounder:
    def ground(self, query: str) -> GroundedQuery:
        return GroundedQuery(
            query=query,
            answer_type_keywords=[],
            entities_from_query=[],
        )


@dataclass
class KeywordOnlyGrounder:
    """返回 answer_type_keywords 但不返回实体，用于验证关系预算下限。"""

    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=[],
        )


def test_mini_graph_first_retriever_source_selection_records_empty_grounding_fallback() -> (
    None
):
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = RecordingAuxiliaryRetriever()
    retriever = MiniGraphFirstRetriever(
        query_grounder=EmptyGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        discourse_selection_k=1,
    )

    result = retriever.retrieve_context("unknown", top_k=1)

    assert result.source_selection is not None
    selection = result.source_selection
    assert selection.fallback_reason == "empty_grounding"
    assert selection.sources[0].selection_reason == "auxiliary_fallback"
    assert selection.sources[0].selected_for_answer is True
    assert selection.sources[0].selected_for_discourse is True
    assert result.chunks[0].metadata["fallback_reason"] == "empty_grounding"


def test_empty_grounding_fallback_keeps_supplemental_discourse_out_of_answer_contexts() -> (
    None
):
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=4)
    retriever = MiniGraphFirstRetriever(
        query_grounder=EmptyGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
    )

    result = retriever.retrieve_context("unknown", top_k=2)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_0", "chunk_1"]
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 4
    summary = result.metadata["source_selection"]
    assert summary["selected_answer_chunk_ids"] == ["chunk_0", "chunk_1"]
    assert summary["selected_discourse_chunk_ids"] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
    ]
    supplemental = result.metadata["supplemental_discourse_chunks"]
    assert list(supplemental) == ["chunk_2", "chunk_3"]
    assert supplemental["chunk_2"].metadata["selected_for_answer"] is False
    assert supplemental["chunk_2"].metadata["selected_for_discourse"] is True


# ---------------------------------------------------------------------------
# MiniRAG-parity 评分测试（TDD 红阶段 —— 预期失败）
# ---------------------------------------------------------------------------
# 以下 3 个测试定义了 MiniRAG Counter/投票评分语义的期望行为。
# 当前生产评分器仍使用旧线性权重，因此这些测试应当失败。


def test_minirag_parity_path_counter_weights_answer_hits_and_edge_votes() -> None:
    """验证 MiniRAG path2chunk Counter 评分：answer_type_hit_count 和 edge_vote_count
    参与计算，而非旧线性权重。"""

    class ParityRelationshipIndex(RecordingRelationshipIndex):
        def query_relationships(
            self,
            query: str,
            answer_type_keywords: list[str],
            top_k: int,
        ) -> list[MiniRelationshipCandidate]:
            self.calls.append((query, tuple(answer_type_keywords)))
            return [
                MiniRelationshipCandidate(
                    relation=RelationEvidence(
                        relation_id="relation_vote",
                        document_id="doc1",
                        source_entity_id="entity_minirag",
                        target_entity_id="entity_sources",
                        source_entity_name="MiniRAG",
                        target_entity_name="Sources",
                        description="MiniRAG uses edge votes.",
                        keywords=["mechanism"],
                        weight=1.0,
                        source_chunk_ids=["chunk_vote"],
                    ),
                    score=1.0,
                    matched_terms=["mechanism"],
                )
            ]

    class ParityPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_vote",
                    ["entity_minirag", "entity_sources"],
                    ["relation_vote"],
                    ["chunk_vote"],
                    answer_hit_count=1,
                    candidate_group_id="entity_minirag",
                    candidate_rank=0,
                ),
                _path(
                    "path_plain",
                    ["entity_minirag", "entity_other"],
                    ["relation_other"],
                    ["chunk_plain", "chunk_plain", "chunk_plain", "chunk_plain"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=1,
                ),
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=ParityRelationshipIndex(),
        path_expander=ParityPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    # chunk_vote 有 answer_type_hit + edge_vote，应排在 chunk_plain 前面
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_vote", "chunk_plain"]
    vote_components = result.chunks[0].metadata["source_score_components"]
    plain_components = result.chunks[1].metadata["source_score_components"]
    assert result.chunks[0].metadata["scoring_policy"] == "minirag_counter_parity"
    assert vote_components["answer_type_hit_count"] == 1.0
    assert vote_components["edge_vote_count"] == 1.0
    assert vote_components["path_chunk_base_weight"] == 3.0
    assert vote_components["minirag_counter_score"] == 6.0
    assert plain_components["minirag_counter_score"] == 4.0


def test_minirag_parity_first_candidate_multiplier_applies_per_group() -> None:
    """MiniRAG first candidate multiplier 应按候选组生效，而不是仅全局首条路径。"""

    class GroupedPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_group_a_rank_0",
                    ["entity_a", "entity_a_answer"],
                    ["relation_a"],
                    ["chunk_group_a_rank_0"],
                    candidate_group_id="entity_a",
                    candidate_rank=0,
                ),
                _path(
                    "path_group_a_rank_1",
                    ["entity_a", "entity_a_other"],
                    ["relation_a_other"],
                    ["chunk_group_a_rank_1"],
                    candidate_group_id="entity_a",
                    candidate_rank=1,
                ),
                _path(
                    "path_group_b_rank_0",
                    ["entity_b", "entity_b_answer"],
                    ["relation_b"],
                    ["chunk_group_b_rank_0"],
                    candidate_group_id="entity_b",
                    candidate_rank=0,
                ),
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=GroupedPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=3)

    assert [chunk.chunk_id for chunk in result.chunks] == [
        "chunk_group_a_rank_0",
        "chunk_group_b_rank_0",
        "chunk_group_a_rank_1",
    ]
    components = {
        chunk.chunk_id: chunk.metadata["source_score_components"]
        for chunk in result.chunks
    }
    assert components["chunk_group_a_rank_0"]["first_candidate_multiplier"] == 2.0
    assert components["chunk_group_b_rank_0"]["first_candidate_multiplier"] == 2.0
    assert components["chunk_group_a_rank_1"]["first_candidate_multiplier"] == 1.0
    assert components["chunk_group_a_rank_0"]["minirag_counter_score"] == 2.0
    assert components["chunk_group_b_rank_0"]["minirag_counter_score"] == 2.0
    assert components["chunk_group_a_rank_1"]["minirag_counter_score"] == 1.0


def test_minirag_parity_auxiliary_hit_amplifies_candidate_path() -> None:
    """验证 MiniRAG kwd2chunk 放大：辅助检索命中路径上的 chunk 时，应用
    first_candidate_multiplier 和 auxiliary_path_multiplier 放大。"""

    class TwoChunkPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_aux",
                    ["entity_minirag", "entity_sources"],
                    ["relation_minirag_sources"],
                    ["chunk_first", "chunk_second"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=0,
                )
            ]

    class FirstChunkAuxiliaryRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            return [
                RetrievedChunk(
                    chunk_id="chunk_first",
                    document_id="doc1",
                    text="first chunk hit by auxiliary retrieval",
                    score=0.99,
                    metadata={},
                )
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=TwoChunkPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=FirstChunkAuxiliaryRetriever(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert [chunk.chunk_id for chunk in result.chunks] == [
        "chunk_first",
        "chunk_second",
    ]
    first_components = result.chunks[0].metadata["source_score_components"]
    second_components = result.chunks[1].metadata["source_score_components"]
    # chunk_first 同时被辅助检索命中且排在路径首位，应获得两个放大乘数
    assert first_components["first_candidate_multiplier"] == 2.0
    assert first_components["auxiliary_path_multiplier"] == 10.0
    assert first_components["minirag_counter_score"] == 40.0
    # chunk_second 与 chunk_first 在同一路径上，共享 auxiliary_path_multiplier
    assert second_components["auxiliary_path_multiplier"] == 10.0
    assert second_components["minirag_counter_score"] == 40.0


def test_minirag_parity_auxiliary_only_chunk_does_not_flat_bonus_rank_first() -> None:
    """验证纯辅助检索命中的 chunk 不会因为固定加分而排在图路径 chunk 前面。"""

    class GraphOnlyPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_graph",
                    ["entity_minirag", "entity_sources"],
                    ["relation_minirag_sources"],
                    ["chunk_graph"],
                    answer_hit_count=0,
                )
            ]

    class AuxiliaryOnlyRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            return [
                RetrievedChunk(
                    chunk_id="chunk_aux_only",
                    document_id="doc1",
                    text="auxiliary-only chunk",
                    score=99.0,
                    metadata={},
                )
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=GraphOnlyPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=AuxiliaryOnlyRetriever(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    # 图路径 chunk 应排在纯辅助 chunk 前面，不应被辅助 chunk 的固定加分超越
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_graph"]
    assert result.source_selection is not None
    assert [source.chunk_id for source in result.source_selection.sources] == [
        "chunk_graph"
    ]


# ---------------------------------------------------------------------------
# MiniRAG mini-mode budget 语义测试
# ---------------------------------------------------------------------------


@dataclass
class BudgetRecordingEntityIndex:
    """记录 entity_texts 和 top_k，用于验证预算推导。"""

    calls: list[tuple[list[str], int]] = field(default_factory=list)

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        self.calls.append((list(entity_texts), top_k))
        return [
            MiniEntityCandidate(
                entity=EntityEvidence(
                    entity_id=f"entity_{name}",
                    document_id="doc1",
                    name=name,
                    entity_type="concept",
                    description=f"{name} entity",
                    source_chunk_ids=[f"chunk_{name}"],
                ),
                score=1.0,
                matched_terms=[name],
            )
            for name in entity_texts
        ]


@dataclass
class BudgetRecordingRelationshipIndex:
    """记录 query, keywords 和 top_k，用于验证预算推导。"""

    calls: list[tuple[str, tuple[str, ...], int]] = field(default_factory=list)

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        self.calls.append((query, tuple(answer_type_keywords), top_k))
        return [
            MiniRelationshipCandidate(
                relation=RelationEvidence(
                    relation_id="relation_1",
                    document_id="doc1",
                    source_entity_id="entity_A",
                    target_entity_id="entity_B",
                    source_entity_name="A",
                    target_entity_name="B",
                    description="test relation",
                    keywords=["mechanism"],
                    weight=1.0,
                    source_chunk_ids=["chunk_A", "chunk_B"],
                ),
                score=1.0,
                matched_terms=["mechanism"],
            )
        ]


@dataclass
class SixEntityGrounder:
    """返回 6 个实体，用于验证 query_entity_limit 截断。"""

    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=["A", "B", "C", "D", "E", "F"],
        )


@dataclass
class BudgetRecordingAuxiliaryRetriever:
    """记录 query 和 top_k，用于验证辅助检索预算推导。"""

    calls: list[tuple[str, int]] = field(default_factory=list)

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return [
            RetrievedChunk(
                chunk_id="chunk_aux",
                document_id="doc1",
                text="auxiliary result",
                score=0.7,
                metadata={},
            )
        ]


def test_budget_defaults_derive_correctly_from_mini_internal_candidate_n() -> None:
    """验证 MiniRAG mini-mode 预算语义：各阶段的 top_k 从 mini_internal_candidate_n 推导。"""
    grounder = SixEntityGrounder()
    entity_index = BudgetRecordingEntityIndex()
    relationship_index = BudgetRecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = BudgetRecordingAuxiliaryRetriever()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
    )

    # top_k=6 controls final answer contexts.
    retriever.retrieve_context("test query", top_k=6)

    # 1. 实体查询：entities_from_query 截断到 query_entity_limit=5，top_k=60
    assert len(entity_index.calls) == 1
    assert entity_index.calls[0][0] == ["A", "B", "C", "D", "E"]  # 截断到前 5 个
    assert entity_index.calls[0][1] == 60  # mini_internal_candidate_n

    # 2. 关系查询：top_k = query_entity_n * mini_internal_candidate_n = 5 * 60 = 300
    assert len(relationship_index.calls) == 1
    assert relationship_index.calls[0][2] == 300

    # 3. 辅助检索：top_k = int(mini_internal_candidate_n / 2) = int(60 / 2) = 30
    assert len(auxiliary_retriever.calls) == 1
    assert auxiliary_retriever.calls[0][1] == 30

    # default discourse_selection_k=12 controls RST / inter-chunk graph visibility.
    # 通过 source_selection.discourse_selection_k 验证
    result = retriever.retrieve_context("test query", top_k=6)
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 12


def test_default_discourse_selection_exposes_two_times_final_context_window() -> None:
    """discourse_selection_n 未显式设置时，默认 discourse 可见窗口为 2 * final context budget。"""
    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        # 不设置 discourse_selection_n
    )

    result = retriever.retrieve_context("How does MiniRAG work?", top_k=4)
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 8


def test_build_source_selection_exposes_two_times_final_context_window() -> None:
    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )
    supports = [
        SourceChunkSupport(
            chunk_id=f"chunk_{index}",
            score=float(10 - index),
            score_components={},
            supporting_entity_ids=[],
            supporting_relation_ids=[],
            supporting_path_ids=[],
            auxiliary_chunk_hit=False,
        )
        for index in range(6)
    ]

    selection = retriever._build_source_selection(supports, top_k=2)

    assert retriever.discourse_selection_k is None
    assert selection.final_context_k == 2
    assert selection.discourse_selection_k == 4
    assert [
        source.chunk_id for source in selection.sources if source.selected_for_answer
    ] == ["chunk_0", "chunk_1"]
    assert [
        source.chunk_id for source in selection.sources if source.selected_for_discourse
    ] == ["chunk_0", "chunk_1", "chunk_2", "chunk_3"]


def test_discourse_selection_n_explicit_overrides_answer_top_n() -> None:
    """显式设置 discourse_selection_n 时，应覆盖默认的 answer_top_n。"""
    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        discourse_selection_n=2,
    )

    result = retriever.retrieve_context("How does MiniRAG work?", top_k=4)
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 2


def test_budget_validation_rejects_invalid_params() -> None:
    """验证构造参数的合法性校验。"""
    from ragflow_lite.domain.errors import ProcessingError

    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()

    with pytest.raises(ProcessingError, match="mini_internal_candidate_n must be >= 1"):
        MiniGraphFirstRetriever(
            query_grounder=grounder,
            entity_index=entity_index,
            relationship_index=relationship_index,
            path_expander=path_expander,
            chunk_lookup=chunk_lookup,
            mini_internal_candidate_n=0,
        )

    with pytest.raises(ProcessingError, match="query_entity_limit must be >= 1"):
        MiniGraphFirstRetriever(
            query_grounder=grounder,
            entity_index=entity_index,
            relationship_index=relationship_index,
            path_expander=path_expander,
            chunk_lookup=chunk_lookup,
            query_entity_limit=0,
        )


def test_legacy_params_map_to_new_budget_params() -> None:
    """验证旧参数名 (grounded_entity_k 等) 仍然可用并映射到新参数。"""
    grounder = RecordingGrounder()
    entity_index = BudgetRecordingEntityIndex()
    relationship_index = BudgetRecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = BudgetRecordingAuxiliaryRetriever()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        grounded_entity_k=10,
        chunk_auxiliary_retrieval_k=5,
        discourse_selection_k=3,
    )

    result = retriever.retrieve_context("How does MiniRAG work?", top_k=2)

    # grounded_entity_k=10 应映射到 entity top_k
    assert entity_index.calls[0][1] == 10

    # chunk_auxiliary_retrieval_k=5 应映射到 auxiliary top_k
    assert auxiliary_retriever.calls[0][1] == 5

    # discourse_selection_k=3 应映射到 discourse selection
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 3


def test_explicit_chunk_auxiliary_candidate_n_overrides_default() -> None:
    """显式设置 chunk_auxiliary_candidate_n 时，应覆盖默认的 int(mini_internal_candidate_n / 2)。"""
    grounder = RecordingGrounder()
    entity_index = RecordingEntityIndex()
    relationship_index = RecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = BudgetRecordingAuxiliaryRetriever()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        chunk_auxiliary_candidate_n=15,
    )

    retriever.retrieve_context("How does MiniRAG work?", top_k=2)
    assert auxiliary_retriever.calls[0][1] == 15


# ---------------------------------------------------------------------------
# MiniRAG 内部预算正数下限回归测试
# ---------------------------------------------------------------------------


def test_keyword_only_grounding_keeps_positive_relationship_budget() -> None:
    """当 grounding 只返回关键词、不返回实体时，关系预算应保持 >= 1。"""
    grounder = KeywordOnlyGrounder()
    entity_index = BudgetRecordingEntityIndex()
    relationship_index = BudgetRecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        mini_internal_candidate_n=7,
    )

    retriever.retrieve_context("which mechanism matters?", top_k=2)

    assert relationship_index.calls == [("which mechanism matters?", ("mechanism",), 7)]


def test_auxiliary_default_budget_is_at_least_one() -> None:
    """mini_internal_candidate_n=1 时，辅助检索默认预算 int(1/2)=0 应被提升为 1。"""
    grounder = RecordingGrounder()
    entity_index = BudgetRecordingEntityIndex()
    relationship_index = BudgetRecordingRelationshipIndex()
    path_expander = RecordingPathExpander()
    chunk_lookup = RecordingChunkLookup()
    auxiliary_retriever = BudgetRecordingAuxiliaryRetriever()

    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=entity_index,
        relationship_index=relationship_index,
        path_expander=path_expander,
        chunk_lookup=chunk_lookup,
        chunk_auxiliary_retriever=auxiliary_retriever,
        mini_internal_candidate_n=1,
    )

    retriever.retrieve_context("How does MiniRAG work?", top_k=2)

    assert auxiliary_retriever.calls[0][1] == 1


def test_minirag_parity_edge_vote_uses_endpoint_pair_when_relation_id_differs() -> None:
    """Endpoint pair vote must work when relation id canonicalization differs."""

    class PairOnlyRelationshipIndex(RecordingRelationshipIndex):
        def query_relationships(
            self,
            query: str,
            answer_type_keywords: list[str],
            top_k: int,
        ) -> list[MiniRelationshipCandidate]:
            self.calls.append((query, tuple(answer_type_keywords)))
            return [
                MiniRelationshipCandidate(
                    relation=RelationEvidence(
                        relation_id="relation_from_candidate",
                        document_id="doc1",
                        source_entity_id="entity_minirag",
                        target_entity_id="entity_sources",
                        source_entity_name="MiniRAG",
                        target_entity_name="Sources",
                        description="Endpoint pair should vote even if relation id differs.",
                        keywords=["mechanism"],
                        weight=1.0,
                        source_chunk_ids=["chunk_pair_vote"],
                    ),
                    score=1.0,
                    matched_terms=["mechanism"],
                )
            ]

    class PairPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_pair_vote",
                    ["entity_minirag", "entity_sources"],
                    ["relation_from_path"],
                    ["chunk_pair_vote"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=0,
                ),
                _path(
                    "path_plain",
                    ["entity_minirag", "entity_other"],
                    ["relation_plain"],
                    ["chunk_plain", "chunk_plain", "chunk_plain"],
                    answer_hit_count=0,
                    candidate_group_id="entity_minirag",
                    candidate_rank=1,
                ),
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=PairOnlyRelationshipIndex(),
        path_expander=PairPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert [chunk.chunk_id for chunk in result.chunks] == [
        "chunk_pair_vote",
        "chunk_plain",
    ]
    components = result.chunks[0].metadata["source_score_components"]
    assert components["edge_vote_count"] == 1.0
    assert components["path_chunk_base_weight"] == 2.0


# ---------------------------------------------------------------------------
# No-path candidate top-20% retention tests (TDD red phase — expected FAIL)
# ---------------------------------------------------------------------------


class ManyEntityIndex:
    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        return [
            MiniEntityCandidate(
                entity=EntityEvidence(
                    entity_id=f"entity_no_path_{index}",
                    document_id="doc1",
                    name=f"NoPath{index}",
                    entity_type="concept",
                    description=f"No-path entity {index}",
                    source_chunk_ids=[f"chunk_no_path_{index}"],
                ),
                score=float(10 - index),
                matched_terms=[f"NoPath{index}"],
            )
            for index in range(10)
        ] + [
            MiniEntityCandidate(
                entity=EntityEvidence(
                    entity_id="entity_with_path",
                    document_id="doc1",
                    name="WithPath",
                    entity_type="concept",
                    description="Entity with relation-backed path",
                    source_chunk_ids=["chunk_with_path_entity"],
                ),
                score=100.0,
                matched_terms=["WithPath"],
            )
        ]


def test_minirag_parity_keeps_top_20_percent_no_path_candidates() -> None:
    class RelationBackedPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return [
                _path(
                    "path_with_relation",
                    ["entity_with_path", "entity_answer"],
                    ["relation_with_path"],
                    ["chunk_with_path"],
                    candidate_group_id="entity_with_path",
                    candidate_rank=0,
                )
            ]

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=ManyEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RelationBackedPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=4)

    chunk_ids = [chunk.chunk_id for chunk in result.chunks]
    assert "chunk_with_path" in chunk_ids
    assert "chunk_no_path_0" in chunk_ids
    assert "chunk_no_path_1" in chunk_ids
    assert "chunk_no_path_2" not in chunk_ids
    no_path_chunks = [
        chunk
        for chunk in result.chunks
        if chunk.metadata["source_score_components"].get("no_path_candidate", 0.0)
    ]
    assert len(no_path_chunks) == 2
    assert {chunk.metadata["supporting_path_ids"][0] for chunk in no_path_chunks} == {
        "no_path_entity_no_path_0",
        "no_path_entity_no_path_1",
    }


def test_minirag_parity_keeps_at_least_one_no_path_candidate() -> None:
    class ThreeEntityIndex:
        def query_entities(
            self,
            entity_texts: list[str],
            top_k: int,
        ) -> list[MiniEntityCandidate]:
            return [
                MiniEntityCandidate(
                    entity=EntityEvidence(
                        entity_id=f"entity_no_path_{index}",
                        document_id="doc1",
                        name=f"NoPath{index}",
                        entity_type="concept",
                        description=f"No-path entity {index}",
                        source_chunk_ids=[f"chunk_no_path_{index}"],
                    ),
                    score=float(3 - index),
                    matched_terms=[f"NoPath{index}"],
                )
                for index in range(3)
            ]

    class EmptyPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return []

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=ThreeEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=EmptyPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=3)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_no_path_0"]
    assert result.chunks[0].metadata["supporting_path_ids"] == [
        "no_path_entity_no_path_0"
    ]


def test_discourse_selection_includes_answer_chunks_and_supplemental_chunks() -> None:
    paths = [
        _path(
            f"path_{index}",
            [f"entity_{index}", f"entity_next_{index}"],
            [f"relation_{index}"],
            [f"chunk_{index}"],
            answer_hit_count=0,
            candidate_group_id=f"entity_{index}",
            candidate_rank=index,
        )
        for index in range(5)
    ]

    class FivePathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return paths

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=FivePathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        discourse_selection_n=4,
    )

    result = retriever.retrieve_context("How does MiniRAG organize evidence?", top_k=2)

    summary = result.metadata["source_selection"]
    assert summary["selected_answer_chunk_ids"] == ["chunk_0", "chunk_1"]
    assert summary["selected_discourse_chunk_ids"] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
    ]
    assert summary["supplemental_discourse_chunk_ids"] == ["chunk_2", "chunk_3"]

    source_by_id = {
        source.chunk_id: source for source in result.source_selection.sources
    }
    assert source_by_id["chunk_0"].selected_for_answer is True
    assert source_by_id["chunk_0"].selected_for_discourse is True
    assert source_by_id["chunk_2"].selected_for_answer is False
    assert source_by_id["chunk_2"].selected_for_discourse is True
    assert source_by_id["chunk_2"].metadata["supplemental_discourse"] is True


def test_retrieve_context_keeps_supplemental_discourse_chunks_out_of_answer_contexts() -> (
    None
):
    paths = [
        _path(
            f"path_{index}",
            [f"entity_{index}", f"entity_next_{index}"],
            [f"relation_{index}"],
            [f"chunk_{index}"],
            answer_hit_count=0,
            candidate_group_id=f"entity_{index}",
            candidate_rank=index,
        )
        for index in range(4)
    ]

    class FourPathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return paths

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=FourPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        discourse_selection_n=4,
    )

    result = retriever.retrieve_context("q", top_k=2)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_0", "chunk_1"]
    supplemental = result.metadata["supplemental_discourse_chunks"]
    assert list(supplemental) == ["chunk_2", "chunk_3"]
    assert supplemental["chunk_2"].chunk_id == "chunk_2"
    assert supplemental["chunk_2"].metadata["selected_for_answer"] is False
    assert supplemental["chunk_2"].metadata["selected_for_discourse"] is True


def test_default_discourse_window_keeps_top_answer_chunks_separate_from_supplemental() -> (
    None
):
    paths = [
        _path(
            f"path_{index:02d}",
            [f"entity_{index}"],
            [f"relation_{index}"],
            [f"chunk_{index:02d}"],
            answer_hit_count=11 - index,
            candidate_group_id=f"entity_{index}",
            candidate_rank=1,
        )
        for index in range(12)
    ]

    class TwelvePathExpander(RecordingPathExpander):
        def expand_paths(
            self,
            seed_entity_ids: list[str],
            seed_relation_ids: list[str],
            max_hops: int,
        ) -> list[TopologyPath]:
            return paths

    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=TwelvePathExpander(),
        chunk_lookup=RecordingChunkLookup(),
    )

    result = retriever.retrieve_context("How does MiniRAG organize evidence?", top_k=6)

    assert [chunk.chunk_id for chunk in result.chunks] == [
        "chunk_00",
        "chunk_01",
        "chunk_02",
        "chunk_03",
        "chunk_04",
        "chunk_05",
    ]
    summary = result.metadata["source_selection"]
    assert summary["selected_answer_chunk_ids"] == [
        "chunk_00",
        "chunk_01",
        "chunk_02",
        "chunk_03",
        "chunk_04",
        "chunk_05",
    ]
    assert summary["selected_discourse_chunk_ids"] == [
        "chunk_00",
        "chunk_01",
        "chunk_02",
        "chunk_03",
        "chunk_04",
        "chunk_05",
        "chunk_06",
        "chunk_07",
        "chunk_08",
        "chunk_09",
        "chunk_10",
        "chunk_11",
    ]
    supplemental = result.metadata["supplemental_discourse_chunks"]
    assert list(supplemental) == [
        "chunk_06",
        "chunk_07",
        "chunk_08",
        "chunk_09",
        "chunk_10",
        "chunk_11",
    ]
    assert all(
        chunk.metadata["selected_for_answer"] is False
        for chunk in supplemental.values()
    )


def test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query() -> None:
    grounder = EmptyGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    rewriter = FailingCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_0"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] == "failed"
    assert rewrite["attempts"] == 2
    assert rewrite["failure_reason"] == "invalid structured output"
    assert rewrite["fallback_source"] == "initial_candidate_snapshot"


# ---------------------------------------------------------------------------
# Successful rewrite and enriched grounding tests (Task 6)
# ---------------------------------------------------------------------------


@dataclass
class SuccessfulCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=["Identify missing MiniRAG relation evidence."],
            attempts=1,
            failure_reason=None,
        )


@dataclass
class EnrichedAwareGrounder:
    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        if "Solution steps:" in query:
            return GroundedQuery(
                query=query,
                answer_type_keywords=["relation"],
                entities_from_query=["EnrichedMiniRAG"],
            )
        return GroundedQuery(
            query=query,
            answer_type_keywords=[],
            entities_from_query=[],
        )


@dataclass
class EmptyStepsCoTRewriter:
    def rewrite(self, query: str) -> CoTGroundingResult:
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=1,
            failure_reason=None,
        )


def test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass() -> (
    None
):
    grounder = EnrichedAwareGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    assert len(grounder.calls) == 2
    assert grounder.calls[0] == "ambiguous question"
    assert "Original query:" in grounder.calls[1]
    assert "ambiguous question" in grounder.calls[1]
    assert "Solution steps:" in grounder.calls[1]
    assert "Identify missing MiniRAG relation evidence." in grounder.calls[1]
    assert len(result.chunks) <= 4
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] in {"succeeded", "degraded"}
    assert rewrite["initial_candidate_count"] >= 1
    assert rewrite["enriched_candidate_count"] >= 1


def test_success_status_with_empty_steps_is_treated_as_rewrite_failure() -> None:
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    retriever = MiniGraphFirstRetriever(
        query_grounder=EmptyGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=EmptyStepsCoTRewriter(),
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert result.metadata["retrieval_rewrite"]["status"] == "failed"
    assert (
        result.metadata["retrieval_rewrite"]["fallback_source"]
        == "initial_candidate_snapshot"
    )
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]


def test_post_rewrite_gate_failure_marks_notice_without_second_rewrite() -> None:
    # EmptyGrounder ensures both initial and enriched passes yield only auxiliary
    # chunks, so the merged result still falls below the post-rewrite threshold.
    grounder = EmptyGrounder()
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=ManyAuxiliaryRetriever(chunk_count=1),
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["post_rewrite_gate_passed"] is False
    assert rewrite["answer_notice_required"] is True


def test_successful_rewrite_rebuilds_selection_metadata_for_merged_chunks() -> None:
    grounded_query = GroundedQuery(
        query="ambiguous question",
        answer_type_keywords=[],
        entities_from_query=[],
    )
    initial_chunk = RetrievedChunk(
        chunk_id="chunk_initial",
        document_id="doc1",
        text="initial chunk",
        score=5.0,
        metadata={"filename": "initial.md"},
    )
    enriched_chunk = RetrievedChunk(
        chunk_id="chunk_enriched",
        document_id="doc1",
        text="enriched chunk",
        score=4.0,
        metadata={"filename": "enriched.md"},
    )
    valid_supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental_valid",
        document_id="doc1",
        text="valid supplemental chunk",
        score=3.0,
        metadata={"filename": "supplemental.md"},
    )
    initial_result = TopologyRetrievalResult(
        query="ambiguous question",
        grounded_query=grounded_query,
        chunks=[initial_chunk],
        paths=[],
        source_selection=GraphFirstSourceSelection(
            sources=[
                GraphFirstSource(
                    chunk_id="chunk_initial",
                    rank=0,
                    score=5.0,
                    score_components={"initial": 5.0},
                    supporting_entity_ids=[],
                    supporting_relation_ids=[],
                    supporting_path_ids=[],
                    auxiliary_chunk_hit=True,
                    selected_for_answer=True,
                    selected_for_discourse=True,
                    selection_reason="initial_answer",
                ),
                GraphFirstSource(
                    chunk_id="chunk_initial_supplemental",
                    rank=1,
                    score=1.0,
                    score_components={"initial": 1.0},
                    supporting_entity_ids=[],
                    supporting_relation_ids=[],
                    supporting_path_ids=[],
                    auxiliary_chunk_hit=True,
                    selected_for_answer=False,
                    selected_for_discourse=True,
                    selection_reason="initial_discourse_only",
                    metadata={"supplemental_discourse": True},
                ),
            ],
            final_context_k=3,
            discourse_selection_k=3,
            context_token_budget=None,
            omitted_source_count=0,
        ),
        metadata={
            "retrieval_mode": "mini_graph_first",
            "source_selection": {},
            "supplemental_discourse_chunks": {},
        },
    )
    enriched_result = TopologyRetrievalResult(
        query="ambiguous question",
        grounded_query=grounded_query,
        chunks=[enriched_chunk],
        paths=[],
        source_selection=GraphFirstSourceSelection(
            sources=[
                GraphFirstSource(
                    chunk_id="chunk_enriched",
                    rank=0,
                    score=4.0,
                    score_components={"enriched": 4.0},
                    supporting_entity_ids=[],
                    supporting_relation_ids=[],
                    supporting_path_ids=[],
                    auxiliary_chunk_hit=True,
                    selected_for_answer=True,
                    selected_for_discourse=True,
                    selection_reason="enriched_answer",
                ),
                GraphFirstSource(
                    chunk_id="chunk_supplemental_valid",
                    rank=1,
                    score=3.0,
                    score_components={"enriched": 3.0},
                    supporting_entity_ids=[],
                    supporting_relation_ids=[],
                    supporting_path_ids=[],
                    auxiliary_chunk_hit=True,
                    selected_for_answer=False,
                    selected_for_discourse=True,
                    selection_reason="valid_discourse_only",
                    metadata={"supplemental_discourse": True},
                ),
                GraphFirstSource(
                    chunk_id="chunk_supplemental_stale",
                    rank=2,
                    score=2.0,
                    score_components={"enriched": 2.0},
                    supporting_entity_ids=[],
                    supporting_relation_ids=[],
                    supporting_path_ids=[],
                    auxiliary_chunk_hit=True,
                    selected_for_answer=False,
                    selected_for_discourse=True,
                    selection_reason="stale_discourse_only",
                    metadata={"supplemental_discourse": True},
                ),
            ],
            final_context_k=3,
            discourse_selection_k=3,
            context_token_budget=None,
            omitted_source_count=0,
        ),
        metadata={
            "retrieval_mode": "mini_graph_first",
            "source_selection": {},
            "supplemental_discourse_chunks": {
                "chunk_supplemental_valid": valid_supplemental_chunk
            },
        },
    )

    class ScriptedRewriteRetriever(MiniGraphFirstRetriever):
        def __init__(
            self,
            *,
            scripted_results: list[TopologyRetrievalResult],
            **kwargs: object,
        ) -> None:
            super().__init__(**kwargs)
            self.scripted_results = list(scripted_results)

        def _retrieve_context_once(
            self,
            *,
            original_query: str,
            grounding_query: str,
            auxiliary_query: str,
            top_k: int,
            discourse_selection_n: int,
        ) -> TopologyRetrievalResult:
            return self.scripted_results.pop(0)

    retriever = ScriptedRewriteRetriever(
        scripted_results=[initial_result, enriched_result],
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        cot_grounding_rewriter=SuccessfulCoTRewriter(),
        discourse_selection_k=3,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=3)

    final_chunk_ids = [chunk.chunk_id for chunk in result.chunks]
    assert final_chunk_ids == ["chunk_initial", "chunk_enriched"]
    assert result.metadata["source_selection"]["selected_answer_chunk_ids"] == (
        final_chunk_ids
    )
    assert result.metadata["source_selection"]["selected_discourse_chunk_ids"] == (
        ["chunk_initial", "chunk_enriched", "chunk_supplemental_valid"]
    )
    assert result.metadata["source_selection"]["supplemental_discourse_chunk_ids"] == [
        "chunk_supplemental_valid"
    ]
    supplemental = result.metadata["supplemental_discourse_chunks"]
    assert list(supplemental) == ["chunk_supplemental_valid"]
    assert result.source_selection is not None
    assert [source.chunk_id for source in result.source_selection.sources] == (
        ["chunk_initial", "chunk_enriched", "chunk_supplemental_valid"]
    )
    assert [
        source.chunk_id
        for source in result.source_selection.sources
        if source.selected_for_answer
    ] == final_chunk_ids
    assert [
        source.chunk_id
        for source in result.source_selection.sources
        if source.selected_for_discourse and not source.selected_for_answer
    ] == ["chunk_supplemental_valid"]
    supplemental_source = result.source_selection.sources[2]
    assert supplemental_source.metadata["supplemental_discourse"] is True
    assert result.source_selection.sources[2].rank == 2
    assert result.source_selection.sources[2].selected_for_answer is False
    assert result.source_selection.sources[2].selected_for_discourse is True
    assert "chunk_supplemental_stale" not in result.metadata["source_selection"][
        "selected_discourse_chunk_ids"
    ]
    assert "chunk_initial_supplemental" not in result.metadata["source_selection"][
        "selected_discourse_chunk_ids"
    ]
    assert "chunk_supplemental_stale" not in supplemental
    assert "chunk_initial_supplemental" not in supplemental
    assert supplemental["chunk_supplemental_valid"].metadata[
        "selected_for_answer"
    ] is False
    assert supplemental["chunk_supplemental_valid"].metadata[
        "selected_for_discourse"
    ] is True
    assert supplemental["chunk_supplemental_valid"].metadata[
        "supplemental_discourse"
    ] is True
    assert result.chunks[0].metadata["retrieval_rewrite_sources"] == ["initial"]
    assert result.chunks[1].metadata["retrieval_rewrite_sources"] == ["enriched"]

    package = EvidencePackageBuilder().build(result)
    item_by_id = {item.canonical_chunk_id: item for item in package.items}
    initial_item = item_by_id["chunk_initial"]
    supplemental_item = item_by_id["chunk_supplemental_valid"]
    assert initial_item.metadata["selected_for_answer"] is True
    assert initial_item.metadata["selected_for_discourse"] is True
    assert initial_item.metadata["source_selection_index"] == 0
    assert initial_item.metadata["retrieval_rewrite_sources"] == ["initial"]
    assert supplemental_item.metadata["selected_for_answer"] is False
    assert supplemental_item.metadata["selected_for_discourse"] is True
    assert supplemental_item.metadata["source_selection_index"] == 2
    assert supplemental_item.metadata["supplemental_discourse"] is True
    assert package.metadata["source_selection"]["selected_discourse_chunk_ids"] == [
        "chunk_initial",
        "chunk_enriched",
        "chunk_supplemental_valid",
    ]
