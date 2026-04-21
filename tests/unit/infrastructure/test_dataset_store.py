"""InfinityDenseVectorIndex 的 dataset / binding 操作单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ragflow_lite.domain.errors import (
    DatasetAlreadyExistsError,
    DatasetNotEmptyError,
    DatasetNotFoundError,
)
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)

DIMS = 4
SIGNATURE = {"provider": "ark", "model": "ep-test-model", "dimensions": DIMS}


class _RowlessTableProxy:
    """模拟真实 RemoteTable：保留 query API，但不暴露 `.rows`。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def rows(self) -> Any:
        raise AttributeError("'RemoteTable' object has no attribute 'rows'")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture
def make_index(fake_infinity_client_factory):
    def factory(
        *,
        client: Any | None = None,
    ) -> tuple[Any, InfinityDenseVectorIndex]:
        active_client = client
        if active_client is None:
            active_client = fake_infinity_client_factory()

        index = InfinityDenseVectorIndex(
            host="127.0.0.1",
            port=23817,
            database="default_db",
            document_table="documents",
            chunk_table="chunks",
            embedding_dimensions=DIMS,
            embedding_signature=SIGNATURE,
            client=active_client,
        )
        return active_client, index

    return factory


def _make_asset(document_id: str = "doc_1") -> DocumentAsset:
    return DocumentAsset(
        document_id=document_id,
        filename="test.txt",
        file_type="txt",
        storage_path=Path("/tmp/test.txt"),
        size_bytes=100,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_chunk(document_id: str = "doc_1", chunk_id: str = "chunk_1") -> EmbeddedChunk:
    return EmbeddedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text="hello world",
        index=0,
        vector=[1.0, 0.0, 0.0, 0.0],
    )


def _wrap_dataset_tables_without_rows(client: Any) -> None:
    db = client.get_database("default_db")
    for table_name in ("documents_datasets", "documents_dataset_bindings"):
        db._tables[table_name] = _RowlessTableProxy(db._tables[table_name])


# ---------------------------------------------------------------------------
# 表创建
# ---------------------------------------------------------------------------


def test_ensure_tables_creates_dataset_and_binding_tables(
    make_index,
) -> None:
    client, index = make_index()
    db = client.get_database("default_db")

    datasets_table = db.get_table("documents_datasets")
    bindings_table = db.get_table("documents_dataset_bindings")

    assert datasets_table.name == "documents_datasets"
    assert bindings_table.name == "documents_dataset_bindings"


# ---------------------------------------------------------------------------
# Dataset CRUD
# ---------------------------------------------------------------------------


def test_create_dataset_returns_dataset(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("测试数据集", "描述")

    assert ds.dataset_id.startswith("ds_")
    assert ds.name == "测试数据集"
    assert ds.description == "描述"
    assert ds.created_at


def test_create_dataset_duplicate_name_raises(make_index) -> None:
    _, index = make_index()
    index.create_dataset("唯一名", "")
    with pytest.raises(DatasetAlreadyExistsError, match="唯一名"):
        index.create_dataset("唯一名", "另一个")


def test_create_dataset_different_names_succeeds(make_index) -> None:
    _, index = make_index()
    ds1 = index.create_dataset("数据集A", "")
    ds2 = index.create_dataset("数据集B", "")
    assert ds1.dataset_id != ds2.dataset_id


def test_list_datasets_returns_all(make_index) -> None:
    _, index = make_index()
    index.create_dataset("A", "desc_a")
    index.create_dataset("B", "desc_b")

    datasets = index.list_datasets()
    assert len(datasets) == 2
    names = {ds.name for ds in datasets}
    assert names == {"A", "B"}


def test_list_datasets_empty(make_index) -> None:
    _, index = make_index()
    assert index.list_datasets() == []


def test_get_dataset_found(make_index) -> None:
    _, index = make_index()
    created = index.create_dataset("测试", "描述")
    found = index.get_dataset(created.dataset_id)
    assert found.name == "测试"


def test_get_dataset_not_found_raises(make_index) -> None:
    _, index = make_index()
    with pytest.raises(DatasetNotFoundError):
        index.get_dataset("ds_nonexistent")


def test_delete_dataset_empty(make_index) -> None:
    _, index = make_index()
    created = index.create_dataset("待删", "")
    index.delete_dataset(created.dataset_id)
    assert index.list_datasets() == []


def test_delete_dataset_not_empty_raises(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("非空", "")
    # 绑定一个文档
    asset = _make_asset()
    chunk = _make_chunk()
    index.index_document(asset, [chunk])
    index.bind_document("doc_1", ds.dataset_id)

    with pytest.raises(DatasetNotEmptyError):
        index.delete_dataset(ds.dataset_id)


def test_delete_dataset_not_found_raises(make_index) -> None:
    _, index = make_index()
    with pytest.raises(DatasetNotFoundError):
        index.delete_dataset("ds_nonexistent")


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_bind_document_to_dataset(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("绑定测试", "")
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])

    index.bind_document("doc_1", ds.dataset_id)

    assert index.get_dataset_id_for_document("doc_1") == ds.dataset_id


def test_bind_document_unknown_dataset_raises(make_index) -> None:
    _, index = make_index()
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])

    with pytest.raises(DatasetNotFoundError):
        index.bind_document("doc_1", "ds_nonexistent")


