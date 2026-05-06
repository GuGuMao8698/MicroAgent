from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.graph_evidence_infinity_store import (
    GraphEvidenceInfinityStore,
)

# ---------------------------------------------------------------------------
# 可控伪依赖：记录调用、可选失败
# ---------------------------------------------------------------------------


@dataclass
class _RecordingGraphStore:
    """记录 upsert / delete 调用的伪图证据存储。"""

    upserts: list[GraphEvidenceBatch] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    documents: dict[str, GraphEvidenceBatch] = field(default_factory=dict)
    fail_upsert: bool = False

    def upsert_document_evidence(
        self, batch: GraphEvidenceBatch
    ) -> GraphEvidenceWriteResult:
        if self.fail_upsert:
            raise RuntimeError("graph store upsert failed")
        self.upserts.append(batch)
        self.documents[batch.document_id] = batch
        return GraphEvidenceWriteResult(
            document_id=batch.document_id,
            entity_count=len(batch.entities),
            relation_count=len(batch.relations),
        )

    def delete_document(self, document_id: str) -> None:
        self.deletes.append(document_id)
        self.documents.pop(document_id, None)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        return self.documents.get(document_id)


@dataclass
class _RecordingCandidateIndex:
    """记录 upsert / delete 调用的伪 Infinity 候选索引。"""

    upserts: list[GraphEvidenceBatch] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    fail_upsert: bool = False

    def upsert_document_evidence(self, batch: GraphEvidenceBatch) -> None:
        if self.fail_upsert:
            raise RuntimeError("candidate upsert failed")
        self.upserts.append(batch)

    def delete_document(self, document_id: str) -> None:
        self.deletes.append(document_id)


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_batch(document_id: str = "doc_1") -> GraphEvidenceBatch:
    """构造包含一个实体和一个关系的测试批次。"""
    entity = EntityEvidence(
        entity_id="entity_1",
        document_id=document_id,
        name="Python",
        entity_type="language",
        description="A popular programming language.",
        source_chunk_ids=["chunk_0"],
    )
    relation = RelationEvidence(
        relation_id="rel_1",
        document_id=document_id,
        source_entity_id="entity_1",
        target_entity_id="entity_2",
        source_entity_name="Python",
        target_entity_name="pip",
        description="Python uses pip for packages.",
        keywords=["packaging"],
        weight=1.0,
        source_chunk_ids=["chunk_0"],
    )
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[entity],
        relations=[relation],
    )


def _build_store(
    *,
    graph_store: _RecordingGraphStore | None = None,
    candidate_index: _RecordingCandidateIndex | None = None,
) -> GraphEvidenceInfinityStore:
    return GraphEvidenceInfinityStore(
        graph_store=graph_store or _RecordingGraphStore(),
        candidate_index=candidate_index or _RecordingCandidateIndex(),
    )


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


