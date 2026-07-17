from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Literal

from ragflow_lite.application.services.grounded_auxiliary_query import (
    build_grounded_auxiliary_query,
)
from ragflow_lite.application.services.retrieval_rewrite import (
    assess_post_rewrite,
    build_enriched_grounding_input,
    build_retrieval_rewrite_metadata,
    decide_grounding_gate,
    merge_retrieval_results,
    render_enriched_query,
    snapshot_initial_candidates,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedAuxiliaryQuery,
    GroundedAuxiliaryResult,
    GroundedQuery,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    PsiRetrievalStatus,
    RetrievedChunk,
    SourceChunkSupport,
    TopologyPath,
    TopologyRetrievalResult,
)
from ragflow_lite.domain.ports.interfaces import (
    ChunkLookup,
    CoTGroundingRewriter,
    EntityNameIndex,
    GroundedAuxiliaryRetriever,
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
        grounded_auxiliary_retriever: GroundedAuxiliaryRetriever | None = None,
        cot_grounding_rewriter: CoTGroundingRewriter | None = None,
        mini_internal_candidate_n: int = 60,
        query_entity_limit: int = 5,
        path_hop_limit: int = 2,
        path_candidate_k: int = 24,
        chunk_auxiliary_candidate_n: int | None = None,
        discourse_selection_n: int | None = None,
        context_token_budget: int | None = None,
        allowed_build_ids: list[str] | None = None,
        # ── 向后兼容别名（旧参数名） ──
        grounded_entity_k: int | None = None,
        chunk_auxiliary_retrieval_k: int | None = None,
        discourse_selection_k: int | None = None,
    ) -> None:
        # 向后兼容：旧参数名映射到新参数
        if grounded_entity_k is not None:
            mini_internal_candidate_n = grounded_entity_k
        if chunk_auxiliary_retrieval_k is not None:
            chunk_auxiliary_candidate_n = chunk_auxiliary_retrieval_k
        if discourse_selection_k is not None:
            discourse_selection_n = discourse_selection_k

        # 参数合法性校验
        if mini_internal_candidate_n < 1:
            raise ProcessingError("mini_internal_candidate_n must be >= 1")
        if query_entity_limit < 1:
            raise ProcessingError("query_entity_limit must be >= 1")
        if discourse_selection_n is not None and discourse_selection_n < 1:
            raise ProcessingError("discourse_selection_n must be >= 1 when provided")
        if context_token_budget is not None and context_token_budget < 1:
            raise ProcessingError("context_token_budget must be >= 1 when provided")

        self.query_grounder = query_grounder
        self.entity_index = entity_index
        self.relationship_index = relationship_index
        self.path_expander = path_expander
        self.chunk_lookup = chunk_lookup
        self.chunk_auxiliary_retriever = chunk_auxiliary_retriever
        self.grounded_auxiliary_retriever = grounded_auxiliary_retriever
        self.cot_grounding_rewriter = cot_grounding_rewriter
        # MiniRAG mini-mode 预算参数
        self.mini_internal_candidate_n = mini_internal_candidate_n
        self.query_entity_limit = query_entity_limit
        self.path_hop_limit = path_hop_limit
        self.path_candidate_k = path_candidate_k
        self.chunk_auxiliary_candidate_n = chunk_auxiliary_candidate_n
        # discourse_selection_n 为 None 时默认等于 answer_top_n * 2（在 retrieve_context 中推导）
        self.discourse_selection_n = discourse_selection_n
        self.context_token_budget = context_token_budget
        self.allowed_build_ids = (
            list(allowed_build_ids) if allowed_build_ids is not None else None
        )
        # 保留旧属性名作为只读别名，避免下游引用立即断裂
        self.grounded_entity_k = self.mini_internal_candidate_n
        self.relationship_candidate_k = self.mini_internal_candidate_n
        self.chunk_auxiliary_retrieval_k = self.chunk_auxiliary_candidate_n
        self.discourse_selection_k = self.discourse_selection_n

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """仅返回检索到的 chunk 列表（不包含路径等上下文信息）。"""
        return self.retrieve_context(query, top_k).chunks

    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult:
        """完整检索流程：grounding -> 图索引 -> 路径扩展 -> 辅助 chunk -> 评分 -> 合并。

        top_k 即 answer_top_n（最终返回的 chunk 数量），
        各内部阶段的预算从 mini_internal_candidate_n 等参数推导。
        """
        _require_positive_top_k(top_k)

        # Contract reviewed 2026-05-08T12:56:51+08:00.
        # top_k is final answer context budget; default discourse visibility is 2 * top_k.
        # Do not collapse discourse_selection_n back to top_k.
        answer_top_n = top_k
        discourse_selection_n = self.discourse_selection_n or (
            answer_top_n * _DEFAULT_DISCOURSE_SELECTION_MULTIPLIER
        )

        initial_result = self._retrieve_context_once(
            original_query=query,
            grounding_query=query,
            auxiliary_query=query,
            top_k=answer_top_n,
            discourse_selection_n=discourse_selection_n,
            retrieval_pass_id="initial",
            rewrite_source="original",
        )
        if self.cot_grounding_rewriter is None:
            return initial_result

        snapshot = snapshot_initial_candidates(initial_result)
        gate = decide_grounding_gate(snapshot, requested_top_n=answer_top_n)
        if not gate.should_rewrite:
            initial_result.metadata.update(
                build_retrieval_rewrite_metadata(
                    enabled=True,
                    triggered=False,
                    strategy=None,
                    status="not_triggered",
                    gate_reason=gate.reason,
                    attempts=0,
                    failure_reason=None,
                    fallback_source=None,
                    initial_candidate_count=len(snapshot.candidates),
                    enriched_candidate_count=0,
                    post_rewrite_gate_passed=None,
                    post_rewrite_gate_reason=None,
                    answer_notice_required=False,
                )
            )
            return initial_result

        rewrite = self.cot_grounding_rewriter.rewrite(snapshot.query)
        if rewrite.status == "failed":
            initial_result.metadata.update(
                build_retrieval_rewrite_metadata(
                    enabled=True,
                    triggered=True,
                    strategy="cot_grounding",
                    status="failed",
                    gate_reason=gate.reason,
                    attempts=rewrite.attempts,
                    failure_reason=rewrite.failure_reason,
                    fallback_source="initial_candidate_snapshot",
                    initial_candidate_count=len(snapshot.candidates),
                    enriched_candidate_count=0,
                    post_rewrite_gate_passed=None,
                    post_rewrite_gate_reason=None,
                    answer_notice_required=False,
                )
            )
            return initial_result

        # Successful rewrite: build enriched grounding input, run second pass, merge.
        try:
            enriched_input = build_enriched_grounding_input(
                snapshot=snapshot, rewrite=rewrite
            )
            enriched_query = render_enriched_query(enriched_input)
        except ProcessingError as exc:
            initial_result.metadata.update(
                build_retrieval_rewrite_metadata(
                    enabled=True,
                    triggered=True,
                    strategy="cot_grounding",
                    status="failed",
                    gate_reason=gate.reason,
                    attempts=rewrite.attempts,
                    failure_reason=str(exc),
                    fallback_source="initial_candidate_snapshot",
                    initial_candidate_count=len(snapshot.candidates),
                    enriched_candidate_count=0,
                    post_rewrite_gate_passed=None,
                    post_rewrite_gate_reason=None,
                    answer_notice_required=False,
                )
            )
            return initial_result

        enriched_result = self._retrieve_context_once(
            original_query=query,
            grounding_query=enriched_query,
            auxiliary_query=enriched_query,
            top_k=answer_top_n,
            discourse_selection_n=discourse_selection_n,
            retrieval_pass_id="enriched",
            rewrite_source="enriched",
        )
        merged_chunks = merge_retrieval_results(
            initial=initial_result,
            enriched=enriched_result,
            top_k=answer_top_n,
        )
        (
            merged_chunks,
            merged_selection,
            merged_supplemental_chunks,
        ) = self._rebuild_merged_source_selection(
            merged_chunks=merged_chunks,
            initial_result=initial_result,
            enriched_result=enriched_result,
            top_k=answer_top_n,
        )

        merged_result = TopologyRetrievalResult(
            query=query,
            grounded_query=enriched_result.grounded_query,
            chunks=merged_chunks,
            paths=_merge_rewrite_paths(
                initial_result=initial_result,
                enriched_result=enriched_result,
                retained_chunk_ids={chunk.chunk_id for chunk in merged_chunks}
                | set(merged_supplemental_chunks),
                retained_path_ids=_dedupe(
                    [
                        path_id
                        for chunk in [
                            *merged_chunks,
                            *merged_supplemental_chunks.values(),
                        ]
                        for path_id in chunk.metadata.get("supporting_path_ids", [])
                        if isinstance(path_id, str)
                    ]
                ),
            ),
            source_selection=merged_selection,
            metadata={
                **dict(enriched_result.metadata),
                "auxiliary_retrieval_statuses": [
                    *initial_result.metadata.get("auxiliary_retrieval_statuses", []),
                    *enriched_result.metadata.get("auxiliary_retrieval_statuses", []),
                ],
                "source_selection": self._source_selection_summary(merged_selection),
                "supplemental_discourse_chunks": merged_supplemental_chunks,
            },
        )
        merged_snapshot = snapshot_initial_candidates(merged_result)
        assessment = assess_post_rewrite(merged_snapshot, requested_top_n=answer_top_n)
        answer_notice_required = not assessment.gate_passed
        merged_result.metadata.update(
            build_retrieval_rewrite_metadata(
                enabled=True,
                triggered=True,
                strategy="cot_grounding",
                status="succeeded" if assessment.gate_passed else "degraded",
                gate_reason=gate.reason,
                attempts=rewrite.attempts,
                failure_reason=None,
                fallback_source=None,
                initial_candidate_count=len(snapshot.candidates),
                enriched_candidate_count=len(enriched_result.chunks),
                post_rewrite_gate_passed=assessment.gate_passed,
                post_rewrite_gate_reason=assessment.reason,
                answer_notice_required=answer_notice_required,
            )
        )
        return merged_result

    def _rebuild_merged_source_selection(
        self,
        *,
        merged_chunks: list[RetrievedChunk],
        initial_result: TopologyRetrievalResult,
        enriched_result: TopologyRetrievalResult,
        top_k: int,
    ) -> tuple[
        list[RetrievedChunk],
        GraphFirstSourceSelection,
        dict[str, RetrievedChunk],
    ]:
        """重建 successful rewrite 合并结果的 source selection 与 chunk metadata。"""
        initial_source_by_chunk = _source_selection_by_chunk(initial_result)
        enriched_source_by_chunk = _source_selection_by_chunk(enriched_result)

        answer_chunk_ids = {chunk.chunk_id for chunk in merged_chunks}
        discourse_selection_k = (
            enriched_result.source_selection.discourse_selection_k
            if enriched_result.source_selection is not None
            else (
                initial_result.source_selection.discourse_selection_k
                if initial_result.source_selection is not None
                else max(top_k, len(merged_chunks))
            )
        )
        context_token_budget = (
            enriched_result.source_selection.context_token_budget
            if enriched_result.source_selection is not None
            else (
                initial_result.source_selection.context_token_budget
                if initial_result.source_selection is not None
                else None
            )
        )
        fallback_reason = (
            enriched_result.source_selection.fallback_reason
            if enriched_result.source_selection is not None
            else (
                initial_result.source_selection.fallback_reason
                if initial_result.source_selection is not None
                else None
            )
        )

        rebuilt_sources: list[GraphFirstSource] = []
        rebuilt_chunks: list[RetrievedChunk] = []
        for rank, chunk in enumerate(merged_chunks):
            previous_source = enriched_source_by_chunk.get(chunk.chunk_id)
            other_source = initial_source_by_chunk.get(chunk.chunk_id)
            rebuilt_source = _rehydrate_merged_source(
                chunk=chunk,
                previous_source=previous_source,
                other_source=other_source,
                rank=rank,
                selected_for_answer=True,
                selected_for_discourse=True,
            )
            rebuilt_sources.append(rebuilt_source)
            rebuilt_chunks.append(
                _with_source_selection_metadata(chunk, rebuilt_source)
            )

        effective_discourse_limit = max(discourse_selection_k, len(rebuilt_chunks))
        supplemental_slots = max(0, effective_discourse_limit - len(rebuilt_chunks))
        supplemental_sources, supplemental_chunks = _rebuild_valid_supplemental_sources(
            candidate_results=[
                ("enriched", enriched_result),
                ("initial", initial_result),
            ],
            answer_chunk_ids=answer_chunk_ids,
            start_rank=len(rebuilt_sources),
            max_sources=supplemental_slots,
        )
        rebuilt_sources.extend(supplemental_sources)

        selection = GraphFirstSourceSelection(
            sources=rebuilt_sources,
            final_context_k=top_k,
            discourse_selection_k=discourse_selection_k,
            context_token_budget=context_token_budget,
            omitted_source_count=max(0, len(rebuilt_sources) - top_k),
            fallback_reason=fallback_reason,
        )
        return rebuilt_chunks, selection, supplemental_chunks

    def _retrieve_context_once(
        self,
        *,
        original_query: str,
        grounding_query: str,
        auxiliary_query: str,
        top_k: int,
        discourse_selection_n: int,
        retrieval_pass_id: str,
        rewrite_source: Literal["original", "enriched"],
    ) -> TopologyRetrievalResult:
        """单次检索通路：grounding -> 图索引 -> 路径扩展 -> 辅助 chunk -> 评分 -> 合并。"""
        # 第 1 步: query grounding —— 提取实体与回答类型关键词
        grounded_query = self.query_grounder.ground(grounding_query)
        auxiliary_request = build_grounded_auxiliary_query(
            query_text=auxiliary_query,
            grounded_query=grounded_query,
            retrieval_pass_id=retrieval_pass_id,
            rewrite_source=rewrite_source,
        )

        # 如果 grounding 结果为空（既无实体也无关键词），直接走辅助检索兜底
        if (
            not grounded_query.entities_from_query
            and not grounded_query.answer_type_keywords
        ):
            return self._fallback_empty_grounding(
                original_query,
                grounded_query,
                top_k,
                discourse_selection_n,
                auxiliary_query=auxiliary_query,
                auxiliary_request=auxiliary_request,
            )

        # 第 2 步: 实体截断与预算推导
        # 截断 grounding 实体到 query_entity_limit，然后推导内部候选数量
        query_entities = grounded_query.entities_from_query[: self.query_entity_limit]
        query_entity_n = len(query_entities)
        entity_candidate_n = self.mini_internal_candidate_n
        # 关系候选预算 = 实体数 * 内部候选数（下限为 mini_internal_candidate_n）
        relationship_candidate_n = max(
            self.mini_internal_candidate_n,
            query_entity_n * self.mini_internal_candidate_n,
        )

        # 第 3 步: 图索引查询 —— 实体名称索引 + 关系索引
        if self.allowed_build_ids is None:
            entity_candidates = self.entity_index.query_entities(
                query_entities,
                top_k=entity_candidate_n,
            )
            relationship_candidates = self.relationship_index.query_relationships(
                grounding_query,
                grounded_query.answer_type_keywords,
                top_k=relationship_candidate_n,
            )
        else:
            entity_candidates = self.entity_index.query_entities(
                query_entities,
                top_k=entity_candidate_n,
                allowed_build_ids=self.allowed_build_ids,
            )
            relationship_candidates = self.relationship_index.query_relationships(
                grounding_query,
                grounded_query.answer_type_keywords,
                top_k=relationship_candidate_n,
                allowed_build_ids=self.allowed_build_ids,
            )

        # 第 4 步: 路径扩展 —— 从种子实体/关系出发扩展拓扑路径，再补充无路径候选
        relation_paths = self.path_expander.expand_paths(
            seed_entity_ids=_entity_ids(entity_candidates),
            seed_relation_ids=_relation_ids(relationship_candidates),
            max_hops=self.path_hop_limit,
        )
        paths = _merge_trimmed_no_path_candidates(
            entity_candidates,
            relation_paths,
            relationship_candidates,
        )[: self.path_candidate_k]

        # 第 5 步: chunk 辅助检索（可选）—— 作为评分加成与兜底
        auxiliary_result = self._retrieve_auxiliary_chunks(auxiliary_request, top_k)
        auxiliary_chunks = auxiliary_result.chunks

        # 第 6 步: 源 chunk 评分与排序
        supports = _score_source_chunks(
            entity_candidates=entity_candidates,
            relationship_candidates=relationship_candidates,
            paths=paths,
            auxiliary_chunks=auxiliary_chunks,
        )

        # 第 7 步: 构建 source selection —— 将评分结果转为带选择决策的结构
        selection = self._build_source_selection(
            supports, top_k, discourse_selection_n=discourse_selection_n
        )
        answer_chunk_ids = [
            source.chunk_id
            for source in selection.sources
            if source.selected_for_answer
        ]
        discourse_only_chunk_ids = [
            source.chunk_id
            for source in selection.sources
            if source.selected_for_discourse and not source.selected_for_answer
        ]
        chunks = self._resolve_chunks_with_selection(
            answer_chunk_ids,
            auxiliary_chunks,
            selection,
            top_k,
        )
        supplemental_chunks = self._resolve_supplemental_discourse_chunks(
            discourse_only_chunk_ids,
            auxiliary_chunks,
            selection,
        )
        return TopologyRetrievalResult(
            query=original_query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=paths,
            metadata={
                "retrieval_mode": "mini_graph_first",
                "source_selection": self._source_selection_summary(selection),
                "supplemental_discourse_chunks": supplemental_chunks,
                "auxiliary_retrieval_statuses": [asdict(auxiliary_result.status)],
            },
            source_selection=selection,
        )

    def _fallback_empty_grounding(
        self,
        original_query: str,
        grounded_query: GroundedQuery,
        top_k: int,
        discourse_selection_n: int | None = None,
        auxiliary_query: str | None = None,
        auxiliary_request: GroundedAuxiliaryQuery | None = None,
    ) -> TopologyRetrievalResult:
        """grounding 为空时的兜底路径：仅依赖辅助检索。"""
        request = auxiliary_request or build_grounded_auxiliary_query(
            query_text=auxiliary_query or original_query,
            grounded_query=grounded_query,
            retrieval_pass_id="initial",
            rewrite_source="original",
        )
        auxiliary_result = self._retrieve_auxiliary_chunks(request, top_k)
        auxiliary_chunks = auxiliary_result.chunks
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
            discourse_selection_n=discourse_selection_n,
        )
        # 为每个 chunk 附上 fallback 元数据
        chunks = [
            _with_fallback_metadata(chunk, "empty_grounding")
            for chunk in auxiliary_chunks[:top_k]
        ]
        auxiliary_by_id = {chunk.chunk_id: chunk for chunk in auxiliary_chunks}
        supplemental_chunks = {
            chunk.chunk_id: _with_source_selection_metadata(chunk, source)
            for source in selection.sources
            if source.selected_for_discourse and not source.selected_for_answer
            if (chunk := auxiliary_by_id.get(source.chunk_id)) is not None
        }
        return TopologyRetrievalResult(
            query=original_query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=[],
            metadata={
                "retrieval_mode": "mini_graph_first",
                "source_selection": self._source_selection_summary(selection),
                "supplemental_discourse_chunks": supplemental_chunks,
                "auxiliary_retrieval_statuses": [asdict(auxiliary_result.status)],
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

    def _resolve_supplemental_discourse_chunks(
        self,
        supplemental_chunk_ids: list[str],
        auxiliary_chunks: list[RetrievedChunk],
        selection: GraphFirstSourceSelection,
    ) -> dict[str, RetrievedChunk]:
        """解析语篇候选中未进入 answer 的补充 chunk，附上选择决策元数据。"""
        if not supplemental_chunk_ids:
            return {}
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.chunk_lookup.get_chunks(supplemental_chunk_ids)
        }
        auxiliary_by_id = {chunk.chunk_id: chunk for chunk in auxiliary_chunks}
        source_by_id = {source.chunk_id: source for source in selection.sources}
        resolved: dict[str, RetrievedChunk] = {}
        for chunk_id in supplemental_chunk_ids:
            base_chunk = chunks_by_id.get(chunk_id) or auxiliary_by_id.get(chunk_id)
            source = source_by_id.get(chunk_id)
            if base_chunk is None or source is None:
                continue
            resolved[chunk_id] = _with_source_selection_metadata(base_chunk, source)
        return resolved

    def _retrieve_auxiliary_chunks(
        self,
        request: GroundedAuxiliaryQuery,
        top_k: int,
    ) -> GroundedAuxiliaryResult:
        """调用 structured auxiliary；legacy 分支始终报告显式 fallback。"""
        auxiliary_k = self._auxiliary_k(top_k)
        if self.grounded_auxiliary_retriever is not None:
            return self.grounded_auxiliary_retriever.retrieve_grounded(
                request, auxiliary_k
            )
        if self.chunk_auxiliary_retriever is not None:
            chunks = self.chunk_auxiliary_retriever.retrieve(
                request.query_text, auxiliary_k
            )
            return GroundedAuxiliaryResult(
                chunks=chunks,
                status=PsiRetrievalStatus(
                    retrieval_pass_id=request.retrieval_pass_id,
                    rewrite_source=request.rewrite_source,
                    state="fallback",
                    stop_reason="legacy_auxiliary_used",
                    fallback_source="legacy_string_retriever",
                    returned_chunk_count=len(chunks),
                ),
            )
        return GroundedAuxiliaryResult(
            chunks=[],
            status=PsiRetrievalStatus(
                retrieval_pass_id=request.retrieval_pass_id,
                rewrite_source=request.rewrite_source,
                state="skipped",
                stop_reason="no_auxiliary_available",
                fallback_source="none",
            ),
        )

    def _auxiliary_k(self, top_k: int) -> int:
        """辅助检索的 top_k：优先使用显式配置，否则按 mini_internal_candidate_n / 2 推导。"""
        if self.chunk_auxiliary_candidate_n is not None:
            return self.chunk_auxiliary_candidate_n
        # 默认推导：mini_internal_candidate_n 的一半（保证 >= 1）
        return _at_least_one(int(self.mini_internal_candidate_n / 2))

    def _build_source_selection(
        self,
        supports: list[SourceChunkSupport],
        top_k: int,
        fallback_reason: str | None = None,
        *,
        discourse_selection_n: int | None = None,
    ) -> GraphFirstSourceSelection:
        """将评分后的 SourceChunkSupport 列表转为带选择决策的 GraphFirstSourceSelection。

        discourse_selection_n 控制语篇候选数量上限；未传入时退化为 top_k * 2。
        """
        effective_discourse_n = discourse_selection_n or (
            top_k * _DEFAULT_DISCOURSE_SELECTION_MULTIPLIER
        )
        sources: list[GraphFirstSource] = []
        for rank, support in enumerate(supports):
            selected_for_answer = rank < top_k
            selected_for_discourse = rank < effective_discourse_n
            metadata = dict(support.metadata)
            metadata["supplemental_discourse"] = (
                selected_for_discourse and not selected_for_answer
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
                    metadata=metadata,
                )
            )
        return GraphFirstSourceSelection(
            sources=sources,
            final_context_k=top_k,
            discourse_selection_k=effective_discourse_n,
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
            "supplemental_discourse_chunk_ids": [
                source.chunk_id
                for source in selection.sources
                if source.selected_for_discourse and not source.selected_for_answer
            ],
            "omitted_source_count": selection.omitted_source_count,
            "fallback_reason": selection.fallback_reason,
        }


