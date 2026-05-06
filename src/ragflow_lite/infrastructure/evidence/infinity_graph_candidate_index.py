"""Infinity 图候选索引 —— 使用 Infinity 原生 match_text + match_dense + weighted_sum 融合
查询 graph entity 和 relationship 候选。

设计要点：
- 两张 Infinity 表：graph_entities / graph_relationships
- 每张表使用 match_text + match_dense + fusion("weighted_sum") 做混合检索
- 实体查询按 entity_texts 逐条查询后按 canonical_id 合并，保留最高分
- 关系查询单次执行
- 信任 Infinity _score，不做本地二次融合
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infinity.common import ConflictType
from infinity.index import IndexInfo, IndexType

from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_fields import (
    ENTITY_MATCH_TEXT_FIELDS,
    RELATIONSHIP_MATCH_TEXT_FIELDS,
    build_entity_candidate_row,
    build_entity_embedding_text,
    build_relationship_candidate_row,
    build_relationship_embedding_text,
)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphCandidateInfinityConfig:
    """Infinity 图候选索引配置。

    Attributes:
        entity_table: 实体候选表名
        relationship_table: 关系候选表名
        graph_initial_recall_n: 底层召回数量（不随查询实体数倍增）
        text_weight: 文本分支权重
        dense_weight: 稠密向量分支权重
        minimum_should_match: 全文匹配最低比例
        dense_similarity_threshold: 稠密相似度阈值
        fusion_normalize: 融合归一化方法
    """

    entity_table: str = "graph_entities"
    relationship_table: str = "graph_relationships"
    graph_initial_recall_n: int = 1024
    text_weight: float = 0.05
    dense_weight: float = 0.95
    minimum_should_match: float = 0.3
    dense_similarity_threshold: float = 0.2
    fusion_normalize: str = "atan"


# ---------------------------------------------------------------------------
# 分数字段解析
# ---------------------------------------------------------------------------


def _entity_display_name(row: dict[str, Any], canonical_id: str) -> str:
    """从行中提取实体可读名称，缺失时回退到 canonical_id。"""
    raw_name = row.get("entity_name_kwd")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    return canonical_id


def _resolve_score(row: dict[str, Any], field_name: str = "_score") -> float:
    """从融合结果行中提取分数，兼容多种字段命名。"""
    for candidate in [field_name, "SCORE", "score", "_distance"]:
        val = row.get(candidate)
        if val is not None:
            return float(val)
    return 0.0


def _dense_knn_params(similarity_threshold: float) -> dict[str, str]:
    """Build Infinity SDK-compatible dense-match optional parameters."""
    return {"threshold": str(similarity_threshold)}


def _minimum_should_match_option(minimum_should_match: float) -> str:
    """Build Infinity fulltext option using the server's percent format."""
    return f"{int(minimum_should_match * 100)}%"


# ---------------------------------------------------------------------------
# 索引实现
# ---------------------------------------------------------------------------


