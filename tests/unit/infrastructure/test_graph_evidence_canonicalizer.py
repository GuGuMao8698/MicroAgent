"""graph_evidence_canonicalizer 纯函数单元测试。

验证跨文档图证据规范化（canonicalize）的核心语义：
- 同名实体跨文档合并为一个 canonical entity
- 有向边按 canonical endpoints 合并，权重求和
- 端点实体缺失的关系跳过并计入诊断计数
- 空名实体跳过并计入诊断计数
- description / source_chunk_ids / keywords 去重
- 空 entity_type 过滤
- 关系元数据包含 canonical_key / member_source_entity_ids / member_target_entity_ids
"""

from __future__ import annotations

from ragflow_lite.domain.models import EntityEvidence, RelationEvidence
from ragflow_lite.infrastructure.evidence.graph_evidence_canonicalizer import (
    CANONICAL_DOCUMENT_ID,
    canonicalize_graph_evidence,
)

# ---------------------------------------------------------------------------
# 测试辅助工厂
# ---------------------------------------------------------------------------


def _entity(
    entity_id: str,
    document_id: str,
    name: str,
    chunk_id: str,
    *,
    entity_type: str = "concept",
    description: str = "",
) -> EntityEvidence:
    return EntityEvidence(
        entity_id=entity_id,
        document_id=document_id,
        name=name,
        entity_type=entity_type,
        description=description or f"{name} description from {document_id}.",
        source_chunk_ids=[chunk_id],
    )


def _relation(
    relation_id: str,
    document_id: str,
    source: EntityEvidence,
    target: EntityEvidence,
    chunk_id: str,
    *,
    description: str = "connects",
    weight: float = 1.0,
) -> RelationEvidence:
    return RelationEvidence(
        relation_id=relation_id,
        document_id=document_id,
        source_entity_id=source.entity_id,
        target_entity_id=target.entity_id,
        source_entity_name=source.name,
        target_entity_name=target.name,
        description=description,
        keywords=["mechanism"],
        weight=weight,
        source_chunk_ids=[chunk_id],
    )


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def test_canonicalize_merges_same_name_entities_across_documents() -> None:
    """同名实体跨文档合并为一个 canonical entity。"""
    doc_a = _entity("entity_doc_a_minirag", "doc_a", "MiniRAG", "chunk_a")
    doc_b = _entity("entity_doc_b_minirag", "doc_b", "MiniRAG", "chunk_b")

    graph = canonicalize_graph_evidence([doc_b, doc_a], [])

    assert len(graph.entities) == 1
    entity = graph.entities[0]
    assert entity.document_id == CANONICAL_DOCUMENT_ID
    assert entity.name == "MiniRAG"
    # source_chunk_ids 按排序后的成员输入顺序合并
    assert entity.source_chunk_ids == ["chunk_a", "chunk_b"]
    assert entity.metadata["canonical"] is True
    assert entity.metadata["canonical_key"] == "minirag"
    assert entity.metadata["member_entity_ids"] == [
        "entity_doc_a_minirag",
        "entity_doc_b_minirag",
    ]
    assert entity.metadata["source_document_ids"] == ["doc_a", "doc_b"]
    # source_entity_names 去重后保留
    assert entity.metadata["source_entity_names"] == ["MiniRAG"]
    assert graph.entity_id_map == {
        "entity_doc_a_minirag": entity.entity_id,
        "entity_doc_b_minirag": entity.entity_id,
    }
    # 无跳过实体
    assert graph.metadata["skipped_entity_count"] == 0