def test_unbind_document(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("解绑", "")
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)

    index.unbind_document("doc_1")
    assert index.get_dataset_id_for_document("doc_1") is None


def test_unbind_document_no_binding_is_noop(make_index) -> None:
    _, index = make_index()
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    # 不应抛异常
    index.unbind_document("doc_1")
    assert index.get_dataset_id_for_document("doc_1") is None


def test_bind_document_upsert_rebind(make_index) -> None:
    """单归属：重新绑定到新 dataset 时覆盖旧绑定。"""
    _, index = make_index()
    ds1 = index.create_dataset("旧", "")
    ds2 = index.create_dataset("新", "")
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])

    index.bind_document("doc_1", ds1.dataset_id)
    assert index.get_dataset_id_for_document("doc_1") == ds1.dataset_id

    index.bind_document("doc_1", ds2.dataset_id)
    assert index.get_dataset_id_for_document("doc_1") == ds2.dataset_id


def test_get_dataset_id_for_unbound_document_returns_none(make_index) -> None:
    _, index = make_index()
    assert index.get_dataset_id_for_document("doc_nonexistent") is None


def test_get_document_ids_for_dataset(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("文档列表", "")

    for i in range(3):
        asset = _make_asset(document_id=f"doc_{i}")
        chunk = _make_chunk(document_id=f"doc_{i}", chunk_id=f"chunk_{i}")
        index.index_document(asset, [chunk])
        index.bind_document(f"doc_{i}", ds.dataset_id)

    doc_ids = index.get_document_ids_for_dataset(ds.dataset_id)
    assert set(doc_ids) == {"doc_0", "doc_1", "doc_2"}


def test_get_dataset_document_count(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("计数", "")
    assert index.get_dataset_document_count(ds.dataset_id) == 0

    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)
    assert index.get_dataset_document_count(ds.dataset_id) == 1


# ---------------------------------------------------------------------------
# delete_document 清理 binding
# ---------------------------------------------------------------------------


def test_delete_document_cleans_up_binding(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("删除清理", "")
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)

    index.delete_document("doc_1")
    assert index.get_dataset_id_for_document("doc_1") is None
    assert index.get_dataset_document_count(ds.dataset_id) == 0


# ---------------------------------------------------------------------------
# list_documents / get_document 包含 dataset_id
# ---------------------------------------------------------------------------


def test_list_documents_includes_dataset_id(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("列表丰富", "")

    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)

    docs = index.list_documents()
    assert len(docs) == 1
    assert docs[0].dataset_id == ds.dataset_id


def test_list_documents_unbound_has_none_dataset_id(make_index) -> None:
    _, index = make_index()
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])

    docs = index.list_documents()
    assert len(docs) == 1
    assert docs[0].dataset_id is None


def test_get_document_includes_dataset_id(make_index) -> None:
    _, index = make_index()
    ds = index.create_dataset("详情", "")

    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)

    doc = index.get_document("doc_1")
    assert doc.dataset_id == ds.dataset_id


# ---------------------------------------------------------------------------
# dataset_id 单引号转义回归
# ---------------------------------------------------------------------------


def test_get_dataset_with_quoted_id_found(make_index) -> None:
    """get_dataset() 对包含单引号的 dataset_id 能正确命中。"""
    client, index = make_index()
    tricky_id = "ds_it's"
    # 直接往 fake 表里插入一行带引号 dataset_id 的数据。
    db = client.get_database("default_db")
    datasets_table = db.get_table(index._datasets_table)
    datasets_table.rows.append(
        {
            "dataset_id": tricky_id,
            "name": "带引号的数据集",
            "description": "测试",
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    )

    found = index.get_dataset(tricky_id)
    assert found.dataset_id == tricky_id
    assert found.name == "带引号的数据集"


def test_get_dataset_with_quoted_id_not_found_raises(make_index) -> None:
    """get_dataset() 对不存在但包含单引号的 dataset_id 抛 DatasetNotFoundError。"""
    _, index = make_index()
    with pytest.raises(DatasetNotFoundError):
        index.get_dataset("ds_no'exist")


def test_get_document_ids_for_dataset_with_quoted_id(make_index) -> None:
    """get_document_ids_for_dataset() 对包含单引号的 dataset_id 返回空列表。"""
    _, index = make_index()
    result = index.get_document_ids_for_dataset("ds_it's")
    assert result == []


def test_delete_dataset_with_quoted_id_not_found_raises(make_index) -> None:
    """delete_dataset() 对不存在但包含单引号的 dataset_id 抛 DatasetNotFoundError。"""
    _, index = make_index()
    with pytest.raises(DatasetNotFoundError):
        index.delete_dataset("ds_no'exist")


def test_dataset_store_paths_do_not_depend_on_table_rows(make_index) -> None:
    client, index = make_index()
    _wrap_dataset_tables_without_rows(client)

    ds = index.create_dataset("无 rows", "")
    asset = _make_asset()
    index.index_document(asset, [_make_chunk()])
    index.bind_document("doc_1", ds.dataset_id)

    datasets = index.list_datasets()
    docs = index.list_documents()
    doc = index.get_document("doc_1")

    assert [item.name for item in datasets] == ["无 rows"]
    assert docs[0].dataset_id == ds.dataset_id
    assert doc.dataset_id == ds.dataset_id
