"""文档只读服务，封装列出/读取单个文档的业务入口。"""

from __future__ import annotations

from ragflow_lite.domain.models import IndexedDocument
from ragflow_lite.domain.ports import DatasetStore, DocumentCatalog


class DocumentService:
    """封装文档目录的只读查询。"""

    def __init__(
        self,
        catalog: DocumentCatalog,
        dataset_store: DatasetStore,
    ) -> None:
        self.catalog = catalog
        self.dataset_store = dataset_store

    def list_documents(self, dataset_id: str | None = None) -> list[IndexedDocument]:
        docs = self.catalog.list_documents()
        if dataset_id is None:
            return docs
        # 验证 dataset 存在
        self.dataset_store.get_dataset(dataset_id)  # raises DatasetNotFoundError
        return [doc for doc in docs if doc.dataset_id == dataset_id]

    def get_document(self, document_id: str) -> IndexedDocument:
        return self.catalog.get_document(document_id)

    def bind_dataset(self, document_id: str, dataset_id: str) -> None:
        """将文档绑定到指定 dataset。先验证文档存在。"""
        self.catalog.get_document(document_id)
        self.dataset_store.bind_document(document_id, dataset_id)

    def unbind_dataset(self, document_id: str) -> None:
        """解除文档的 dataset 绑定。先验证文档存在。"""
        self.catalog.get_document(document_id)
        self.dataset_store.unbind_document(document_id)