def test_canonicalize_merges_same_directed_relationship_across_documents() -> None:
    """有向边按 canonical endpoints 合并，权重求和。"""
    doc_a_source = _entity("a_minirag", "doc_a", "MiniRAG", "chunk_a")
    doc_a_target = _entity("a_sources", "doc_a", "Source Chunks", "chunk_b")
    doc_b_source = _entity("b_minirag", "doc_b", "MiniRAG", "chunk_c")
    doc_b_target = _entity("b_sources", "doc_b", "Source Chunks", "chunk_d")
    rel_a = _relation(
        "rel_a",
        "doc_a",
        doc_a_source,
        doc_a_target,
        "chunk_rel_a",
        description="MiniRAG recovers source chunks.",
        weight=1.5,
    )
    rel_b = _relation(
        "rel_b",
        "doc_b",
        doc_b_source,
        doc_b_target,
        "chunk_rel_b",
        description="MiniRAG recovers source chunks.",
        weight=2.0,
    )

    graph = canonicalize_graph_evidence(
        [doc_a_source, doc_a_target, doc_b_source, doc_b_target],
        [rel_b, rel_a],
    )

    assert len(graph.relationships) == 1
    relation = graph.relationships[0]
    assert relation.document_id == CANONICAL_DOCUMENT_ID
    assert relation.weight == 3.5
    assert relation.source_chunk_ids == ["chunk_rel_a", "chunk_rel_b"]
    assert relation.metadata["canonical"] is True
    assert relation.metadata["member_relation_ids"] == ["rel_a", "rel_b"]
    assert relation.metadata["source_document_ids"] == ["doc_a", "doc_b"]
    # 新增关系元数据字段
    assert "canonical_key" in relation.metadata
    assert "member_source_entity_ids" in relation.metadata
    assert "member_target_entity_ids" in relation.metadata
    # canonical_key 格式为 source_id->target_id
    assert "->" in relation.metadata["canonical_key"]
    # member_source/target_entity_ids 包含原始端点 id
    assert "a_minirag" in relation.metadata["member_source_entity_ids"]
    assert "b_minirag" in relation.metadata["member_source_entity_ids"]
    assert "a_sources" in relation.metadata["member_target_entity_ids"]
    assert "b_sources" in relation.metadata["member_target_entity_ids"]
    # 关系端点名称来自 canonical_name_by_id
    assert relation.source_entity_name == "MiniRAG"
    assert relation.target_entity_name == "Source Chunks"
    assert graph.relation_id_map == {
        "rel_a": relation.relation_id,
        "rel_b": relation.relation_id,
    }


def test_canonicalize_skips_relations_with_missing_endpoints() -> None:
    """端点实体缺失的关系跳过并计入诊断计数。"""
    source = _entity("source", "doc_a", "MiniRAG", "chunk_a")
    missing_target = _entity("target", "doc_a", "Source Chunks", "chunk_b")
    relation = _relation("rel_missing", "doc_a", source, missing_target, "chunk_rel")

    graph = canonicalize_graph_evidence([source], [relation])

    assert graph.relationships == []
    assert graph.relation_id_map == {}
    assert graph.metadata["skipped_relation_count"] == 1


def test_canonicalize_skips_empty_name_entities() -> None:
    """空名实体跳过并计入诊断计数。"""
    empty_a = _entity("empty_a", "doc_a", "", "chunk_a")
    empty_b = _entity("empty_b", "doc_b", "   ", "chunk_b")
    valid = _entity("valid", "doc_a", "Valid Entity", "chunk_c")

    graph = canonicalize_graph_evidence([empty_a, empty_b, valid], [])

    assert len(graph.entities) == 1
    assert graph.entities[0].name == "Valid Entity"
    # 两个空名实体被跳过
    assert graph.metadata["skipped_entity_count"] == 2
    # 空名实体不在 id map 中
    assert "empty_a" not in graph.entity_id_map
    assert "empty_b" not in graph.entity_id_map


def test_canonicalize_filters_empty_entity_types() -> None:
    """空 entity_type 在合并时被过滤。"""
    ent_a = _entity("a", "doc_a", "Foo", "ch_a", entity_type="")
    ent_b = _entity("b", "doc_b", "Foo", "ch_b", entity_type="concept")
    ent_c = _entity("c", "doc_c", "Foo", "ch_c", entity_type="")

    graph = canonicalize_graph_evidence([ent_a, ent_b, ent_c], [])

    assert len(graph.entities) == 1
    entity = graph.entities[0]
    # 空 entity_type 被过滤，只保留 "concept"
    assert entity.entity_type == "concept"


def test_canonicalize_deduplicates_descriptions() -> None:
    """重复 description 去重。"""
    ent_a = _entity("a", "doc_a", "Foo", "ch_a", description="same desc")
    ent_b = _entity("b", "doc_b", "Foo", "ch_b", description="same desc")
    ent_c = _entity("c", "doc_c", "Foo", "ch_c", description="other desc")

    graph = canonicalize_graph_evidence([ent_a, ent_b, ent_c], [])

    assert len(graph.entities) == 1
    assert graph.entities[0].description == "same desc\nother desc"


