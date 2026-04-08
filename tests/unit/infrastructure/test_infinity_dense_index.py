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


def _search_hybrid_and_get_chunk_table(
    client: Any,
    idx: InfinityDenseVectorIndex,
    *,
    query: str,
    query_vector: list[float],
    top_k: int,
) -> Any:
    idx.search_hybrid(query, query_vector, top_k=top_k)
    return client.get_database("default_db").get_table("chunks")


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
        assert "chunks_filename_fulltext_idx" in chunk_table._indexes

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

    def test_search_hybrid_uses_candidate_k_window(self, make_index) -> None:
        """search_hybrid 内部对 text/dense/fusion 传入 candidate_k 而非 top_k。"""
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        top_k = 5
        expected_candidate_k = max(30, top_k * 4)  # 30
        chunk_table = _search_hybrid_and_get_chunk_table(
            client,
            idx,
            query="hello",
            query_vector=[1.0, 0.0, 0.0, 0.0],
            top_k=top_k,
        )
        assert chunk_table.last_hybrid_text_topn == expected_candidate_k
        assert chunk_table.last_hybrid_dense_topn == expected_candidate_k
        assert chunk_table.last_hybrid_fusion_topn == expected_candidate_k

    def test_search_hybrid_trims_results_to_top_k(self, make_index) -> None:
        """search_hybrid 返回结果数量不超过请求的 top_k。"""
        _, idx = make_index()
        asset = _make_asset()
        chunks = [
            _make_chunk(index=i, text=f"chunk text {i}", vector=[1.0, 0.0, 0.0, 0.0])
            for i in range(10)
        ]
        idx.index_document(asset, chunks)

        results = idx.search_hybrid("chunk text", [1.0, 0.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_search_hybrid_candidate_window_recalls_dual_signal_chunk(
        self, make_index
    ) -> None:
        """candidate_k 扩召窗口使单路截断之外的双信号 chunk 进入最终结果。

        构造：5 个纯 text 匹配 chunk + 2 个纯 dense 匹配 chunk + 1 个双信号
        chunk（同时匹配 text 和 dense）。使用 top_k=1 时，若各分支只用
        topn=1 截断，双信号 chunk 会同时被两个分支截掉；但 candidate_k=30
        使其进入 fusion，最终因双信号加权得分最高而被召回。
        """
        _, idx = make_index()
        asset = _make_asset()

        chunks: list[EmbeddedChunk] = []
        # 5 个 text-only chunk：匹配 "alpha" 但 dense 得分为零
        for i in range(5):
            chunks.append(
                _make_chunk(
                    document_id="doc_1",
                    index=i,
                    text="alpha content",
                    vector=[0.0, 0.0, 0.0, 0.0],
                )
            )
        # 2 个 dense-only chunk：高 dense 分但不包含 "alpha"
        for i in range(5, 7):
            chunks.append(
                _make_chunk(
                    document_id="doc_1",
                    index=i,
                    text="xyz unrelated",
                    vector=[0.9, 0.0, 0.0, 0.0],
                )
            )
        # 1 个双信号 chunk：同时匹配 text 和 dense
        dual = _make_chunk(
            document_id="doc_1",
            index=7,
            text="alpha keyword",
            vector=[0.9, 0.0, 0.0, 0.0],
        )
        chunks.append(dual)

        idx.index_document(asset, chunks)

        results = idx.search_hybrid("alpha", [1.0, 0.0, 0.0, 0.0], top_k=1)

        assert len(results) == 1
        assert results[0].chunk_id == dual.chunk_id

    def test_search_hybrid_text_fields_is_filename_boost_text(self, make_index) -> None:
        """search_hybrid 的 text 分支使用 filename^3,text 多字段。"""
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        chunk_table = _search_hybrid_and_get_chunk_table(
            client,
            idx,
            query="hello",
            query_vector=[1.0, 0.0, 0.0, 0.0],
            top_k=5,
        )
        assert chunk_table.last_hybrid_text_fields == "filename^3,text"

    def test_search_hybrid_recalls_via_filename_match(self, make_index) -> None:
        """正文不命中、dense 不命中时，仅靠 filename sparse 字段召回。"""
        _, idx = make_index()
        asset = DocumentAsset(
            document_id="doc_fn",
            filename="ragflow-manual.md",
            file_type="md",
            storage_path=Path("/tmp/ragflow-manual.md"),
            size_bytes=100,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        chunk = _make_chunk(
            document_id="doc_fn",
            text="unrelated content here",
            vector=[0.0, 0.0, 0.0, 0.0],
            metadata={"filename": "ragflow-manual.md", "file_type": "md"},
        )
        idx.index_document(asset, [chunk])

        # "manual" 不在 text 中，但 filename 中包含，sparse 应命中。
        results = idx.search_hybrid("manual", [0.0, 0.0, 0.0, 1.0], top_k=5)

        assert len(results) == 1
        assert results[0].document_id == "doc_fn"


class TestDocumentCatalog:
    """验证 InfinityDenseVectorIndex 的 DocumentCatalog 实现。"""

    def test_list_documents_returns_empty(self, make_index) -> None:
        _, idx = make_index()
        assert idx.list_documents() == []

    def test_list_documents_returns_documents_in_reverse_order(
        self, make_index
    ) -> None:
        _, idx = make_index()
        for i in range(3):
            asset = DocumentAsset(
                document_id=f"doc_{i}",
                filename=f"test_{i}.txt",
                file_type="txt",
                storage_path=Path(f"/tmp/test_{i}.txt"),
                size_bytes=100,
                created_at=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
                metadata={"format": "text"},
            )
            idx.index_document(asset, [])

        docs = idx.list_documents()
        assert len(docs) == 3
        # 按 created_at 倒序：最新的在前
        assert docs[0].document_id == "doc_2"
        assert docs[1].document_id == "doc_1"
        assert docs[2].document_id == "doc_0"

    def test_list_documents_includes_metadata(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        asset.metadata = {"format": "pdf", "page_count": 3}
        idx.index_document(asset, [])

        docs = idx.list_documents()
        assert len(docs) == 1
        assert docs[0].metadata == {"format": "pdf", "page_count": 3}

    def test_list_documents_empty_metadata(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        # asset.metadata 默认为空 dict
        idx.index_document(asset, [])

        docs = idx.list_documents()
        assert len(docs) == 1
        assert docs[0].metadata == {}

    def test_get_document_returns_single_document(self, make_index) -> None:
        _, idx = make_index()
        asset = _make_asset()
        asset.metadata = {"format": "pdf", "page_count": 1}
        idx.index_document(asset, [])

        doc = idx.get_document("doc_1")
        assert doc.document_id == "doc_1"
        assert doc.filename == "test.txt"
        assert doc.file_type == "txt"
        assert doc.size_bytes == 100
        assert doc.metadata == {"format": "pdf", "page_count": 1}

    def test_get_document_raises_not_found(self, make_index) -> None:
        from ragflow_lite.domain.errors import DocumentNotFoundError

        _, idx = make_index()
        with pytest.raises(DocumentNotFoundError, match="nonexistent"):
            idx.get_document("nonexistent")

    def test_index_document_writes_metadata_to_parser_metadata_json(
        self, make_index
    ) -> None:
        client, idx = make_index()
        asset = _make_asset()
        asset.metadata = {"format": "pdf", "page_count": 5}
        idx.index_document(asset, [])

        db = client.get_database("default_db")
        doc_table = db.get_table("documents")
        assert len(doc_table.rows) == 1
        import json

        parsed = json.loads(doc_table.rows[0]["parser_metadata_json"])
        assert parsed == {"format": "pdf", "page_count": 5}

    # ------------------------------------------------------------------
    # sort / filter 回归
    # ------------------------------------------------------------------

    def test_list_documents_uses_sdk_sort_and_returns_reverse_order(
        self, make_index
    ) -> None:
        """list_documents() 使用 [[col, SortType.Desc]] 形式的 sort 参数。"""
        _, idx = make_index()
        for i in range(3):
            asset = DocumentAsset(
                document_id=f"doc_{i}",
                filename=f"test_{i}.txt",
                file_type="txt",
                storage_path=Path(f"/tmp/test_{i}.txt"),
                size_bytes=100,
                created_at=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
            )
            idx.index_document(asset, [])

        docs = idx.list_documents()
        assert [d.document_id for d in docs] == ["doc_2", "doc_1", "doc_0"]

    def test_get_document_with_single_quote_in_id(self, make_index) -> None:
        """get_document() 对包含单引号的 document_id 能正确命中。"""
        _, idx = make_index()
        tricky_id = "doc_it's"
        asset = DocumentAsset(
            document_id=tricky_id,
            filename="tricky.txt",
            file_type="txt",
            storage_path=Path("/tmp/tricky.txt"),
            size_bytes=42,
            created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        idx.index_document(asset, [])

        doc = idx.get_document(tricky_id)
        assert doc.document_id == tricky_id
        assert doc.filename == "tricky.txt"

    def test_get_document_not_found_with_single_quote_in_id(self, make_index) -> None:
        """get_document() 对不存在但包含单引号的 ID 抛 DocumentNotFoundError。"""
        from ragflow_lite.domain.errors import DocumentNotFoundError

        _, idx = make_index()
        with pytest.raises(DocumentNotFoundError, match="no'exist"):
            idx.get_document("no'exist")

    def test_delete_document_with_single_quote_in_id(self, make_index) -> None:
        """delete_document() 对包含单引号的 document_id 可正常删除。"""
        client, idx = make_index()
        tricky_id = "doc_o'clock"
        asset = DocumentAsset(
            document_id=tricky_id,
            filename="clock.txt",
            file_type="txt",
            storage_path=Path("/tmp/clock.txt"),
            size_bytes=10,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        idx.index_document(asset, [_make_chunk(document_id=tricky_id)])

        idx.delete_document(tricky_id)

        db = client.get_database("default_db")
        assert len(db.get_table("documents").rows) == 0
        assert len(db.get_table("chunks").rows) == 0
