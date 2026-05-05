"""跨文档图证据规范化（canonicalize）。

将多份文档级图证据合并为一张去重 canonical 图：
- 同名实体按 normalized name 合并为一个 canonical entity
- 有向边按 (canonical source, canonical target) 合并，权重求和
- 端点实体缺失的关系跳过并计入诊断

设计原则：纯函数，无副作用，不依赖外部存储。输入排序确定性保证输出确定性。
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ragflow_lite.domain.models import EntityEvidence, RelationEvidence

# 规范化后的虚拟 document_id，标识合并产物
CANONICAL_DOCUMENT_ID = "__canonical__"

Metadata = dict[str, Any]


def normalize_canonical_text(text: str) -> str:
    """文本归一化：小写 + 去首尾空白 + 合并连续空白为单空格。

    用于实体名称的规范化键，使不同大小写/空白的同名实体能匹配。
    """
    return " ".join(text.lower().split())


def stable_canonical_id(kind: str, *parts: str) -> str:
    """基于 SHA1 的确定性 canonical id 生成。

    kind 区分 canonical_entity / canonical_relation，parts 提供唯一性输入。
    用 SHA1 而非 UUID，保证相同输入跨进程、跨运行产生相同 id，
    便于调试和幂等验证。
    """
    raw = f"{kind}:{':'.join(parts)}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _stable_union(values: list[str]) -> list[str]:
    """去重并保持首次出现顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _join_unique(values: list[str], separator: str) -> str:
    """拼接非空去重值。"""
    return separator.join(_stable_union([v for v in values if v.strip()]))


@dataclass(slots=True)
class CanonicalGraphEvidence:
    """规范化后的跨文档图证据。

    entities / relationships: 合并后的 canonical 实体和关系列表。
    entity_id_map / relation_id_map: raw id -> canonical id 映射，
        调用方可据此替换引用。
    metadata: 诊断信息（跳过计数等）。
    """

    entities: list[EntityEvidence]
    relationships: list[RelationEvidence]
    entity_id_map: dict[str, str]
    relation_id_map: dict[str, str]
    metadata: Metadata = field(default_factory=dict)


