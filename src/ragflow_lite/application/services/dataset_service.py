"""Dataset 管理 service，封装 create/list/get/delete 业务入口。"""

from __future__ import annotations

from ragflow_lite.domain.models import Dataset
from ragflow_lite.domain.ports import DatasetStore


class DatasetService:
    """封装 dataset 的管理与查询。"""

    def __init__(self, store: DatasetStore) -> None:
        self.store = store

    def create_dataset(self, name: str, description: str) -> Dataset:
        name = name.strip()
        if not name:
            raise ValueError("Dataset name must not be empty.")
        return self.store.create_dataset(name, description)

    def list_datasets(self) -> list[Dataset]:
        return self.store.list_datasets()

    def get_dataset(self, dataset_id: str) -> Dataset:
        return self.store.get_dataset(dataset_id)

    def delete_dataset(self, dataset_id: str) -> None:
        self.store.delete_dataset(dataset_id)