class InfinityGraphCandidateIndex:
    """Infinity 图候选索引，查询实体和关系候选。"""

    def __init__(
        self,
        *,
        client: Any,
        database: str,
        embedder: Any,
        config: GraphCandidateInfinityConfig | None = None,
    ) -> None:
        self._client = client
        self._db = client.get_database(database)
        self._embedder = embedder
        self._config = config or GraphCandidateInfinityConfig()
        self._ensure_tables()

    # ------------------------------------------------------------------
    # 表管理
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """确保 graph candidate 表和全文索引存在。"""
        dimensions = self._embedding_dimensions()
        entity_columns = {
            "candidate_id": {"type": "varchar", "constraints": ["primary key"]},
            "canonical_id": {"type": "varchar"},
            "document_id": {"type": "varchar"},
            "candidate_kind": {"type": "varchar"},
            "entity_name_kwd": {"type": "varchar"},
            "entity_name_tks": {"type": "varchar"},
            "entity_type_tks": {"type": "varchar"},
            "entity_description_tks": {"type": "varchar"},
            "embedding_text": {"type": "varchar"},
            "vec": {"type": f"vector,{dimensions},float"},
            "source_chunk_ids": {"type": "varchar"},
            "metadata": {"type": "varchar"},
        }
        relationship_columns = {
            "candidate_id": {"type": "varchar", "constraints": ["primary key"]},
            "canonical_id": {"type": "varchar"},
            "document_id": {"type": "varchar"},
            "candidate_kind": {"type": "varchar"},
            "source_entity_id": {"type": "varchar"},
            "target_entity_id": {"type": "varchar"},
            "source_entity_name": {"type": "varchar"},
            "target_entity_name": {"type": "varchar"},
            "relationship_endpoint_kwd": {"type": "varchar"},
            "relationship_endpoint_tks": {"type": "varchar"},
            "relationship_keyword_tks": {"type": "varchar"},
            "relationship_description_tks": {"type": "varchar"},
            "embedding_text": {"type": "varchar"},
            "vec": {"type": f"vector,{dimensions},float"},
            "keywords": {"type": "varchar"},
            "weight": {"type": "float"},
            "source_chunk_ids": {"type": "varchar"},
            "metadata": {"type": "varchar"},
        }
        self._db.create_table(
            self._config.entity_table,
            entity_columns,
            ConflictType.Ignore,
        )
        self._db.create_table(
            self._config.relationship_table,
            relationship_columns,
            ConflictType.Ignore,
        )
        self._ensure_fulltext_indexes(
            self._config.entity_table,
            [
                "entity_name_kwd",
                "entity_name_tks",
                "entity_type_tks",
                "entity_description_tks",
            ],
        )
        self._ensure_fulltext_indexes(
            self._config.relationship_table,
            [
                "relationship_endpoint_kwd",
                "relationship_endpoint_tks",
                "relationship_keyword_tks",
                "relationship_description_tks",
            ],
        )

    def _embedding_dimensions(self) -> int:
        signature = getattr(self._embedder, "signature", None)
        if isinstance(signature, dict):
            dimensions = signature.get("dimensions")
            if dimensions is not None:
                return int(dimensions)
        dimensions = getattr(self._embedder, "dimensions", None)
        if dimensions is not None:
            return int(dimensions)
        dim = getattr(self._embedder, "dim", None)
        if dim is not None:
            return int(dim)
        raise RuntimeError(
            "Graph candidate Infinity tables require an embedder with "
            "signature['dimensions'], dimensions, or dim."
        )

    def _ensure_fulltext_indexes(self, table_name: str, columns: list[str]) -> None:
        table = self._db.get_table(table_name)
        existing_indexes = self._list_index_names(table)
        for column in columns:
            index_name = f"{table_name}_{column}_fulltext_idx"
            if index_name in existing_indexes:
                continue
            table.create_index(
                index_name,
                IndexInfo(column, IndexType.FullText),
                ConflictType.Ignore,
            )

    def _list_index_names(self, table: Any) -> set[str]:
        list_indexes = getattr(table, "list_indexes", None)
        if not callable(list_indexes):
            return set()

        response = list_indexes()
        if response is None:
            return set()
        if isinstance(response, tuple):
            response = response[0]

        names = getattr(response, "index_names", None)
        if names is None and isinstance(response, dict):
            names = response.get("index_names")
        if names is None:
            return set()
        return {str(name) for name in names}

    # ------------------------------------------------------------------
    # 实体查询
    # ------------------------------------------------------------------

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        """按每个查询实体文本独立查询，再按 canonical_id 合并。

        Args:
            entity_texts: 查询实体文本列表（来自 query grounding）
            top_k: 最终返回的最大候选数

        Returns:
            合并后的候选实体列表，按分数降序排列
        """
        if not entity_texts:
            return []

        # 按 canonical_id 合并结果
        merged: dict[str, dict[str, Any]] = {}

        for entity_text in entity_texts:
            # 1. 嵌入查询文本
            query_vector = self._embedder.embed_query(entity_text)

            # 2. 获取实体表并执行融合查询
            table = self._db.get_table(self._config.entity_table)
            recall_n = self._config.graph_initial_recall_n

            df, _extra = (
                table.match_text(
                    fields=",".join(ENTITY_MATCH_TEXT_FIELDS),
                    matching_text=entity_text,
                    topn=recall_n,
                    extra_options={
                        "minimum_should_match": _minimum_should_match_option(
                            self._config.minimum_should_match
                        ),
                    },
                )
                .match_dense(
                    vector_column_name="vec",
                    embedding_data=query_vector,
                    embedding_data_type="float",
                    distance_type="ip",
                    topn=recall_n,
                    knn_params=_dense_knn_params(
                        self._config.dense_similarity_threshold
                    ),
                )
                .fusion(
                    "weighted_sum",
                    topn=recall_n,
                    fusion_params={
                        "weights": f"{self._config.text_weight},{self._config.dense_weight}",
                        "normalize": self._config.fusion_normalize,
                    },
                )
                .output(
                    [
                        "candidate_id",
                        "canonical_id",
                        "document_id",
                        "entity_name_kwd",
                        "source_chunk_ids",
                        "metadata",
                        "_score",
                    ]
                )
                .to_pl()
            )

            if df.is_empty():
                continue

            # 3. 遍历当前查询结果，合并到全局 merged
            for row_dict in df.iter_rows(named=True):
                canonical_id = str(row_dict.get("canonical_id", ""))
                if not canonical_id:
                    continue

                score = _resolve_score(row_dict)
                candidate_id = str(row_dict.get("candidate_id", canonical_id))

                if canonical_id in merged:
                    existing = merged[canonical_id]
                    # 保留最高分
                    if score > existing["score"]:
                        existing["score"] = score
                        existing["best_row"] = row_dict
                        existing["matched_query_entity"] = entity_text
                    # 收集 member candidate IDs
                    existing["member_candidate_ids"].add(candidate_id)
                else:
                    merged[canonical_id] = {
                        "canonical_id": canonical_id,
                        "score": score,
                        "best_row": row_dict,
                        "member_candidate_ids": {candidate_id},
                        "matched_query_entity": entity_text,
                    }

        # 4. 转换为 MiniEntityCandidate 并按分数截断
        candidates = []
        for entry in merged.values():
            row = entry["best_row"]
            canonical_id = entry["canonical_id"]
            score = entry["score"]
            candidate_id = str(row.get("candidate_id", canonical_id))

            # 构建合并后的 metadata
            merged_metadata: dict[str, Any] = {
                "retrieval_mode": "graph_candidate_infinity_hybrid",
                "candidate_kind": "entity",
                "candidate_id": candidate_id,
                "canonical_id": canonical_id,
                "score": score,
                "fusion_method": "weighted_sum",
                "fusion_weights": {
                    "text": self._config.text_weight,
                    "dense": self._config.dense_weight,
                },
                "minimum_should_match": self._config.minimum_should_match,
                "dense_similarity_threshold": self._config.dense_similarity_threshold,
                "graph_initial_recall_n": self._config.graph_initial_recall_n,
                "field_boosts": ENTITY_MATCH_TEXT_FIELDS,
                "matched_query_entity": entry["matched_query_entity"],
                "member_candidate_ids": sorted(entry["member_candidate_ids"]),
            }

            candidate = MiniEntityCandidate(
                entity=EntityEvidence(
                    entity_id=canonical_id,
                    document_id=str(row.get("document_id", "")),
                    name=_entity_display_name(row, canonical_id),
                    entity_type="",
                    description="",
                    source_chunk_ids=list(row.get("source_chunk_ids") or []),
                    metadata=merged_metadata,
                ),
                score=score,
                matched_terms=[],
                metadata=merged_metadata,
            )
            candidates.append(candidate)

        # 按分数降序排序
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    # ------------------------------------------------------------------
    # 关系查询
    # ------------------------------------------------------------------

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        """查询关系候选，使用原始 query 做嵌入和文本匹配。

        Args:
            query: 原始查询文本
            answer_type_keywords: 答案类型关键词（用于辅助匹配）
            top_k: 返回的最大候选数

        Returns:
            关系候选列表，按分数降序排列
        """
        # 1. 嵌入原始查询
        query_vector = self._embedder.embed_query(query)

        # 2. 构建文本匹配查询：原始 query + answer_type_keywords
        #    将关键词拼接到查询文本中增强匹配
        matching_text = query
        if answer_type_keywords:
            matching_text = f"{query} {' '.join(answer_type_keywords)}"

        # 3. 获取关系表并执行融合查询
        table = self._db.get_table(self._config.relationship_table)
        recall_n = self._config.graph_initial_recall_n

        df, _extra = (
            table.match_text(
                fields=",".join(RELATIONSHIP_MATCH_TEXT_FIELDS),
                matching_text=matching_text,
                topn=recall_n,
                extra_options={
                    "minimum_should_match": _minimum_should_match_option(
                        self._config.minimum_should_match
                    ),
                },
            )
            .match_dense(
                vector_column_name="vec",
                embedding_data=query_vector,
                embedding_data_type="float",
                distance_type="ip",
                topn=recall_n,
                knn_params=_dense_knn_params(self._config.dense_similarity_threshold),
            )
            .fusion(
                "weighted_sum",
                topn=recall_n,
                fusion_params={
                    "weights": f"{self._config.text_weight},{self._config.dense_weight}",
                    "normalize": self._config.fusion_normalize,
                },
            )
            .output(
                [
                    "candidate_id",
                    "canonical_id",
                    "document_id",
                    "source_chunk_ids",
                    "metadata",
                    "_score",
                ]
            )
            .to_pl()
        )

        if df.is_empty():
            return []

        # 4. 映射为 MiniRelationshipCandidate
        candidates = []
        for row_dict in df.iter_rows(named=True):
            canonical_id = str(row_dict.get("canonical_id", ""))
            if not canonical_id:
                continue

            score = _resolve_score(row_dict)
            candidate_id = str(row_dict.get("candidate_id", canonical_id))

            metadata: dict[str, Any] = {
                "retrieval_mode": "graph_candidate_infinity_hybrid",
                "candidate_kind": "relationship",
                "candidate_id": candidate_id,
                "canonical_id": canonical_id,
                "score": score,
                "fusion_method": "weighted_sum",
                "fusion_weights": {
                    "text": self._config.text_weight,
                    "dense": self._config.dense_weight,
                },
                "minimum_should_match": self._config.minimum_should_match,
                "dense_similarity_threshold": self._config.dense_similarity_threshold,
                "graph_initial_recall_n": self._config.graph_initial_recall_n,
                "field_boosts": RELATIONSHIP_MATCH_TEXT_FIELDS,
            }

            candidate = MiniRelationshipCandidate(
                relation=RelationEvidence(
                    relation_id=canonical_id,
                    document_id=str(row_dict.get("document_id", "")),
                    source_entity_id="",
                    target_entity_id="",
                    source_entity_name="",
                    target_entity_name="",
                    description="",
                    keywords=[],
                    weight=0.0,
                    source_chunk_ids=list(row_dict.get("source_chunk_ids") or []),
                    metadata=metadata,
                ),
                score=score,
                matched_terms=[],
                metadata=metadata,
            )
            candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    # ------------------------------------------------------------------
    # 行生命周期：upsert / delete
    # ------------------------------------------------------------------

    def upsert_document_evidence(self, batch: GraphEvidenceBatch) -> None:
        """插入（或替换）一个文档的全部图证据行。

        先删除该文档的旧行，再重新插入 —— upsert 语义。

        Args:
            batch: 包含实体和关系的图证据批次
        """
        # 先删除该文档的旧行
        self.delete_document(batch.document_id)

        # 构建并插入实体行
        entity_rows = [
            build_entity_candidate_row(
                entity,
                vector=self._embedder.embed_query(build_entity_embedding_text(entity)),
            )
            for entity in batch.entities
        ]

        # 构建并插入关系行
        relationship_rows = [
            build_relationship_candidate_row(
                relation,
                vector=self._embedder.embed_query(
                    build_relationship_embedding_text(relation)
                ),
            )
            for relation in batch.relations
        ]

        if entity_rows:
            self._get_table(self._config.entity_table).insert(entity_rows)
        if relationship_rows:
            self._get_table(self._config.relationship_table).insert(relationship_rows)

    def delete_document(self, document_id: str) -> None:
        """删除一个文档在两张表中的全部行。

        Args:
            document_id: 要删除的文档 ID
        """
        # 防止 SQL 注入：转义单引号
        escaped = document_id.replace("'", "\\'")
        filter_expr = f"document_id = '{escaped}'"
        self._get_table(self._config.entity_table).delete(filter_expr)
        self._get_table(self._config.relationship_table).delete(filter_expr)

    def _get_table(self, name: str) -> Any:
        """按名称获取 Infinity 表对象。"""
        return self._db.get_table(name)