def canonicalize_graph_evidence(
    entities: list[EntityEvidence],
    relations: list[RelationEvidence],
) -> CanonicalGraphEvidence:
    """将多文档图证据合并为 canonical 图。

    步骤：
    1. 按 (normalized name, document_id, entity_id) 排序确保输入确定性。
    2. 按 normalized name 分组，每组生成一个 canonical entity。
    3. 构建 raw entity_id -> canonical entity_id 映射。
    4. 对 relations 按 (canonical source, canonical target) 分组合并，
       端点缺失的关系跳过并计入诊断。
    """
    # --- 阶段 1: 实体合并 ---

    # 排序保证跨运行确定性：先按 normalized name，再按 document_id，再按 entity_id
    sorted_entities = sorted(
        entities,
        key=lambda e: (normalize_canonical_text(e.name), e.document_id, e.entity_id),
    )

    # 按 normalized name 分组；OrderedDict 保持首次遇到时的插入顺序
    entity_groups: OrderedDict[str, list[EntityEvidence]] = OrderedDict()
    skipped_entity_count = 0
    for ent in sorted_entities:
        key = normalize_canonical_text(ent.name)
        if not key:
            skipped_entity_count += 1
            continue
        entity_groups.setdefault(key, []).append(ent)

    # 为每个分组生成 canonical entity 和 raw->canonical 映射
    canonical_entities: list[EntityEvidence] = []
    entity_id_map: dict[str, str] = {}
    # canonical entity id -> display name，用于关系阶段查找端点名称
    canonical_name_by_id: dict[str, str] = {}

    for canonical_key, members in entity_groups.items():
        # canonical entity id 由 kind + normalized name 确定性生成
        canonical_eid = stable_canonical_id("canonical_entity", canonical_key)

        # 合并成员信息：过滤空字符串后去重，保留首次出现顺序
        entity_type = _join_unique([m.entity_type for m in members], " | ")

        # description 按文档顺序去重拼接，便于追溯来源
        description = _join_unique([m.description for m in members], "\n")

        # source_chunk_ids 按成员排序顺序去重收集
        source_chunk_ids = _stable_union(
            [chunk_id for m in members for chunk_id in m.source_chunk_ids]
        )

        # member_entity_ids / source_document_ids 按排序后的成员顺序记录
        member_ids = [m.entity_id for m in members]
        source_doc_ids = [m.document_id for m in members]

        # source_entity_names: 去重后的原始名称集合（同名实体可能有不同大小写）
        source_entity_names = _stable_union([m.name for m in members])

        canonical_entity = EntityEvidence(
            entity_id=canonical_eid,
            document_id=CANONICAL_DOCUMENT_ID,
            name=members[0].name,
            entity_type=entity_type,
            description=description,
            source_chunk_ids=source_chunk_ids,
            metadata={
                "canonical": True,
                "canonical_key": canonical_key,
                "member_entity_ids": member_ids,
                "source_document_ids": source_doc_ids,
                "source_entity_names": source_entity_names,
            },
        )
        canonical_entities.append(canonical_entity)

        # 每个 raw entity_id 都映射到同一个 canonical id
        for m in members:
            entity_id_map[m.entity_id] = canonical_eid

        # 记录 canonical id -> 首个显示名称，供关系阶段使用
        canonical_name_by_id[canonical_eid] = members[0].name

    # --- 阶段 2: 关系合并 ---

    # 排序保证关系合并的确定性
    sorted_relations = sorted(
        relations,
        key=lambda r: (r.document_id, r.relation_id),
    )

    skipped_relation_count = 0
    # 按 (canonical source id, canonical target id) 元组分组
    relation_groups: OrderedDict[tuple[str, str], list[RelationEvidence]] = (
        OrderedDict()
    )

    for rel in sorted_relations:
        # 查找端点的 canonical id；缺失则跳过
        canonical_source = entity_id_map.get(rel.source_entity_id)
        canonical_target = entity_id_map.get(rel.target_entity_id)
        if canonical_source is None or canonical_target is None:
            skipped_relation_count += 1
            continue

        group_key = (canonical_source, canonical_target)
        relation_groups.setdefault(group_key, []).append(rel)

    canonical_relations: list[RelationEvidence] = []
    relation_id_map: dict[str, str] = {}

    for (source_id, target_id), members in relation_groups.items():
        # canonical relation id 由两端 canonical entity id 确定性生成
        canonical_rid = stable_canonical_id("canonical_relation", source_id, target_id)

        # 权重求和：多次观测增强可信度
        merged_weight = sum(m.weight for m in members)

        # source_chunk_ids 按成员排序顺序去重收集
        merged_chunks = _stable_union(
            [chunk_id for m in members for chunk_id in m.source_chunk_ids]
        )

        # description 按文档顺序去重拼接
        merged_descriptions = _join_unique([m.description for m in members], "\n")

        # keywords 取稳定去重并集，保持首次出现顺序
        merged_keywords = _stable_union([kw for m in members for kw in m.keywords])

        # member_relation_ids / source_document_ids 按排序后的成员顺序
        member_ids = [m.relation_id for m in members]
        source_doc_ids = [m.document_id for m in members]

        # 成员原始端点 entity id 集合，用于追溯
        member_source_entity_ids = _stable_union([m.source_entity_id for m in members])
        member_target_entity_ids = _stable_union([m.target_entity_id for m in members])

        canonical_relation = RelationEvidence(
            relation_id=canonical_rid,
            document_id=CANONICAL_DOCUMENT_ID,
            source_entity_id=source_id,
            target_entity_id=target_id,
            source_entity_name=canonical_name_by_id[source_id],
            target_entity_name=canonical_name_by_id[target_id],
            description=merged_descriptions,
            keywords=merged_keywords,
            weight=merged_weight,
            source_chunk_ids=merged_chunks,
            metadata={
                "canonical": True,
                "canonical_key": f"{source_id}->{target_id}",
                "member_relation_ids": member_ids,
                "source_document_ids": source_doc_ids,
                "member_source_entity_ids": member_source_entity_ids,
                "member_target_entity_ids": member_target_entity_ids,
            },
        )
        canonical_relations.append(canonical_relation)

        # 每个 raw relation_id 都映射到同一个 canonical id
        for m in members:
            relation_id_map[m.relation_id] = canonical_rid

    return CanonicalGraphEvidence(
        entities=canonical_entities,
        relationships=canonical_relations,
        entity_id_map=entity_id_map,
        relation_id_map=relation_id_map,
        metadata={
            "skipped_entity_count": skipped_entity_count,
            "skipped_relation_count": skipped_relation_count,
        },
    )