# ---------------------------------------------------------------------------
# MiniRAG mini-mode 评分对齐常量
# ---------------------------------------------------------------------------
_SCORING_POLICY = "minirag_counter_parity"
_DEFAULT_DISCOURSE_SELECTION_MULTIPLIER = 2
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


def _positional_psi_multiplier(
    path: TopologyPath,
    auxiliary_hit_ids: set[str],
) -> float:
    distinct_chunk_ids = list(dict.fromkeys(path.source_chunk_ids))[:2]
    if not distinct_chunk_ids:
        return 1.0
    first_hit = distinct_chunk_ids[0] in auxiliary_hit_ids
    if len(distinct_chunk_ids) == 1:
        return 5.0 if first_hit else 1.0
    second_hit = distinct_chunk_ids[1] in auxiliary_hit_ids
    if first_hit and second_hit:
        return 10.0
    if first_hit:
        return 5.0
    if second_hit:
        return 2.0
    return 1.0


def _auxiliary_path_multiplier(
    path: TopologyPath,
    auxiliary_hit_ids: set[str],
    *,
    policy: str,
) -> float:
    if not path.source_chunk_ids:
        return 1.0
    if policy == "minirag_counter_parity":
        return (
            _MINIRAG_AUXILIARY_PATH_MULTIPLIER
            if path.source_chunk_ids[0] in auxiliary_hit_ids
            else 1.0
        )
    if policy == "psi_positional_5_2_10_experimental":
        if bool(path.metadata.get("no_path_candidate")):
            return 1.0
        return _positional_psi_multiplier(path, auxiliary_hit_ids)
    return 1.0