def test_canonicalize_deduplicates_source_chunk_ids() -> None:
    """重复 source_chunk_ids 跨成员去重。"""
    ent_a = _entity("a", "doc_a", "Foo", "ch_a")
    ent_a.source_chunk_ids = ["ch_1", "ch_2"]
    ent_b = _entity("b", "doc_b", "Foo", "ch_b")
    ent_b.source_chunk_ids = ["ch_2", "ch_3"]

    graph = canonicalize_graph_evidence([ent_a, ent_b], [])

    assert len(graph.entities) == 1
    assert graph.entities[0].source_chunk_ids == ["ch_1", "ch_2", "ch_3"]


def test_canonicalize_entity_source_entity_names() -> None:
    """source_entity_names 包含去重后的原始名称。"""
    ent_a = _entity("a", "doc_a", "MiniRAG", "ch_a")
    ent_b = _entity("b", "doc_b", "minirag", "ch_b")
    ent_c = _entity("c", "doc_c", "MINIRAG", "ch_c")

    graph = canonicalize_graph_evidence([ent_a, ent_b, ent_c], [])

    assert len(graph.entities) == 1
    # 名称归一化后相同，但 source_entity_names 保留不同大小写的原始名称
    assert graph.entities[0].metadata["source_entity_names"] == [
        "MiniRAG",
        "minirag",
        "MINIRAG",
    ]


def test_canonicalize_deduplicates_relation_descriptions_and_chunks() -> None:
    """关系 description 和 source_chunk_ids 去重。"""
    source = _entity("src", "doc_a", "Source", "ch_src")
    target = _entity("tgt", "doc_a", "Target", "ch_tgt")
    rel_a = _relation("r1", "doc_a", source, target, "ch_r1", description="same")
    rel_b = _relation("r2", "doc_b", source, target, "ch_r2", description="same")

    graph = canonicalize_graph_evidence([source, target], [rel_a, rel_b])

    assert len(graph.relationships) == 1
    rel = graph.relationships[0]
    # 重复 description 只出现一次
    assert rel.description == "same"
    # 两个不同的 chunk id
    assert rel.source_chunk_ids == ["ch_r1", "ch_r2"]


def test_canonical_entity_display_name_prefers_longest_original_name() -> None:
    """同一 canonical 组内，display name 选择最长的原始名称并保持确定性。

    归一化键相同（normalize 后都是 "mini rag"），但 name.strip() 长度不同：
    "Mini RAG" -> strip len 8，"Mini  RAG" -> strip len 9。
    """
    short = _entity("short", "doc_a", "Mini RAG", "chunk_a")
    long = _entity("long", "doc_b", "Mini  RAG", "chunk_b")
    graph = canonicalize_graph_evidence([short, long], [])
    assert len(graph.entities) == 1
    entity = graph.entities[0]
    assert entity.name == "Mini  RAG"
    assert entity.metadata["source_entity_names"] == [
        "Mini RAG",
        "Mini  RAG",
    ]


def test_canonical_relationship_endpoint_names_use_chosen_display_names() -> None:
    """关系端点名称使用 canonical display name（最长原始名称）。"""
    source_short = _entity("source_short", "doc_a", "Mini RAG", "chunk_a")
    source_long = _entity("source_long", "doc_b", "Mini  RAG", "chunk_b")
    target_short = _entity("target_short", "doc_a", "Source Chunks", "chunk_c")
    target_long = _entity("target_long", "doc_b", "Source  Chunks", "chunk_d")
    relation = _relation(
        "rel_1",
        "doc_b",
        source_long,
        target_long,
        "chunk_rel",
        description="Mini  RAG recovers Source  Chunks.",
    )
    graph = canonicalize_graph_evidence(
        [source_short, source_long, target_short, target_long],
        [relation],
    )
    assert len(graph.relationships) == 1
    rel = graph.relationships[0]
    assert rel.source_entity_name == "Mini  RAG"
    assert rel.target_entity_name == "Source  Chunks"
