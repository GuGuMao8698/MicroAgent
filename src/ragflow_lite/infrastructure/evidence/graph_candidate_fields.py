"""Graph candidate 字段构建器。

将 EntityEvidence / RelationEvidence 转换为 Infinity 图候选行，
包含字段化文本（fielded text）和查询侧字段 boost 常量。

设计要点：
- entity_description_tks 会被写入行（可被索引），但不出现在
  ENTITY_MATCH_TEXT_FIELDS 中（不参与默认文本匹配），避免长描述干扰
  精确名称/类型匹配。
- canonical_id 优先取 metadata.canonical_id（跨文档合并后的稳定 ID），
  无则回退到 entity_id / relation_id。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ragflow_lite.domain.models.entities import EntityEvidence, RelationEvidence
from ragflow_lite.infrastructure.nlp.ragflow_tokenizer import (
    tokenize as ragflow_tokenize,
)

# ---------------------------------------------------------------------------
# 查询侧字段 boost 常量
# ---------------------------------------------------------------------------

ENTITY_MATCH_TEXT_FIELDS: list[str] = [
    # 精确名称匹配权重最高
    "entity_name_kwd^30",
    "entity_name_tks^20",
    # 类型匹配仅作辅助
    "entity_type_tks^2",
]

RELATIONSHIP_MATCH_TEXT_FIELDS: list[str] = [
    # 端点实体名称精确匹配权重最高
    "relationship_endpoint_kwd^30",
    "relationship_endpoint_tks^20",
    # 关键词匹配与端点同级
    "relationship_keyword_tks^20",
    # 描述文本仅作辅助
    "relationship_description_tks^2",
]


# ---------------------------------------------------------------------------
# embedding text 构建函数
# ---------------------------------------------------------------------------


def build_entity_embedding_text(entity: EntityEvidence) -> str:
    """实体 embedding 文本：只用名称，保持语义纯粹。"""
    return entity.name


def build_relationship_embedding_text(relation: RelationEvidence) -> str:
    """关系 embedding 文本：包含 source/target/keywords/description 四段。"""
    keywords = " ".join(relation.keywords)
    return (
        f"source: {relation.source_entity_name}\n"
        f"target: {relation.target_entity_name}\n"
        f"keywords: {keywords}\n"
        f"description: {relation.description}"
    )


# ---------------------------------------------------------------------------
# 候选行构建函数
# ---------------------------------------------------------------------------


def build_entity_candidate_row(
    entity: EntityEvidence,
    *,
    vector: list[float],
    tokenize: Callable[[str], str] = ragflow_tokenize,
) -> dict[str, Any]:
    """将 EntityEvidence 转换为 Infinity entity 候选行。

    注意：entity_description_tks 写入行（可被索引），
    但不在 ENTITY_MATCH_TEXT_FIELDS 中（不参与默认匹配）。
    """
    # canonical_id 优先取 metadata 中的跨文档合并 ID
    canonical_id = str(entity.metadata.get("canonical_id") or entity.entity_id)
    return {
        "candidate_id": entity.entity_id,
        "canonical_id": canonical_id,
        "document_id": entity.document_id,
        "candidate_kind": "entity",
        "entity_name_kwd": entity.name,
        "entity_name_tks": tokenize(entity.name),
        "entity_type_tks": tokenize(entity.entity_type),
        # 描述文本被索引但不参与默认匹配
        "entity_description_tks": tokenize(entity.description),
        "embedding_text": build_entity_embedding_text(entity),
        "vec": vector,
        "source_chunk_ids": json.dumps(
            list(entity.source_chunk_ids), ensure_ascii=False
        ),
        "metadata": json.dumps(dict(entity.metadata), ensure_ascii=False),
    }


def build_relationship_candidate_row(
    relation: RelationEvidence,
    *,
    vector: list[float],
    tokenize: Callable[[str], str] = ragflow_tokenize,
) -> dict[str, Any]:
    """将 RelationEvidence 转换为 Infinity relationship 候选行。"""
    # canonical_id 优先取 metadata 中的跨文档合并 ID
    canonical_id = str(relation.metadata.get("canonical_id") or relation.relation_id)
    endpoint_text = (
        f"{relation.source_entity_name} {relation.target_entity_name}".strip()
    )
    keyword_text = " ".join(relation.keywords)
    return {
        "candidate_id": relation.relation_id,
        "canonical_id": canonical_id,
        "document_id": relation.document_id,
        "candidate_kind": "relationship",
        "source_entity_id": relation.source_entity_id,
        "target_entity_id": relation.target_entity_id,
        "source_entity_name": relation.source_entity_name,
        "target_entity_name": relation.target_entity_name,
        "relationship_endpoint_kwd": endpoint_text,
        "relationship_endpoint_tks": tokenize(endpoint_text),
        "relationship_keyword_tks": tokenize(keyword_text),
        "relationship_description_tks": tokenize(relation.description),
        "embedding_text": build_relationship_embedding_text(relation),
        "vec": vector,
        "keywords": json.dumps(list(relation.keywords), ensure_ascii=False),
        "weight": relation.weight,
        "source_chunk_ids": json.dumps(
            list(relation.source_chunk_ids), ensure_ascii=False
        ),
        "metadata": json.dumps(dict(relation.metadata), ensure_ascii=False),
    }