def _path_candidate_rank(path: TopologyPath) -> int | None:
    raw = path.candidate_rank
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        rank = int(raw)
        return rank if rank >= 0 else None
    return None


def _relation_backed_candidate_groups(paths: list[TopologyPath]) -> set[str]:
    """收集已有关系路径支撑的实体 ID。

    判定方式：如果路径包含 relation_ids，则该路径上所有 entity_ids 和
    candidate_group_id 都视为已覆盖。这样即使 path_expander 未设置
    candidate_group_id（如默认 RecordingPathExpander），只要实体出现在
    有关系边的路径上就不会被当作"无路径候选"重复引入。
    """
    groups: set[str] = set()
    for path in paths:
        if not path.relation_ids:
            continue
        if path.candidate_group_id:
            groups.add(path.candidate_group_id)
        for eid in path.entity_ids:
            groups.add(eid)
    return groups


def _relation_endpoint_entity_ids(
    relationship_candidates: list[MiniRelationshipCandidate],
) -> set[str]:
    """从关系候选中提取所有端点实体 ID。

    如果一个实体作为关系端点出现，说明它已被关系索引覆盖，
    不应再被当作"无路径候选"重复引入。
    """
    entity_ids: set[str] = set()
    for candidate in relationship_candidates:
        relation = candidate.relation
        if relation.source_entity_id:
            entity_ids.add(relation.source_entity_id)
        if relation.target_entity_id:
            entity_ids.add(relation.target_entity_id)
    return entity_ids


