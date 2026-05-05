from __future__ import annotations

from pathlib import Path

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_sidecar import (
    GraphCandidateSidecar,
    build_entity_embedding_text,
    build_relationship_embedding_text,
)

# ---------------------------------------------------------------------------
# Fake embedder: returns deterministic vectors based on text hash
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """确定性伪嵌入器，根据文本生成固定向量。"""

    def embed_query(self, query: str) -> list[float]:
        # 简单确定性向量：用文本哈希映射到 [0,1) 区间填充 4 维
        base = hash(query)
        return [(base % (10**6 + i)) / (10**6 + i) for i in range(1, 5)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch(document_id: str = "doc_1") -> GraphEvidenceBatch:
    """构造包含一个实体和一个关系的测试批次。"""
    entity = EntityEvidence(
        entity_id="entity_1",
        document_id=document_id,
        name="TypeScript",
        entity_type="language",
        description="A typed superset of JavaScript.",
        source_chunk_ids=["chunk_0"],
    )
    relation = RelationEvidence(
        relation_id="rel_1",
        document_id=document_id,
        source_entity_id="entity_1",
        target_entity_id="entity_2",
        source_entity_name="TypeScript",
        target_entity_name="JavaScript",
        description="TypeScript compiles to JavaScript.",
        keywords=["compilation", "web"],
        weight=1.0,
        source_chunk_ids=["chunk_0"],
    )
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[entity],
        relations=[relation],
    )


SIGNATURE_A: dict[str, str | int | None] = {
    "model": "fake-model",
    "dim": 4,
}
SIGNATURE_B: dict[str, str | int | None] = {
    "model": "other-model",
    "dim": 4,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_entity_embedding_text_uses_name_only() -> None:
    """实体嵌入文本只使用 entity.name，不包含 description 或 type。"""
    entity = EntityEvidence(
        entity_id="e1",
        document_id="doc_1",
        name="TypeScript",
        entity_type="language",
        description="A typed superset of JavaScript.",
        source_chunk_ids=[],
    )
    text = build_entity_embedding_text(entity)
    assert text == "TypeScript"


def test_relationship_embedding_text_uses_endpoints_keywords_and_description() -> None:
    """关系嵌入文本由 source_name、target_name、keywords、description 四部分以 \\n 拼接。"""
    relation = RelationEvidence(
        relation_id="r1",
        document_id="doc_1",
        source_entity_id="e1",
        target_entity_id="e2",
        source_entity_name="TypeScript",
        target_entity_name="JavaScript",
        description="TypeScript compiles to JavaScript.",
        keywords=["compilation", "web"],
        weight=1.0,
        source_chunk_ids=[],
    )
    text = build_relationship_embedding_text(relation)
    assert (
        text
        == "TypeScript\nJavaScript\ncompilation web\nTypeScript compiles to JavaScript."
    )


def test_sidecar_rebuilds_document_candidate_vectors(tmp_path: Path) -> None:
    """rebuild_document 后 load_all 能返回正确的实体和关系向量记录。"""
    embedder = FakeEmbedder()
    sidecar = GraphCandidateSidecar(
        sidecar_dir=tmp_path,
        embedding_signature=SIGNATURE_A,
    )
    batch = _make_batch("doc_1")

    sidecar.rebuild_document(batch, embedder)

    snapshot = sidecar.load_all()
    assert len(snapshot.entities) == 1
    assert len(snapshot.relationships) == 1

    ent_rec = snapshot.entities[0]
    assert ent_rec.candidate_id == "entity_1"
    assert ent_rec.document_id == "doc_1"
    assert ent_rec.candidate_kind == "entity"
    assert ent_rec.embedding_text == "TypeScript"
    assert ent_rec.vector == embedder.embed_query("TypeScript")

    rel_rec = snapshot.relationships[0]
    assert rel_rec.candidate_id == "rel_1"
    assert rel_rec.document_id == "doc_1"
    assert rel_rec.candidate_kind == "relationship"
    assert "TypeScript" in rel_rec.embedding_text
    # embedder 被调用了两次（entity + relationship）
    expected_rel_text = build_relationship_embedding_text(batch.relations[0])
    assert rel_rec.embedding_text == expected_rel_text
    assert rel_rec.vector == embedder.embed_query(expected_rel_text)


def test_sidecar_delete_document_removes_vectors(tmp_path: Path) -> None:
    """rebuild 后 delete_document，再 load_all 返回空快照。"""
    embedder = FakeEmbedder()
    sidecar = GraphCandidateSidecar(
        sidecar_dir=tmp_path,
        embedding_signature=SIGNATURE_A,
    )
    batch = _make_batch("doc_1")
    sidecar.rebuild_document(batch, embedder)

    sidecar.delete_document("doc_1")

    snapshot = sidecar.load_all()
    assert len(snapshot.entities) == 0
    assert len(snapshot.relationships) == 0


def test_sidecar_rejects_embedding_signature_mismatch(tmp_path: Path) -> None:
    """使用签名 A 写入后，用签名 B 构造新 sidecar 实例 load_all 应抛出 ProcessingError。"""
    embedder = FakeEmbedder()

    # 用 SIGNATURE_A 写入
    sidecar_a = GraphCandidateSidecar(
        sidecar_dir=tmp_path,
        embedding_signature=SIGNATURE_A,
    )
    sidecar_a.rebuild_document(_make_batch("doc_1"), embedder)

    # 用 SIGNATURE_B 打开同一目录
    sidecar_b = GraphCandidateSidecar(
        sidecar_dir=tmp_path,
        embedding_signature=SIGNATURE_B,
    )

    with pytest.raises(ProcessingError):
        sidecar_b.load_all()
