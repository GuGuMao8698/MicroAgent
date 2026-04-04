"""使用假的 Infinity client 验证 `InfinityDenseVectorIndex` 的单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)

DIMS = 4
SIGNATURE = {"provider": "ark", "model": "ep-test-model", "dimensions": DIMS}


@pytest.fixture
def make_index(fake_infinity_client_factory):
    def factory(
        *,
        client: Any | None = None,
        dimensions: int = DIMS,
        signature: dict[str, Any] | None = None,
        show_columns_mode: str = "dataframe",
    ) -> tuple[Any, InfinityDenseVectorIndex]:
        active_client = client
        if active_client is None:
            active_client = fake_infinity_client_factory(
                show_columns_mode=show_columns_mode
            )

        index = InfinityDenseVectorIndex(
            host="127.0.0.1",
            port=23817,
            database="default_db",
            document_table="documents",
            chunk_table="chunks",
            embedding_dimensions=dimensions,
            embedding_signature=signature or SIGNATURE,
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


def _make_chunk(
    document_id: str = "doc_1",
    index: int = 0,
    vector: list[float] | None = None,
    metadata: dict[str, Any] | None = None,
    text: str | None = None,
) -> EmbeddedChunk:
    return EmbeddedChunk(
        chunk_id=f"chunk_{document_id}_{index}",
        document_id=document_id,
        text=text if text is not None else f"chunk text {index}",
        index=index,
        vector=vector or [1.0, 0.0, 0.0, 0.0],
        metadata=metadata or {"filename": "test.txt", "file_type": "txt"},
    )


class TestInfinityDenseVectorIndex:
    def test_creates_tables_on_init(self, make_index) -> None:
        client, _ = make_index()
        db = client.get_database("default_db")
        assert "documents" in db._tables
        assert "chunks" in db._tables

    def test_creates_tables_on_init_with_tuple_show_columns(self, make_index) -> None:
        client, _ = make_index(show_columns_mode="tuple")
        db = client.get_database("default_db")
        assert "documents" in db._tables
        assert "chunks" in db._tables

    def test_index_document_writes_doc_and_chunks(self, make_index) -> None:
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk()

        idx.index_document(asset, [chunk])

        db = client.get_database("default_db")
        doc_table = db.get_table("documents")
        chunk_table = db.get_table("chunks")
        assert len(doc_table.rows) == 1
        assert doc_table.rows[0]["document_id"] == "doc_1"
        assert len(chunk_table.rows) == 1
        assert chunk_table.rows[0]["chunk_id"] == "chunk_doc_1_0"

    def test_index_document_without_chunks_only_writes_doc(self, make_index) -> None:
        client, idx = make_index()
        asset = _make_asset()

        idx.index_document(asset, [])

        db = client.get_database("default_db")
        doc_table = db.get_table("documents")
        chunk_table = db.get_table("chunks")
        assert len(doc_table.rows) == 1
        assert len(chunk_table.rows) == 0

    def test_index_document_replaces_existing(self, make_index) -> None:
        client, idx = make_index()
        asset = _make_asset()

        idx.index_document(asset, [_make_chunk(index=0)])
        idx.index_document(asset, [_make_chunk(index=0), _make_chunk(index=1)])

        db = client.get_database("default_db")
        assert len(db.get_table("documents").rows) == 1
        assert len(db.get_table("chunks").rows) == 2

    def test_search_returns_matching_chunks(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search([1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"
        assert results[0].score > 0
        assert results[0].metadata["filename"] == "test.txt"

    def test_search_returns_empty_for_no_match(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search([0.0, 0.0, 0.0, -1.0], top_k=5)

        assert len(results) == 0

    def test_delete_document_removes_doc_and_chunks(self, make_index) -> None:
        client, idx = make_index()
        asset = _make_asset()
        idx.index_document(asset, [_make_chunk()])

        idx.delete_document("doc_1")

        db = client.get_database("default_db")
        assert len(db.get_table("documents").rows) == 0
        assert len(db.get_table("chunks").rows) == 0

    def test_rejects_wrong_dimension_vector(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        bad_chunk = _make_chunk(vector=[1.0, 0.0, 0.0])  # 3 dims, expected 4

        with pytest.raises(ProcessingError, match="does not match expected"):
            idx.index_document(asset, [bad_chunk])

    def test_rejects_wrong_query_dimension(self, make_index) -> None:
        _, idx = make_index()

        with pytest.raises(ProcessingError, match="does not match expected"):
            idx.search([1.0, 0.0, 0.0], top_k=5)

    def test_disconnect_closes_client(self, make_index) -> None:
        client, idx = make_index()
        idx.disconnect()
        assert client.disconnected

    def test_metadata_restored_from_json(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(
            metadata={
                "filename": "test.txt",
                "file_type": "txt",
                "start_offset": 0,
                "end_offset": 100,
                "format": "text",
                "page_count": 1,
                "normalized": True,
            },
        )
        idx.index_document(asset, [chunk])

        results = idx.search([1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].metadata["start_offset"] == 0
        assert results[0].metadata["end_offset"] == 100
        assert results[0].metadata["normalized"] is True

    def test_search_raises_on_stale_embedding_signature(self, make_index) -> None:
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        # 篡改已写入行，模拟历史 embedding 配置遗留的数据。
        db = client.get_database("default_db")
        chunk_table = db.get_table("chunks")
        chunk_table.rows[0]["embedding_model"] = "old-ep-model"

        with pytest.raises(ProcessingError, match="Embedding signature mismatch"):
            idx.search([1.0, 0.0, 0.0, 0.0], top_k=5)

    def test_chunk_row_uses_asset_file_type_not_metadata(self, make_index) -> None:
        client, idx = make_index()
        asset = DocumentAsset(
            document_id="doc_1",
            filename="test.txt",
            file_type="pdf",
            storage_path=Path("/tmp/test.txt"),
            size_bytes=100,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        # chunk metadata 中故意不带 file_type，确认结果优先使用文档资产上的值。
        chunk = _make_chunk(
            metadata={"start_offset": 0, "end_offset": 50, "normalized": True},
            vector=[1.0, 0.0, 0.0, 0.0],
        )
        idx.index_document(asset, [chunk])

        db = client.get_database("default_db")
        chunk_table = db.get_table("chunks")
        assert chunk_table.rows[0]["file_type"] == "pdf"
        assert chunk_table.rows[0]["filename"] == "test.txt"

        results = idx.search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0].metadata["file_type"] == "pdf"
        assert results[0].metadata["start_offset"] == 0

    def test_init_fails_when_chunk_table_has_no_vec_column(
        self,
        fake_infinity_client_factory,
    ) -> None:
        client = fake_infinity_client_factory()
        db = client.get_database("default_db")
        # 预先创建一个缺少 `vec` 列的表，验证初始化时会直接失败。
        db.create_table("chunks", {"chunk_id": {"type": "varchar"}})

        with pytest.raises(RuntimeError, match="does not contain a 'vec' column"):
            InfinityDenseVectorIndex(
                host="127.0.0.1",
                port=23817,
                database="default_db",
                document_table="documents",
                chunk_table="chunks",
                embedding_dimensions=DIMS,
                embedding_signature=SIGNATURE,
                client=client,
            )

    def test_ensure_fulltext_index_on_init(self, make_index) -> None:
        client, _ = make_index()
        db = client.get_database("default_db")
        chunk_table = db.get_table("chunks")
        assert "chunks_text_fulltext_idx" in chunk_table._indexes

    def test_search_text_returns_matching_chunks(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk()
        idx.index_document(asset, [chunk])

        results = idx.search_text("chunk text", top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"
        assert results[0].score == 1.0
        assert results[0].metadata["filename"] == "test.txt"

    def test_search_text_returns_empty_for_no_match(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk()
        idx.index_document(asset, [chunk])

        results = idx.search_text("nonexistent text", top_k=5)

        assert len(results) == 0

    # ------------------------------------------------------------------
    # search_hybrid
    # ------------------------------------------------------------------

    def test_search_hybrid_returns_fused_results(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"
        assert results[0].score > 0
        assert results[0].metadata["filename"] == "test.txt"

    def test_search_hybrid_overlap_chunk_returns_one(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].chunk_id == chunk.chunk_id

    def test_search_hybrid_text_only_hit(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[0.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"

    def test_search_hybrid_dense_only_hit(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="no match here", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("xyz", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_1"

    def test_search_hybrid_returns_empty_for_no_match(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[0.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("xyz", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 0

    def test_search_hybrid_rejects_wrong_query_dimension(self, make_index) -> None:
        _, idx = make_index()

        from ragflow_lite.domain.errors import ProcessingError

        with pytest.raises(ProcessingError, match="does not match expected"):
            idx.search_hybrid("query", [1.0, 0.0, 0.0], top_k=5)

    def test_search_hybrid_raises_on_stale_embedding_signature(
        self, make_index
    ) -> None:
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        db = client.get_database("default_db")
        chunk_table = db.get_table("chunks")
        chunk_table.rows[0]["embedding_model"] = "old-ep-model"

        with pytest.raises(ProcessingError, match="Embedding signature mismatch"):
            idx.search_hybrid("chunk text", [1.0, 0.0, 0.0, 0.0], top_k=5)