def _no_path_candidate_paths(
    entity_candidates: list[MiniEntityCandidate],
    relation_paths: list[TopologyPath],
    relationship_candidates: list[MiniRelationshipCandidate] | None = None,
) -> list[TopologyPath]:
    """为没有关系路径支撑的实体候选生成合成 TopologyPath。

    MiniRAG 的策略：先按 score 降序、path_id 升序对无路径候选排序，
    再截取前 20%（至少保留 1 个），而非与关系路径全局混合排序。
    这保证了低连通度但高相关性的实体不被关系路径淹没。

    判定"已有支撑"的依据：实体出现在某条有关系边的路径上，
    或实体是某条关系候选的端点。后者防止"实体已作为种子参与扩展
    但扩展器未返回该实体路径"的场景误生成无路径候选。
    """
    relation_backed_groups = _relation_backed_candidate_groups(relation_paths)
    # 补充：关系候选端点也视为已覆盖
    if relationship_candidates is not None:
        relation_backed_groups |= _relation_endpoint_entity_ids(relationship_candidates)
    candidates: list[TopologyPath] = []
    for rank, candidate in enumerate(entity_candidates):
        entity = candidate.entity
        if entity.entity_id in relation_backed_groups:
            continue
        if not entity.source_chunk_ids:
            continue
        candidates.append(
            TopologyPath(
                path_id=f"no_path_{entity.entity_id}",
                document_id=entity.document_id,
                entity_ids=[entity.entity_id],
                relation_ids=[],
                source_chunk_ids=list(entity.source_chunk_ids),
                score=candidate.score,
                candidate_group_id=entity.entity_id,
                candidate_rank=rank,
                metadata={
                    "hop_count": 0,
                    "no_path_candidate": True,
                    "candidate_score": candidate.score,
                    "answer_type_hit_count": 0,
                },
            )
        )
    # 内部排序后再截取：保证最高分的无路径候选优先保留
    candidates.sort(key=lambda path: (-path.score, path.path_id))
    if not candidates:
        return []
    # 至少保留 1 个，避免极端情况下所有无路径候选被丢弃
    keep_n = max(1, int(len(candidates) * 0.2))
    return candidates[:keep_n]


