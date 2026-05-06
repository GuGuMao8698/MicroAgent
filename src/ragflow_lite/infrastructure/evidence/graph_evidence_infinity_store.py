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
    若 Infinity 写入失败，回滚 JSON store 和 Infinity candidates。
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
        # 先写 JSON store
        result = self._graph_store.upsert_document_evidence(batch)
        try:
            # 再写 Infinity candidates
            self._candidate_index.upsert_document_evidence(batch)
        except Exception:
            # Infinity 写入失败：回滚两边
            self._candidate_index.delete_document(batch.document_id)
            self._graph_store.delete_document(batch.document_id)
            raise
        return result

    def delete_document(self, document_id: str) -> None:
        self._candidate_index.delete_document(document_id)
        self._graph_store.delete_document(document_id)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        return self._graph_store.get_document_evidence(document_id)
