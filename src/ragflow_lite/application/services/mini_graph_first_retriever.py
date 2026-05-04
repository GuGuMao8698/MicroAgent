from __future__ import annotations

from collections import Counter, defaultdict

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RetrievedChunk,
    SourceChunkSupport,
    TopologyPath,
    TopologyRetrievalResult,
)
from ragflow_lite.domain.ports.interfaces import (
    ChunkLookup,
    EntityNameIndex,
    QueryGrounder,
    ReasoningPathExpander,
    RelationshipIndex,
    Retriever,
)


class MiniGraphFirstRetriever:
    """图优先检索器 —— 先做 query grounding，再查图索引、扩展路径，最后评分与合并 chunk。

    检索流程:
        1. query grounding：提取实体与回答类型关键词
        2. 图索引查询：实体名称索引 + 关系索引
        3. 路径扩展：从种子实体/关系出发扩展拓扑路径
        4. chunk 辅助检索（可选）：纯向量/全文检索作为评分加成与兜底
        5. 源 chunk 评分与排序
    """

    def __init__(
        self,
        *,
        query_grounder: QueryGrounder,
        entity_index: EntityNameIndex,
        relationship_index: RelationshipIndex,
        path_expander: ReasoningPathExpander,
        chunk_lookup: ChunkLookup,
        chunk_auxiliary_retriever: Retriever | None = None,
        grounded_entity_k: int = 8,
        relationship_candidate_k: int = 16,
        path_hop_limit: int = 2,
        path_candidate_k: int = 24,
        chunk_auxiliary_retrieval_k: int | None = None,
        discourse_selection_k: int = 5,
        context_token_budget: int | None = None,
    ) -> None:
        if discourse_selection_k < 1:
            raise ProcessingError("discourse_selection_k must be >= 1")
        if context_token_budget is not None and context_token_budget < 1:
            raise ProcessingError("context_token_budget must be >= 1 when provided")
        self.query_grounder = query_grounder
        self.entity_index = entity_index
        self.relationship_index = relationship_index
        self.path_expander = path_expander
        self.chunk_lookup = chunk_lookup
        self.chunk_auxiliary_retriever = chunk_auxiliary_retriever
        self.grounded_entity_k = grounded_entity_k
        self.relationship_candidate_k = relationship_candidate_k
        self.path_hop_limit = path_hop_limit
        self.path_candidate_k = path_candidate_k
        self.chunk_auxiliary_retrieval_k = chunk_auxiliary_retrieval_k
        self.discourse_selection_k = discourse_selection_k
        self.context_token_budget = context_token_budget

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """仅返回检索到的 chunk 列表（不包含路径等上下文信息）。"""
        return self.retrieve_context(query, top_k).chunks

    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult:
        """完整检索流程：grounding -> 图索引 -> 路径扩展 -> 辅助 chunk -> 评分 -> 合并。"""
        _require_positive_top_k(top_k)

        # 第 1 步: query grounding —— 提取实体与回答类型关键词
        grounded_query = self.query_grounder.ground(query)

        # 如果 grounding 结果为空（既无实体也无关键词），直接走辅助检索兜底
        if (
            not grounded_query.entities_from_query
            and not grounded_query.answer_type_keywords
        ):
            return self._fallback_empty_grounding(query, grounded_query, top_k)

        # 第 2 步: 图索引查询 —— 实体名称索引 + 关系索引
        entity_candidates = self.entity_index.query_entities(
            grounded_query.entities_from_query,
            top_k=self.grounded_entity_k,
        )
        relationship_candidates = self.relationship_index.query_relationships(
            query,
            grounded_query.answer_type_keywords,
            top_k=self.relationship_candidate_k,
        )

        # 第 3 步: 路径扩展 —— 从种子实体/关系出发扩展拓扑路径
        paths = self.path_expander.expand_paths(
            seed_entity_ids=_entity_ids(entity_candidates),
            seed_relation_ids=_relation_ids(relationship_candidates),
            max_hops=self.path_hop_limit,
        )[: self.path_candidate_k]

        # 第 4 步: chunk 辅助检索（可选）—— 作为评分加成与兜底
        auxiliary_chunks = self._retrieve_auxiliary_chunks(query, top_k)

        # 第 5 步: 源 chunk 评分与排序
        supports = _score_source_chunks(
            entity_candidates=entity_candidates,
            relationship_candidates=relationship_candidates,
            paths=paths,
            auxiliary_chunks=auxiliary_chunks,
        )

        # 第 6 步: 构建 source selection —— 将评分结果转为带选择决策的结构
        selection = self._build_source_selection(supports, top_k)
        selected_chunk_ids = [
            source.chunk_id
            for source in selection.sources
            if source.selected_for_answer
        ]
        chunks = self._resolve_chunks_with_selection(
            selected_chunk_ids,
            auxiliary_chunks,
            selection,
            top_k,
        )
        return TopologyRetrievalResult(
            query=query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=paths,
            metadata={
                "retrieval_mode": "mini_graph_first",
                "source_selection": self._source_selection_summary(selection),
            },
            source_selection=selection,
        )

    def _fallback_empty_grounding(
        self,
        query: str,
        grounded_query: GroundedQuery,
        top_k: int,
    ) -> TopologyRetrievalResult:
        """grounding 为空时的兜底路径：仅依赖辅助检索。"""
        auxiliary_chunks = self._retrieve_auxiliary_chunks(query, top_k)
        # 将辅助检索 chunk 转为 SourceChunkSupport 以复用 selection 构建
        supports = [
            SourceChunkSupport(
                chunk_id=chunk.chunk_id,
                score=chunk.score,
                score_components={"auxiliary_hit": chunk.score},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=True,
            )
            for chunk in auxiliary_chunks
        ]
        selection = self._build_source_selection(
            supports,
            top_k,
            fallback_reason="empty_grounding",
        )
        # 为每个 chunk 附上 fallback 元数据
        chunks = [
            _with_fallback_metadata(chunk, "empty_grounding")
            for chunk in auxiliary_chunks[:top_k]
        ]
        return TopologyRetrievalResult(
            query=query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=[],
            metadata={
                "retrieval_mode": "mini_graph_first",
                "source_selection": self._source_selection_summary(selection),
            },
            source_selection=selection,
        )

    def _resolve_chunks_with_selection(
        self,
        selected_chunk_ids: list[str],
        auxiliary_chunks: list[RetrievedChunk],
        selection: GraphFirstSourceSelection,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """根据 source selection 解析实际 chunk，附上选择决策元数据。"""
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.chunk_lookup.get_chunks(selected_chunk_ids)
        }
        auxiliary_by_id = {chunk.chunk_id: chunk for chunk in auxiliary_chunks}
        resolved: list[RetrievedChunk] = []
        for source in selection.sources:
            if not source.selected_for_answer:
                continue
            base_chunk = chunks_by_id.get(source.chunk_id) or auxiliary_by_id.get(
                source.chunk_id
            )
            if base_chunk is None:
                continue
            resolved.append(_with_source_selection_metadata(base_chunk, source))
            if len(resolved) == top_k:
                return resolved
        # 兜底: 如果选择路径未解析到 chunk，回退到辅助检索结果
        if resolved:
            return resolved
        return [
            _with_fallback_metadata(chunk, "no_graph_source_chunks")
            for chunk in auxiliary_chunks[:top_k]
        ]

    def _retrieve_auxiliary_chunks(
        self,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """调用辅助 chunk 检索器（纯向量/全文），未配置时返回空列表。"""
        if self.chunk_auxiliary_retriever is None:
            return []
        return self.chunk_auxiliary_retriever.retrieve(query, self._auxiliary_k(top_k))

    def _auxiliary_k(self, top_k: int) -> int:
        """辅助检索的 top_k：优先使用显式配置，否则与主 top_k 一致。"""
        return self.chunk_auxiliary_retrieval_k or top_k

    def _build_source_selection(
        self,
        supports: list[SourceChunkSupport],
        top_k: int,
        fallback_reason: str | None = None,
    ) -> GraphFirstSourceSelection:
        """将评分后的 SourceChunkSupport 列表转为带选择决策的 GraphFirstSourceSelection。"""
        sources: list[GraphFirstSource] = []
        for rank, support in enumerate(supports):
            selected_for_answer = rank < top_k
            selected_for_discourse = (
                selected_for_answer and rank < self.discourse_selection_k
            )
            sources.append(
                GraphFirstSource(
                    chunk_id=support.chunk_id,
                    rank=rank,
                    score=support.score,
                    score_components=dict(support.score_components),
                    supporting_entity_ids=list(support.supporting_entity_ids),
                    supporting_relation_ids=list(support.supporting_relation_ids),
                    supporting_path_ids=list(support.supporting_path_ids),
                    auxiliary_chunk_hit=support.auxiliary_chunk_hit,
                    selected_for_answer=selected_for_answer,
                    selected_for_discourse=selected_for_discourse,
                    selection_reason=self._selection_reason(support, fallback_reason),
                    metadata=dict(support.metadata),
                )
            )
        return GraphFirstSourceSelection(
            sources=sources,
            final_context_k=top_k,
            discourse_selection_k=self.discourse_selection_k,
            # 仅记录字段，不做 token 计数强制执行；
            # 待后续 slice 引入 tokenizer 或仓库级计数策略后再强制。
            context_token_budget=self.context_token_budget,
            omitted_source_count=max(0, len(sources) - top_k),
            fallback_reason=fallback_reason,
        )

    def _selection_reason(
        self,
        support: SourceChunkSupport,
        fallback_reason: str | None,
    ) -> str:
        """根据支撑信息推断选择原因。"""
        reasons: list[str] = []
        if support.supporting_path_ids:
            reasons.append("graph_path_support")
        if support.supporting_relation_ids:
            reasons.append("graph_relation_support")
        if support.supporting_entity_ids:
            reasons.append("graph_entity_support")
        # "auxiliary_fallback" 含义：该 chunk 通过辅助检索命中，或检索器处于兜底模式；
        # 并非字面意义上的"系统发生了回退"，而是规范中用于辅助相关原因的稳定字符串。
        if support.auxiliary_chunk_hit or fallback_reason is not None:
            reasons.append("auxiliary_fallback")
        return "+".join(reasons) if reasons else "omitted_by_final_context_budget"

    def _source_selection_summary(
        self,
        selection: GraphFirstSourceSelection,
    ) -> dict[str, object]:
        """将 source selection 转为 metadata 中的摘要字典。"""
        return {
            "scoring_policy": _SCORING_POLICY,
            "final_context_k": selection.final_context_k,
            "discourse_selection_k": selection.discourse_selection_k,
            "context_token_budget": selection.context_token_budget,
            "selected_answer_chunk_ids": [
                source.chunk_id
                for source in selection.sources
                if source.selected_for_answer
            ],
            "selected_discourse_chunk_ids": [
                source.chunk_id
                for source in selection.sources
                if source.selected_for_discourse
            ],
            "omitted_source_count": selection.omitted_source_count,
            "fallback_reason": selection.fallback_reason,
        }


# ---------------------------------------------------------------------------
# MiniRAG mini-mode 评分对齐常量
# ---------------------------------------------------------------------------
_SCORING_POLICY = "minirag_counter_parity"
_MINIRAG_FIRST_CANDIDATE_MULTIPLIER = 2.0
_MINIRAG_AUXILIARY_PATH_MULTIPLIER = 10.0
_MINIRAG_PATH2CHUNK_BASE_BONUS = 1.0


def _path_answer_hit_count(path: TopologyPath) -> int:
    """从路径元数据中提取 answer_type 命中计数。"""
    raw = path.metadata.get("answer_type_hit_count", 0)
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    return 0


def _edge_vote_count(
    path: TopologyPath,
    relationship_candidates: list[MiniRelationshipCandidate],
) -> int:
    """计算路径上的关系边投票数：relation_id 匹配或相邻 entity pair 匹配。"""
    relation_ids = set(path.relation_ids)
    entity_pairs = {
        (path.entity_ids[index], path.entity_ids[index + 1])
        for index in range(max(0, len(path.entity_ids) - 1))
    }
    votes = 0
    for candidate in relationship_candidates:
        relation = candidate.relation
        if relation.relation_id in relation_ids:
            votes += 1
            continue
        if (relation.source_entity_id, relation.target_entity_id) in entity_pairs:
            votes += 1
            continue
        if (relation.target_entity_id, relation.source_entity_id) in entity_pairs:
            votes += 1
    return votes


def _path_chunk_weight(answer_hit_count: int, edge_vote_count: int) -> float:
    """路径 chunk 基础权重 = answer_hit_count + edge_vote_count + 1。"""
    return (
        float(answer_hit_count)
        + float(edge_vote_count)
        + _MINIRAG_PATH2CHUNK_BASE_BONUS
    )


def _path_candidate_rank(path: TopologyPath) -> int | None:
    raw = path.candidate_rank
    if raw is None:
        raw = path.metadata.get("candidate_rank")
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        rank = int(raw)
        return rank if rank >= 0 else None
    return None


def _first_candidate_multiplier(path: TopologyPath) -> float:
    """MiniRAG kwd2chunk first candidate multiplier：每个候选组 rank 0 为 2x。"""
    candidate_rank = _path_candidate_rank(path)
    if candidate_rank == 0:
        return _MINIRAG_FIRST_CANDIDATE_MULTIPLIER
    return 1.0


def _score_source_chunks(
    *,
    entity_candidates: list[MiniEntityCandidate],
    relationship_candidates: list[MiniRelationshipCandidate],
    paths: list[TopologyPath],
    auxiliary_chunks: list[RetrievedChunk],
) -> list[SourceChunkSupport]:
    """使用 MiniRAG mini-mode Counter/vote 语义对源 chunk 评分。"""
    auxiliary_hit_ids = {chunk.chunk_id for chunk in auxiliary_chunks}

    # Counter 聚合：chunk_id -> 累计得分
    chunk_counter: Counter[str] = Counter()
    # 每个 chunk 的评分组件明细
    chunk_components: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "minirag_counter_score": 0.0,
            "answer_type_hit_count": 0.0,
            "edge_vote_count": 0.0,
            "path_chunk_base_weight": 0.0,
            "first_candidate_multiplier": 1.0,
            "auxiliary_path_multiplier": 1.0,
            "auxiliary_chunk_hit": 0.0,
        }
    )
    supporting_entity_ids: dict[str, list[str]] = defaultdict(list)
    supporting_relation_ids: dict[str, list[str]] = defaultdict(list)
    supporting_path_ids: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        if not path.source_chunk_ids:
            continue
        answer_hit_count = _path_answer_hit_count(path)
        edge_vote_count = _edge_vote_count(path, relationship_candidates)
        path_weight = _path_chunk_weight(answer_hit_count, edge_vote_count)
        candidate_multiplier = _first_candidate_multiplier(path)
        first_chunk_id = path.source_chunk_ids[0]
        path_chunk_counts = Counter(path.source_chunk_ids)
        # 如果路径的首 chunk 命中辅助检索，整条路径获得 10x 放大
        path_auxiliary_multiplier = (
            _MINIRAG_AUXILIARY_PATH_MULTIPLIER
            if first_chunk_id in auxiliary_hit_ids
            else 1.0
        )

        for chunk_id, count in path_chunk_counts.items():
            contribution = (
                float(count)
                * path_weight
                * candidate_multiplier
                * path_auxiliary_multiplier
            )
            chunk_counter[chunk_id] += contribution
            components = chunk_components[chunk_id]
            components["minirag_counter_score"] += contribution
            components["answer_type_hit_count"] += float(answer_hit_count)
            components["edge_vote_count"] += float(edge_vote_count)
            components["path_chunk_base_weight"] += path_weight
            components["first_candidate_multiplier"] = max(
                components["first_candidate_multiplier"], candidate_multiplier
            )
            components["auxiliary_path_multiplier"] = max(
                components["auxiliary_path_multiplier"], path_auxiliary_multiplier
            )
            components["auxiliary_chunk_hit"] = (
                1.0
                if chunk_id in auxiliary_hit_ids
                else components["auxiliary_chunk_hit"]
            )
            supporting_entity_ids[chunk_id].extend(path.entity_ids)
            supporting_relation_ids[chunk_id].extend(path.relation_ids)
            supporting_path_ids[chunk_id].append(path.path_id)

    # 补充实体和关系候选的 supporting 信息
    for candidate in entity_candidates:
        for chunk_id in candidate.entity.source_chunk_ids:
            if chunk_id in chunk_counter:
                supporting_entity_ids[chunk_id].append(candidate.entity.entity_id)

    for candidate in relationship_candidates:
        for chunk_id in candidate.relation.source_chunk_ids:
            if chunk_id in chunk_counter:
                supporting_relation_ids[chunk_id].append(candidate.relation.relation_id)

    supports: list[SourceChunkSupport] = []
    for chunk_id, score in chunk_counter.items():
        components = dict(chunk_components[chunk_id])
        components["minirag_counter_score"] = float(score)
        supports.append(
            SourceChunkSupport(
                chunk_id=chunk_id,
                score=float(score),
                score_components=components,
                supporting_entity_ids=_dedupe(supporting_entity_ids.get(chunk_id, [])),
                supporting_relation_ids=_dedupe(
                    supporting_relation_ids.get(chunk_id, [])
                ),
                supporting_path_ids=_dedupe(supporting_path_ids.get(chunk_id, [])),
                auxiliary_chunk_hit=chunk_id in auxiliary_hit_ids,
                metadata={"scoring_policy": _SCORING_POLICY},
            )
        )

    # 确定性排序：score 降序，chunk_id 升序（MicroRAG 测试稳定性）
    supports.sort(key=lambda support: (-support.score, support.chunk_id))
    return supports