def _merge_trimmed_no_path_candidates(
    entity_candidates: list[MiniEntityCandidate],
    relation_paths: list[TopologyPath],
    relationship_candidates: list[MiniRelationshipCandidate] | None = None,
) -> list[TopologyPath]:
    """合并关系路径与截断后的无路径候选。关系路径保持原序在前，无路径候选追加在后。"""
    return relation_paths + _no_path_candidate_paths(
        entity_candidates, relation_paths, relationship_candidates
    )


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
    chunk_counter: defaultdict[str, float] = defaultdict(float)
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
            "no_path_candidate": 0.0,
        }
    )
    supporting_entity_ids: dict[str, list[str]] = defaultdict(list)
    supporting_relation_ids: dict[str, list[str]] = defaultdict(list)
    supporting_path_ids: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        if not path.source_chunk_ids:
            continue
        answer_hit_count = _path_answer_hit_count(path)
        no_path_candidate = bool(path.metadata.get("no_path_candidate"))
        edge_vote_count = _edge_vote_count(path, relationship_candidates)
        path_weight = _path_chunk_weight(answer_hit_count, edge_vote_count)
        candidate_multiplier = _first_candidate_multiplier(path)
        path_chunk_counts = Counter(path.source_chunk_ids)
        # 如果路径的首 chunk 命中辅助检索，整条路径获得 10x 放大
        path_auxiliary_multiplier = _auxiliary_path_multiplier(
            path,
            auxiliary_hit_ids,
            policy=_SCORING_POLICY,
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
            # 标记来自无路径候选的 chunk，供下游 score_components 识别
            if no_path_candidate:
                components["no_path_candidate"] = 1.0
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
            "source_selection_index": source.rank,
            "selected_for_answer": source.selected_for_answer,
            "selected_for_discourse": source.selected_for_discourse,
            "selection_reason": source.selection_reason,
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


def _merged_chunk_source_score(
    chunk: RetrievedChunk,
    source: GraphFirstSource | None,
) -> float:
    metadata_score = chunk.metadata.get("source_chunk_score")
    if isinstance(metadata_score, (int, float)):
        return float(metadata_score)
    if source is not None:
        return source.score
    return chunk.score


def _merged_chunk_score_components(
    chunk: RetrievedChunk,
    source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
) -> dict[str, float]:
    merged: dict[str, float] = {}
    for candidate in (other_source, source):
        if candidate is not None:
            merged.update(candidate.score_components)
    metadata_components = chunk.metadata.get("source_score_components")
    if isinstance(metadata_components, dict):
        merged.update(
            {
                key: float(value)
                for key, value in metadata_components.items()
                if isinstance(key, str) and isinstance(value, (int, float))
            }
        )
    return merged


def _merged_chunk_list_metadata(
    chunk: RetrievedChunk,
    key: str,
    source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
) -> list[str]:
    merged: list[str] = []
    for candidate in (source, other_source):
        if candidate is None:
            continue
        if key == "supporting_entity_ids":
            merged.extend(candidate.supporting_entity_ids)
        elif key == "supporting_relation_ids":
            merged.extend(candidate.supporting_relation_ids)
        elif key == "supporting_path_ids":
            merged.extend(candidate.supporting_path_ids)
    value = chunk.metadata.get(key)
    if isinstance(value, list):
        merged.extend(item for item in value if isinstance(item, str))
    return _dedupe(merged)


def _merged_chunk_auxiliary_hit(
    chunk: RetrievedChunk,
    source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
) -> bool:
    value = chunk.metadata.get("auxiliary_chunk_hit")
    return bool(
        (isinstance(value, bool) and value)
        or (source is not None and source.auxiliary_chunk_hit)
        or (other_source is not None and other_source.auxiliary_chunk_hit)
    )


def _merged_chunk_selection_reason(
    chunk: RetrievedChunk,
    source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
) -> str:
    reasons: list[str] = []
    for candidate in (source, other_source):
        if candidate is None or not candidate.selection_reason:
            continue
        reasons.extend(
            reason.strip()
            for reason in candidate.selection_reason.split("+")
            if reason.strip()
        )
    value = chunk.metadata.get("selection_reason")
    if isinstance(value, str) and value:
        reasons.extend(reason.strip() for reason in value.split("+") if reason.strip())
    if reasons:
        return "+".join(_dedupe(reasons))
    return "retrieval_rewrite_merged_context"


def _merged_chunk_source_metadata(
    chunk: RetrievedChunk,
    source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
    *,
    selected_for_answer: bool,
    selected_for_discourse: bool,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for candidate in (other_source, source):
        if candidate is not None:
            metadata.update(candidate.metadata)
    if "scoring_policy" in chunk.metadata:
        metadata["scoring_policy"] = chunk.metadata["scoring_policy"]
    metadata["supplemental_discourse"] = (
        selected_for_discourse and not selected_for_answer
    )
    return metadata


def _rehydrate_merged_source(
    *,
    chunk: RetrievedChunk,
    previous_source: GraphFirstSource | None,
    other_source: GraphFirstSource | None,
    rank: int,
    selected_for_answer: bool,
    selected_for_discourse: bool,
) -> GraphFirstSource:
    return GraphFirstSource(
        chunk_id=chunk.chunk_id,
        rank=rank,
        score=_merged_chunk_source_score(chunk, previous_source),
        score_components=_merged_chunk_score_components(
            chunk, previous_source, other_source
        ),
        supporting_entity_ids=_merged_chunk_list_metadata(
            chunk, "supporting_entity_ids", previous_source, other_source
        ),
        supporting_relation_ids=_merged_chunk_list_metadata(
            chunk, "supporting_relation_ids", previous_source, other_source
        ),
        supporting_path_ids=_merged_chunk_list_metadata(
            chunk, "supporting_path_ids", previous_source, other_source
        ),
        auxiliary_chunk_hit=_merged_chunk_auxiliary_hit(
            chunk, previous_source, other_source
        ),
        selected_for_answer=selected_for_answer,
        selected_for_discourse=selected_for_discourse,
        selection_reason=_merged_chunk_selection_reason(
            chunk, previous_source, other_source
        ),
        metadata=_merged_chunk_source_metadata(
            chunk,
            previous_source,
            other_source,
            selected_for_answer=selected_for_answer,
            selected_for_discourse=selected_for_discourse,
        ),
    )


def _rebuild_valid_supplemental_sources(
    *,
    candidate_results: list[tuple[str, TopologyRetrievalResult]],
    answer_chunk_ids: set[str],
    start_rank: int,
    max_sources: int,
) -> tuple[list[GraphFirstSource], dict[str, RetrievedChunk]]:
    if max_sources <= 0:
        return [], {}

    rebuilt_sources: list[GraphFirstSource] = []
    rebuilt_chunks: dict[str, RetrievedChunk] = {}
    seen_chunk_ids = set(answer_chunk_ids)

    for _, result in candidate_results:
        selection = result.source_selection
        if selection is None:
            continue
        for source in selection.sources:
            if len(rebuilt_sources) >= max_sources:
                return rebuilt_sources, rebuilt_chunks
            if source.selected_for_answer or not source.selected_for_discourse:
                continue
            if source.chunk_id in seen_chunk_ids:
                continue
            base_chunk = _resolve_rebuilt_supplemental_chunk(result, source.chunk_id)
            if base_chunk is None:
                continue

            rebuilt_source = _rehydrate_merged_source(
                chunk=base_chunk,
                previous_source=source,
                other_source=None,
                rank=start_rank + len(rebuilt_sources),
                selected_for_answer=False,
                selected_for_discourse=True,
            )
            rebuilt_sources.append(rebuilt_source)
            rebuilt_chunks[source.chunk_id] = _with_source_selection_metadata(
                base_chunk, rebuilt_source
            )
            seen_chunk_ids.add(source.chunk_id)

    return rebuilt_sources, rebuilt_chunks


def _resolve_rebuilt_supplemental_chunk(
    result: TopologyRetrievalResult,
    chunk_id: str,
) -> RetrievedChunk | None:
    supplemental_chunks = result.metadata.get("supplemental_discourse_chunks", {})
    if isinstance(supplemental_chunks, dict):
        candidate = supplemental_chunks.get(chunk_id)
        if isinstance(candidate, RetrievedChunk):
            return candidate
    for chunk in result.chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    return None


def _merge_rewrite_paths(
    *,
    initial_result: TopologyRetrievalResult,
    enriched_result: TopologyRetrievalResult,
    retained_chunk_ids: set[str],
    retained_path_ids: list[str],
) -> list[TopologyPath]:
    merged_paths: list[TopologyPath] = []
    seen_path_ids: set[str] = set()
    retained_path_id_set = set(retained_path_ids)
    for result in (enriched_result, initial_result):
        for path in result.paths:
            if path.path_id in seen_path_ids:
                continue
            if (
                path.path_id not in retained_path_id_set
                and not retained_chunk_ids.intersection(path.source_chunk_ids)
            ):
                continue
            merged_paths.append(path)
            seen_path_ids.add(path.path_id)
    return merged_paths


def _source_selection_by_chunk(
    result: TopologyRetrievalResult,
) -> dict[str, GraphFirstSource]:
    if result.source_selection is None:
        return {}
    return {source.chunk_id: source for source in result.source_selection.sources}


def _entity_ids(candidates: list[MiniEntityCandidate]) -> list[str]:
    """从实体候选列表中提取去重的实体 ID。"""
    return _dedupe([candidate.entity.entity_id for candidate in candidates])


def _relation_ids(candidates: list[MiniRelationshipCandidate]) -> list[str]:
    """从关系候选列表中提取去重的关系 ID。"""
    return _dedupe([candidate.relation.relation_id for candidate in candidates])


def _dedupe(values: list[str]) -> list[str]:
    """保序去重。"""
    return list(dict.fromkeys(values))


def _at_least_one(value: int) -> int:
    """保证内部预算推导结果不小于 1。"""
    return max(1, value)


def _require_positive_top_k(top_k: int) -> None:
    """校验 top_k 必须为正整数。"""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
