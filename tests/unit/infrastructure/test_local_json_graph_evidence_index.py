from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_evidence_index import (
    LocalJsonGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.evidence.local_json_store import (
    LocalJsonGraphEvidenceStore,
)


def _write_batch(tmp_path) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc1",
            entities=[
                EntityEvidence(
                    entity_id="entity_minirag",
                    document_id="doc1",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval mode.",
                    source_chunk_ids=["chunk_a"],
                ),
                EntityEvidence(
                    entity_id="entity_sources",
                    document_id="doc1",
                    name="Sources",
                    entity_type="evidence",
                    description="Recovered chunks.",
                    source_chunk_ids=["chunk_b"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="relation_minirag_sources",
                    document_id="doc1",
                    source_entity_id="entity_minirag",
                    target_entity_id="entity_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Sources",
                    description="MiniRAG recovers source chunks.",
                    keywords=["mechanism"],
                    weight=1.0,
                    source_chunk_ids=["chunk_a", "chunk_b"],
                )
            ],
        )
    )


def test_local_json_graph_index_queries_entities_relationships_and_paths(
    tmp_path,
) -> None:
    _write_batch(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path)

    entity_candidates = index.query_entities(["MiniRAG"], top_k=3)
    relationship_candidates = index.query_relationships(
        "How does MiniRAG recover sources?",
        ["mechanism"],
        top_k=3,
    )
    paths = index.expand_paths(
        seed_entity_ids=[entity_candidates[0].entity.entity_id],
        seed_relation_ids=[relationship_candidates[0].relation.relation_id],
        max_hops=2,
    )

    assert [candidate.entity.entity_id for candidate in entity_candidates] == [
        "entity_minirag"
    ]
    assert [
        candidate.relation.relation_id for candidate in relationship_candidates
    ] == ["relation_minirag_sources"]
    assert paths[0].candidate_group_id == "entity_minirag"
    assert paths[0].candidate_rank == 0
    assert paths[0].source_chunk_ids == ["chunk_a", "chunk_b"]
    assert paths[0].metadata["hop_count"] == 1


def test_local_json_index_explicit_build_allowlist_is_conservative(tmp_path) -> None:
    _write_batch(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path)

    assert index.query_entities(["MiniRAG"], top_k=3, allowed_build_ids=[]) == []
    assert (
        index.query_entities(["MiniRAG"], top_k=3, allowed_build_ids=["build-1"]) == []
    )
    assert (
        index.query_relationships(
            "How does MiniRAG recover sources?",
            ["mechanism"],
            top_k=3,
            allowed_build_ids=[],
        )
        == []
    )
    assert (
        index.query_relationships(
            "How does MiniRAG recover sources?",
            ["mechanism"],
            top_k=3,
            allowed_build_ids=["build-1"],
        )
        == []
    )


# ---------------------------------------------------------------------------
# 跨文档 canonical 合并测试
# ---------------------------------------------------------------------------


def _write_cross_document_batches(tmp_path: Path) -> None:
    """写入两份文档的图证据，包含共享实体 'MiniRAG'。"""
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc_a",
            entities=[
                EntityEvidence(
                    entity_id="doc_a_alpha",
                    document_id="doc_a",
                    name="Alpha",
                    entity_type="concept",
                    description="Entry concept.",
                    source_chunk_ids=["chunk_alpha"],
                ),
                EntityEvidence(
                    entity_id="doc_a_minirag",
                    document_id="doc_a",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval.",
                    source_chunk_ids=["chunk_minirag_a"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc_a_alpha_minirag",
                    document_id="doc_a",
                    source_entity_id="doc_a_alpha",
                    target_entity_id="doc_a_minirag",
                    source_entity_name="Alpha",
                    target_entity_name="MiniRAG",
                    description="Alpha introduces MiniRAG.",
                    keywords=["entry"],
                    weight=1.0,
                    source_chunk_ids=["chunk_rel_a"],
                )
            ],
        )
    )
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc_b",
            entities=[
                EntityEvidence(
                    entity_id="doc_b_minirag",
                    document_id="doc_b",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph retrieval mode.",
                    source_chunk_ids=["chunk_minirag_b"],
                ),
                EntityEvidence(
                    entity_id="doc_b_sources",
                    document_id="doc_b",
                    name="Source Chunks",
                    entity_type="evidence",
                    description="Recovered source chunks.",
                    source_chunk_ids=["chunk_sources"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc_b_minirag_sources",
                    document_id="doc_b",
                    source_entity_id="doc_b_minirag",
                    target_entity_id="doc_b_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Source Chunks",
                    description="MiniRAG recovers source chunks.",
                    keywords=["recovery"],
                    weight=1.0,
                    source_chunk_ids=["chunk_rel_b"],
                )
            ],
        )
    )


def test_canonical_index_merges_same_name_entities_across_documents(tmp_path) -> None:
    """canonical 模式下同名实体跨文档合并。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(
        tmp_path,
        reload_on_query=True,
        canonicalize_cross_document=True,
    )

    candidates = index.query_entities(["MiniRAG"], top_k=5)

    # 应合并为一个 canonical entity
    assert [candidate.entity.name for candidate in candidates] == ["MiniRAG"]
    entity = candidates[0].entity
    assert entity.document_id == "__canonical__"
    assert entity.source_chunk_ids == ["chunk_minirag_a", "chunk_minirag_b"]
    assert entity.metadata["member_entity_ids"] == [
        "doc_a_minirag",
        "doc_b_minirag",
    ]
    assert entity.metadata["source_document_ids"] == ["doc_a", "doc_b"]


def test_canonical_index_expands_paths_across_documents(tmp_path) -> None:
    """canonical 模式下路径可跨文档桥接。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(
        tmp_path,
        reload_on_query=True,
        canonicalize_cross_document=True,
    )

    alpha = index.query_entities(["Alpha"], top_k=1)[0]
    paths = index.expand_paths(
        seed_entity_ids=[alpha.entity.entity_id],
        seed_relation_ids=[],
        max_hops=2,
    )

    # 应存在跨文档桥接路径
    source_chunks_by_path = [path.source_chunk_ids for path in paths]
    # 跨文档路径应包含来自 doc_a 和 doc_b 的 chunks
    assert [
        "chunk_alpha",
        "chunk_minirag_a",
        "chunk_minirag_b",
        "chunk_sources",
        "chunk_rel_a",
        "chunk_rel_b",
    ] in source_chunks_by_path
    assert any(path.document_id == "__canonical__" for path in paths)


def test_legacy_index_still_keeps_document_scoped_duplicate_entities(tmp_path) -> None:
    """不启用 canonical 时，同名实体保持文档隔离。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path, reload_on_query=True)

    candidates = index.query_entities(["MiniRAG"], top_k=5)

    # 未启用 canonical，应返回两个独立实体
    assert [candidate.entity.entity_id for candidate in candidates] == [
        "doc_a_minirag",
        "doc_b_minirag",
    ]