def _with_source_selection_metadata(
    chunk: RetrievedChunk,
    source: GraphFirstSource,
) -> RetrievedChunk:
    """将评分、支撑和选择决策信息写入 chunk 的 metadata。"""
    metadata = dict(chunk.metadata)
    # 将 source.metadata（包含 scoring_policy 等）合并进 chunk metadata
    metadata.update(source.metadata)
    metadata.update(
        {
            "retrieval_mode": "mini_graph_first",
            "source_chunk_score": source.score,
            "source_selection_rank": source.rank,
            "selected_for_answer": source.selected_for_answer,
            "selected_for_discourse": source.selected_for_discourse,
            "selection_reason": source.selection_reason,
            # 兼容旧键：下游测试仍读取 "score_components"；规范键为 "source_score_components"
            "score_components": dict(source.score_components),
            "source_score_components": dict(source.score_components),
            "supporting_entity_ids": source.supporting_entity_ids,
            "supporting_relation_ids": source.supporting_relation_ids,
            "supporting_path_ids": source.supporting_path_ids,
            "auxiliary_chunk_hit": source.auxiliary_chunk_hit,
        }
    )
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        text=chunk.text,
        score=source.score,
        metadata=metadata,
    )


def _with_fallback_metadata(
    chunk: RetrievedChunk,
    fallback_reason: str,
) -> RetrievedChunk:
    """为兜底 chunk 标记 fallback 信息。"""
    metadata = dict(chunk.metadata)
    metadata.update(
        {
            "retrieval_mode": "mini_graph_first_fallback",
            "fallback_reason": fallback_reason,
            "order_source": "chunk_auxiliary_retrieval",
        }
    )
    return RetrievedChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        text=chunk.text,
        score=chunk.score,
        metadata=metadata,
    )


def _entity_ids(candidates: list[MiniEntityCandidate]) -> list[str]:
    """从实体候选列表中提取去重的实体 ID。"""
    return _dedupe([candidate.entity.entity_id for candidate in candidates])


def _relation_ids(candidates: list[MiniRelationshipCandidate]) -> list[str]:
    """从关系候选列表中提取去重的关系 ID。"""
    return _dedupe([candidate.relation.relation_id for candidate in candidates])


def _dedupe(values: list[str]) -> list[str]:
    """保序去重。"""
    return list(dict.fromkeys(values))


def _require_positive_top_k(top_k: int) -> None:
    """校验 top_k 必须为正整数。"""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