class TestUpsertDocumentEvidence:
    def test_upsert_writes_json_store_then_infinity_candidates(self) -> None:
        """upsert 成功时：先写 JSON store，再写 Infinity candidates，返回 JSON store 的结果。"""
        graph_store = _RecordingGraphStore()
        candidate_index = _RecordingCandidateIndex()
        store = _build_store(
            graph_store=graph_store,
            candidate_index=candidate_index,
        )
        batch = _make_batch()

        result = store.upsert_document_evidence(batch)

        # 两者都收到 upsert
        assert len(graph_store.upserts) == 1
        assert graph_store.upserts[0].document_id == "doc_1"
        assert len(candidate_index.upserts) == 1
        assert candidate_index.upserts[0].document_id == "doc_1"
        # 返回值来自 graph_store
        assert result.document_id == "doc_1"
        assert result.entity_count == 1
        assert result.relation_count == 1
        # 无 delete 调用
        assert graph_store.deletes == []
        assert candidate_index.deletes == []

    def test_candidate_failure_rolls_back_json_and_candidate_rows(self) -> None:
        """Infinity candidate 写入失败时：回滚 JSON store 和 Infinity candidates，然后传播异常。"""
        graph_store = _RecordingGraphStore()
        candidate_index = _RecordingCandidateIndex(fail_upsert=True)
        store = _build_store(
            graph_store=graph_store,
            candidate_index=candidate_index,
        )
        batch = _make_batch()

        with pytest.raises(RuntimeError, match="candidate upsert failed"):
            store.upsert_document_evidence(batch)

        # JSON store 先写成功了
        assert len(graph_store.upserts) == 1
        # 但被回滚删除
        assert graph_store.deletes == ["doc_1"]
        assert graph_store.get_document_evidence("doc_1") is None
        # Infinity candidates 也被回滚删除
        assert candidate_index.deletes == ["doc_1"]

    def test_candidate_failure_restores_previous_json_evidence(self) -> None:
        """Infinity 写入失败时，应恢复旧 JSON evidence，而不是删除整份旧数据。"""
        old_batch = _make_batch(document_id="doc_1")
        new_batch = _make_batch(document_id="doc_1")
        new_batch.entities[0].name = "Python updated"
        graph_store = _RecordingGraphStore(documents={"doc_1": old_batch})
        candidate_index = _RecordingCandidateIndex(fail_upsert=True)
        store = _build_store(
            graph_store=graph_store,
            candidate_index=candidate_index,
        )

        with pytest.raises(RuntimeError, match="candidate upsert failed"):
            store.upsert_document_evidence(new_batch)

        assert graph_store.get_document_evidence("doc_1") is old_batch
        assert graph_store.deletes == []
        assert candidate_index.deletes == ["doc_1"]

    def test_json_store_failure_propagates_without_rollback(self) -> None:
        """JSON store 写入失败时：直接传播异常，不尝试写 Infinity candidates，也不回滚。"""
        graph_store = _RecordingGraphStore(fail_upsert=True)
        candidate_index = _RecordingCandidateIndex()
        store = _build_store(
            graph_store=graph_store,
            candidate_index=candidate_index,
        )
        batch = _make_batch()

        with pytest.raises(RuntimeError, match="graph store upsert failed"):
            store.upsert_document_evidence(batch)

        # Infinity candidates 没有收到任何调用
        assert candidate_index.upserts == []
        assert candidate_index.deletes == []
        # graph_store 也没有 delete 调用（JSON store 失败不需要回滚）
        assert graph_store.deletes == []


class TestDeleteDocument:
    def test_delete_removes_from_both_stores(self) -> None:
        """delete 同时删除 JSON store 和 Infinity candidates。"""
        graph_store = _RecordingGraphStore()
        candidate_index = _RecordingCandidateIndex()
        store = _build_store(
            graph_store=graph_store,
            candidate_index=candidate_index,
        )

        store.delete_document("doc_1")

        assert graph_store.deletes == ["doc_1"]
        assert candidate_index.deletes == ["doc_1"]


class TestGetDocumentEvidence:
    def test_get_delegates_to_json_store(self) -> None:
        """读取图证据委托给 JSON store。"""
        batch = _make_batch("doc_read")

        @dataclass
        class _PopulatedGraphStore:
            """带有预填充数据的伪存储。"""

            _batch: GraphEvidenceBatch

            def upsert_document_evidence(
                self, batch: GraphEvidenceBatch
            ) -> GraphEvidenceWriteResult:
                return GraphEvidenceWriteResult(
                    document_id=batch.document_id,
                    entity_count=len(batch.entities),
                    relation_count=len(batch.relations),
                )

            def delete_document(self, document_id: str) -> None:
                pass

            def get_document_evidence(
                self, document_id: str
            ) -> GraphEvidenceBatch | None:
                if document_id == self._batch.document_id:
                    return self._batch
                return None

        store = _build_store(
            graph_store=_PopulatedGraphStore(_batch=batch),
        )

        result = store.get_document_evidence("doc_read")
        assert result is not None
        assert result.document_id == "doc_read"

        assert store.get_document_evidence("nonexistent") is None
