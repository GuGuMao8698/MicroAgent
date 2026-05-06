from __future__ import annotations

from ragflow_lite.domain.models import (
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
)
from ragflow_lite.domain.ports.interfaces import GraphEvidenceStore
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    InfinityGraphCandidateIndex,
)


class GraphEvidenceInfinityStore:
    """写入同步包装器：同时更新 JSON 图证据和 Infinity 图候选行。

    写入顺序：先 JSON store，再 Infinity candidates。
    若 Infinity 写入失败，恢复 JSON store 到写入前状态，并清理本次 Infinity candidates。
    回滚是尽力而为：如果回滚本身失败，原始异常会继续传播。
    """

    def __init__(
        self,
        *,
        graph_store: GraphEvidenceStore,
        candidate_index: InfinityGraphCandidateIndex,
    ) -> None:
        self._graph_store = graph_store
        self._candidate_index = candidate_index

    def upsert_document_evidence(
        self,
        batch: GraphEvidenceBatch,
    ) -> GraphEvidenceWriteResult:
        # 快照写入前状态，用于失败时恢复
        previous_batch = self._graph_store.get_document_evidence(batch.document_id)
        result = self._graph_store.upsert_document_evidence(batch)
        try:
            self._candidate_index.upsert_document_evidence(batch)
        except Exception:
            self._candidate_index.delete_document(batch.document_id)
            if previous_batch is None:
                self._graph_store.delete_document(batch.document_id)
            else:
                self._graph_store.upsert_document_evidence(previous_batch)
            raise
        return result

    def delete_document(self, document_id: str) -> None:
        self._candidate_index.delete_document(document_id)
        self._graph_store.delete_document(document_id)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        return self._graph_store.get_document_evidence(document_id)
