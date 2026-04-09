"""DatasetService 和 DocumentService dataset 绑定行为的单元测试。"""

from __future__ import annotations

import pytest

from ragflow_lite.application.services.dataset_service import DatasetService
from ragflow_lite.application.services.document_service import DocumentService
from ragflow_lite.domain.errors import (
    DatasetAlreadyExistsError,
    DatasetNotEmptyError,
    DatasetNotFoundError,
    DocumentNotFoundError,
)
from ragflow_lite.domain.models import Dataset, IndexedDocument

# ---------------------------------------------------------------------------
# 内存 fake store
# ---------------------------------------------------------------------------


class FakeDatasetStore:
    """内存实现的 DatasetStore，用于 service 层测试。"""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._bindings: dict[str, str] = {}  # document_id -> dataset_id

    def create_dataset(self, name: str, description: str) -> Dataset:
        for ds in self._datasets.values():
            if ds.name == name:
                raise DatasetAlreadyExistsError(name)
        ds = Dataset(
            dataset_id=f"ds_{name}",
            name=name,
            description=description,
            created_at="2025-01-01T00:00:00+00:00",
        )
        self._datasets[ds.dataset_id] = ds
        return ds

    def list_datasets(self) -> list[Dataset]:
        return list(self._datasets.values())

    def get_dataset(self, dataset_id: str) -> Dataset:
        if dataset_id not in self._datasets:
            raise DatasetNotFoundError(dataset_id)
        return self._datasets[dataset_id]

    def delete_dataset(self, dataset_id: str) -> None:
        self.get_dataset(dataset_id)
        count = self.get_dataset_document_count(dataset_id)
        if count > 0:
            raise DatasetNotEmptyError(dataset_id)
        del self._datasets[dataset_id]

    def bind_document(self, document_id: str, dataset_id: str) -> None:
        self.get_dataset(dataset_id)
        self._bindings[document_id] = dataset_id

    def unbind_document(self, document_id: str) -> None:
        self._bindings.pop(document_id, None)

    def get_dataset_id_for_document(self, document_id: str) -> str | None:
        return self._bindings.get(document_id)

    def get_document_ids_for_dataset(self, dataset_id: str) -> list[str]:
        return [
            doc_id for doc_id, ds_id in self._bindings.items() if ds_id == dataset_id
        ]

    def get_dataset_document_count(self, dataset_id: str) -> int:
        return len(self.get_document_ids_for_dataset(dataset_id))


class FakeCatalog:
    """最小 DocumentCatalog 实现，模拟 Infinity 的 dataset_id enrichment。"""

    def __init__(
        self,
        docs: list[IndexedDocument] | None = None,
        store: FakeDatasetStore | None = None,
    ) -> None:
        self._docs = docs or []
        self._store = store

    def list_documents(self) -> list[IndexedDocument]:
        result = []
        for doc in self._docs:
            doc.dataset_id = (
                self._store.get_dataset_id_for_document(doc.document_id)
                if self._store
                else None
            )
            result.append(doc)
        return result

    def get_document(self, document_id: str) -> IndexedDocument:
        for doc in self._docs:
            if doc.document_id == document_id:
                if self._store:
                    doc.dataset_id = self._store.get_dataset_id_for_document(
                        document_id
                    )
                return doc
        raise DocumentNotFoundError(document_id)


# ---------------------------------------------------------------------------
# DatasetService tests
# ---------------------------------------------------------------------------


class TestDatasetService:
    @pytest.fixture
    def service(self) -> DatasetService:
        return DatasetService(store=FakeDatasetStore())

    def test_create_dataset_strips_name(self, service) -> None:
        ds = service.create_dataset("  名称  ", "")
        assert ds.name == "名称"

    def test_create_dataset_blank_name_raises(self, service) -> None:
        with pytest.raises(ValueError, match="empty"):
            service.create_dataset("   ", "")

    def test_create_dataset_duplicate_name_raises(self, service) -> None:
        service.create_dataset("同名", "")
        with pytest.raises(DatasetAlreadyExistsError):
            service.create_dataset("同名", "")

    def test_list_datasets(self, service) -> None:
        service.create_dataset("A", "")
        service.create_dataset("B", "")
        assert len(service.list_datasets()) == 2

    def test_get_dataset(self, service) -> None:
        created = service.create_dataset("测试", "描述")
        found = service.get_dataset(created.dataset_id)
        assert found.name == "测试"

    def test_get_dataset_not_found(self, service) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.get_dataset("ds_nonexistent")

    def test_delete_dataset(self, service) -> None:
        created = service.create_dataset("待删", "")
        service.delete_dataset(created.dataset_id)
        assert service.list_datasets() == []

    def test_delete_dataset_not_found(self, service) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.delete_dataset("ds_nonexistent")


# ---------------------------------------------------------------------------
# DocumentService dataset binding tests
# ---------------------------------------------------------------------------


class TestDocumentServiceDatasetBinding:
    @pytest.fixture
    def store(self) -> FakeDatasetStore:
        return FakeDatasetStore()

    @pytest.fixture
    def docs(self) -> list[IndexedDocument]:
        return [
            IndexedDocument(
                document_id="doc_1",
                filename="a.txt",
                file_type="txt",
                size_bytes=10,
                created_at="2025-01-01T00:00:00+00:00",
            ),
            IndexedDocument(
                document_id="doc_2",
                filename="b.txt",
                file_type="txt",
                size_bytes=20,
                created_at="2025-01-01T00:00:00+00:00",
            ),
        ]

    @pytest.fixture
    def service(self, docs, store) -> DocumentService:
        return DocumentService(
            catalog=FakeCatalog(docs, store=store),
            dataset_store=store,
        )

    def test_list_documents_no_filter(self, service) -> None:
        result = service.list_documents()
        assert len(result) == 2

    def test_list_documents_filter_by_dataset(self, service, store) -> None:
        ds = store.create_dataset("过滤测试", "")
        store.bind_document("doc_1", ds.dataset_id)

        filtered = service.list_documents(dataset_id=ds.dataset_id)
        assert len(filtered) == 1
        assert filtered[0].document_id == "doc_1"

    def test_list_documents_filter_unknown_dataset_raises(self, service) -> None:
        with pytest.raises(DatasetNotFoundError):
            service.list_documents(dataset_id="ds_nonexistent")

    def test_bind_dataset(self, service, store) -> None:
        ds = store.create_dataset("绑定", "")
        service.bind_dataset("doc_1", ds.dataset_id)
        assert store.get_dataset_id_for_document("doc_1") == ds.dataset_id

    def test_bind_dataset_unknown_document_raises(self, service, store) -> None:
        ds = store.create_dataset("绑定", "")
        with pytest.raises(DocumentNotFoundError):
            service.bind_dataset("doc_nonexistent", ds.dataset_id)

    def test_unbind_dataset(self, service, store) -> None:
        ds = store.create_dataset("解绑", "")
        store.bind_document("doc_1", ds.dataset_id)
        service.unbind_dataset("doc_1")
        assert store.get_dataset_id_for_document("doc_1") is None

    def test_unbind_dataset_unknown_document_raises(self, service) -> None:
        with pytest.raises(DocumentNotFoundError):
            service.unbind_dataset("doc_nonexistent")
