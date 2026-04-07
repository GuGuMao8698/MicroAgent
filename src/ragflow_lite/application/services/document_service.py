"""文档只读服务，封装列出/读取单个文档的业务入口。"""

from __future__ import annotations

from ragflow_lite.domain.models import IndexedDocument
from ragflow_lite.domain.ports import DocumentCatalog


class DocumentService:
    """封装文档目录的只读查询。"""

    def __init__(self, catalog: DocumentCatalog) -> None:
        self.catalog = catalog

    def list_documents(self) -> list[IndexedDocument]:
        return self.catalog.list_documents()

    def get_document(self, document_id: str) -> IndexedDocument:
        return self.catalog.get_document(document_id)
