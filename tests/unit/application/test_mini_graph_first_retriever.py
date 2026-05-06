from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services.mini_graph_first_retriever import (
    MiniGraphFirstRetriever,
)
from ragflow_lite.domain.models import (
    EntityEvidence,
    GroundedQuery,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RelationEvidence,
    RetrievedChunk,
    TopologyPath,
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

    # top_k=6 意味着 answer_top_n=6
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

    # 4. discourse_selection_n 默认等于 answer_top_n = 6
    # 通过 source_selection.discourse_selection_k 验证
    result = retriever.retrieve_context("test query", top_k=6)
    assert result.source_selection is not None
    assert result.source_selection.discourse_selection_k == 6


def test_discourse_selection_defaults_to_answer_top_n() -> None:
    """discourse_selection_n 未显式设置时，应默认等于 answer_top_n（即 top_k）。"""
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
    assert result.source_selection.discourse_selection_k == 4


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

    with pytest.raises(ProcessingError, match="graph_initial_recall_n must be >= 1"):
        MiniGraphFirstRetriever(
            query_grounder=grounder,
            entity_index=entity_index,
            relationship_index=relationship_index,
            path_expander=path_expander,
            chunk_lookup=chunk_lookup,
            graph_initial_recall_n=0,
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
