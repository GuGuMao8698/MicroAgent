"""GraphEvidenceSidecarStore：组合 GraphEvidenceStore 与 GraphCandidateSidecar 的包装器。

在 upsert 时先委托内部 graph_store 持久化图证据，再调用 sidecar 重建候选向量；
在 delete 时同时清理 graph_store 和 sidecar 数据。对外行为与 GraphEvidenceStore
协议一致，可无缝替换 pipeline 中的 graph_store。
"""

from __future__ import annotations

from ragflow_lite.domain.models import (
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
)
from ragflow_lite.domain.ports.interfaces import GraphEvidenceStore
from ragflow_lite.infrastructure.evidence.graph_candidate_sidecar import (
    GraphCandidateSidecar,
    QueryEmbedder,
)


class GraphEvidenceSidecarStore:
    """组合 GraphEvidenceStore 与 GraphCandidateSidecar 的包装器。

    对外实现 GraphEvidenceStore 协议，内部同时管理图证据持久化和
    候选向量旁路存储，确保两者生命周期一致。

    Parameters
    ----------
    graph_store:
        内部图证据存储实例，来自 domain ports。
    sidecar:
        候选向量旁路存储实例，来自 Task 1。
    embedder:
        嵌入器实例，满足 QueryEmbedder 协议。
    """

    def __init__(
        self,
        *,
        graph_store: GraphEvidenceStore,
        sidecar: GraphCandidateSidecar,
        embedder: QueryEmbedder,
    ) -> None:
        self._graph_store = graph_store
        self._sidecar = sidecar
        self._embedder = embedder

    def upsert_document_evidence(
        self, batch: GraphEvidenceBatch
    ) -> GraphEvidenceWriteResult:
        """先委托 graph_store 持久化图证据，再调用 sidecar 重建候选向量。"""
        result = self._graph_store.upsert_document_evidence(batch)
        self._sidecar.rebuild_document(batch, self._embedder)
        return result

    def delete_document(self, document_id: str) -> None:
        """同时清理 graph_store 和 sidecar 数据。"""
        self._graph_store.delete_document(document_id)
        self._sidecar.delete_document(document_id)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        """委托内部 graph_store 读取图证据。"""
        return self._graph_store.get_document_evidence(document_id)
