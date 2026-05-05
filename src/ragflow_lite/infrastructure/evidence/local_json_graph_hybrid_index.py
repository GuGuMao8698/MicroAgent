"""基于本地 JSON 文文件的图证据混合索引实现。

继承 LocalJsonGraphEvidenceIndex，重写 query_entities / query_relationships
使用词法 + 稠密混合检索。expand_paths 从基类继承不变。
"""

from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import (
    MiniEntityCandidate,
    MiniRelationshipCandidate,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_scoring import (
    GraphCandidateRetrievalConfig,
    cosine_similarity,
    fuse_candidate_scores,
    score_entity_lexical,
    score_relationship_lexical,
    tokenize_query_terms,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_sidecar import (
    GraphCandidateSidecar,
    QueryEmbedder,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_evidence_index import (
    LocalJsonGraphEvidenceIndex,
)


class LocalJsonGraphEvidenceHybridIndex(LocalJsonGraphEvidenceIndex):
    """基于本地 JSON 文文件的图证据混合索引。

    扩展 LocalJsonGraphEvidenceIndex，重写 query_entities / query_relationships
    使用词法 + 稠密混合检索。expand_paths 从基类继承不变。
    """

    def __init__(
        self,
        evidence_dir: Path,
        sidecar: GraphCandidateSidecar,
        embedder: QueryEmbedder,
        config: GraphCandidateRetrievalConfig | None = None,
    ) -> None:
        # 启用 canonicalize 以跨文档合并同名实体/关系，hybrid dense 分数随之映射
        super().__init__(
            evidence_dir,
            reload_on_query=True,
            canonicalize_cross_document=True,
        )
        self.sidecar = sidecar
        self.embedder = embedder
        self.config = config or GraphCandidateRetrievalConfig()

    # ------------------------------------------------------------------
    # EntityNameIndex 混合实现
    # ------------------------------------------------------------------

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        """根据实体文本列表查询匹配的实体候选（词法 + 稠密混合）。

        步骤：
        1. 分词 entity_texts 得 query_terms
        2. 加载所有实体
        3. 词法评分
        4. 稠密评分：嵌入查询文本，与实体旁路向量计算余弦相似度
        5. 融合词法和稠密分数
        6. 取 top_k 构造 MiniEntityCandidate
        """
        # 1. 分词
        query_terms = tokenize_query_terms(entity_texts)

        # 2. 加载实体和旁路向量
        entities = self._get_entities()
        snapshot = self.sidecar.load_all()

        # 获取 raw -> canonical id 映射，用于将 sidecar 原始稠密得分映射到 canonical 候选
        canonical_graph = self._get_canonical_graph()
        entity_id_map = (
            canonical_graph.entity_id_map if canonical_graph is not None else {}
        )

        # 3. 词法评分
        lexical_scores: dict[str, float] = {}
        lexical_matched_terms: dict[str, list[str]] = {}
        for entity in entities:
            result = score_entity_lexical(entity, query_terms, self.config)
            if result.score > 0:
                lexical_scores[entity.entity_id] = result.score
                lexical_matched_terms[entity.entity_id] = result.matched_terms

        # 4. 稠密评分
        query_text = " ".join(entity_texts)
        query_vector = self.embedder.embed_query(query_text)

        dense_scores: dict[str, float] = {}
        dense_records: dict[str, str] = {}  # candidate_id -> embedding_text
        for record in snapshot.entities:
            # raw sidecar id 映射到 canonical id；未命中映射时保留原始 id（向后兼容）
            candidate_id = entity_id_map.get(record.candidate_id, record.candidate_id)
            sim = cosine_similarity(query_vector, record.vector)
            if sim >= self.config.dense_similarity_threshold:
                # 同一 canonical candidate 的多个 raw member 取最大稠密得分
                previous = dense_scores.get(candidate_id, 0.0)
                if sim >= previous:
                    dense_scores[candidate_id] = sim
                    dense_records[candidate_id] = record.embedding_text

        # 5. 融合
        fused = fuse_candidate_scores(lexical_scores, dense_scores, self.config)

        # 截断到 graph_initial_candidate_k
        fused = fused[: self.config.graph_initial_candidate_k]

        # 构建 entity_by_id 映射
        entity_by_id = {e.entity_id: e for e in entities}

        # 6. 构造 top_k 候选
        candidates: list[MiniEntityCandidate] = []
        for item in fused[:top_k]:
            entity = entity_by_id.get(item.candidate_id)
            if entity is None:
                continue

            # 确定检索来源
            retrieval_sources: list[str] = []
            if item.lexical_score > 0:
                retrieval_sources.append("lexical")
            if item.dense_score > 0:
                retrieval_sources.append("dense")

            # 收集匹配词项
            matched = lexical_matched_terms.get(item.candidate_id, [])

            # 嵌入文本
            emb_text = dense_records.get(item.candidate_id, "")

            metadata = {
                "retrieval_mode": "graph_evidence_hybrid",
                "retrieval_sources": retrieval_sources,
                "lexical_score": item.lexical_score,
                "dense_score": item.dense_score,
                "normalized_lexical_score": item.normalized_lexical_score,
                "normalized_dense_score": item.normalized_dense_score,
                "fusion_score": item.fusion_score,
                "fusion_weights": {
                    "lexical": self.config.lexical_weight,
                    "dense": self.config.dense_weight,
                },
                "minimum_should_match": self.config.minimum_should_match,
                "dense_similarity_threshold": self.config.dense_similarity_threshold,
                "embedding_text": emb_text,
                "matched_terms": matched,
                # 合并 canonical 来源信息（entity.metadata 包含 member_entity_ids 等）
                **entity.metadata,
                "canonical_id": entity.entity_id,
                "source_chunk_ids": list(entity.source_chunk_ids),
            }

            candidates.append(
                MiniEntityCandidate(
                    entity=entity,
                    score=item.fusion_score,
                    matched_terms=matched,
                    metadata=metadata,
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # RelationshipIndex 混合实现
    # ------------------------------------------------------------------

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        """根据查询和回答类型关键词查询匹配的关系候选（词法 + 稠密混合）。

        步骤：
        1. 分词 query + answer_type_keywords 得 query_terms
        2. 加载所有关系
        3. 词法评分
        4. 稠密评分：嵌入 query，与关系旁路向量计算余弦相似度
        5. 融合词法和稠密分数
        6. 取 top_k 构造 MiniRelationshipCandidate
        """
        # 1. 分词
        query_terms = tokenize_query_terms([query] + answer_type_keywords)

        # 2. 加载关系和旁路向量
        relations = self._get_relations()
        snapshot = self.sidecar.load_all()

        # 获取 raw -> canonical id 映射，用于将 sidecar 原始稠密得分映射到 canonical 候选
        canonical_graph = self._get_canonical_graph()
        relation_id_map = (
            canonical_graph.relation_id_map if canonical_graph is not None else {}
        )

        # 3. 词法评分
        lexical_scores: dict[str, float] = {}
        lexical_matched_terms: dict[str, list[str]] = {}
        for relation in relations:
            result = score_relationship_lexical(relation, query_terms, self.config)
            if result.score > 0:
                lexical_scores[relation.relation_id] = result.score
                lexical_matched_terms[relation.relation_id] = result.matched_terms

        # 4. 稠密评分：嵌入原始查询文本
        query_vector = self.embedder.embed_query(query)

        dense_scores: dict[str, float] = {}
        dense_records: dict[str, str] = {}  # candidate_id -> embedding_text
        for record in snapshot.relationships:
            # raw sidecar id 映射到 canonical id；未命中映射时保留原始 id（向后兼容）
            candidate_id = relation_id_map.get(record.candidate_id, record.candidate_id)
            sim = cosine_similarity(query_vector, record.vector)
            if sim >= self.config.dense_similarity_threshold:
                # 同一 canonical candidate 的多个 raw member 取最大稠密得分
                previous = dense_scores.get(candidate_id, 0.0)
                if sim >= previous:
                    dense_scores[candidate_id] = sim
                    dense_records[candidate_id] = record.embedding_text

        # 5. 融合
        fused = fuse_candidate_scores(lexical_scores, dense_scores, self.config)

        # 截断到 graph_initial_candidate_k
        fused = fused[: self.config.graph_initial_candidate_k]

        # 构建 relation_by_id 映射
        relation_by_id = {r.relation_id: r for r in relations}

        # 6. 构造 top_k 候选
        candidates: list[MiniRelationshipCandidate] = []
        for item in fused[:top_k]:
            relation = relation_by_id.get(item.candidate_id)
            if relation is None:
                continue

            # 确定检索来源
            retrieval_sources: list[str] = []
            if item.lexical_score > 0:
                retrieval_sources.append("lexical")
            if item.dense_score > 0:
                retrieval_sources.append("dense")

            # 收集匹配词项
            matched = lexical_matched_terms.get(item.candidate_id, [])

            # 嵌入文本
            emb_text = dense_records.get(item.candidate_id, "")

            metadata = {
                "retrieval_mode": "graph_evidence_hybrid",
                "retrieval_sources": retrieval_sources,
                "lexical_score": item.lexical_score,
                "dense_score": item.dense_score,
                "normalized_lexical_score": item.normalized_lexical_score,
                "normalized_dense_score": item.normalized_dense_score,
                "fusion_score": item.fusion_score,
                "fusion_weights": {
                    "lexical": self.config.lexical_weight,
                    "dense": self.config.dense_weight,
                },
                "minimum_should_match": self.config.minimum_should_match,
                "dense_similarity_threshold": self.config.dense_similarity_threshold,
                "embedding_text": emb_text,
                "matched_terms": matched,
                # 合并 canonical 来源信息（relation.metadata 包含 member_entity_ids 等）
                **relation.metadata,
                "canonical_id": relation.relation_id,
                "source_chunk_ids": list(relation.source_chunk_ids),
            }

            candidates.append(
                MiniRelationshipCandidate(
                    relation=relation,
                    score=item.fusion_score,
                    matched_terms=matched,
                    metadata=metadata,
                )
            )

        return candidates
