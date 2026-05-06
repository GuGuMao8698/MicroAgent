"""使用假的 Infinity client 验证 `InfinityDenseVectorIndex` 的单元测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    ChunkHybridRetrievalConfig,
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
        chunk_hybrid_config: ChunkHybridRetrievalConfig | None = None,
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
            chunk_hybrid_config=chunk_hybrid_config,
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


def _create_existing_chunk_table_without_fulltext_indexes(db: Any) -> Any:
    db.create_table(
        "chunks",
        {
            "chunk_id": {"type": "varchar"},
            "document_id": {"type": "varchar"},
            "chunk_index": {"type": "integer"},
            "text": {"type": "varchar"},
            "vec": {"type": f"vector,{DIMS},float"},
            "filename": {"type": "varchar"},
            "file_type": {"type": "varchar"},
            "chunk_metadata_json": {"type": "varchar"},
            "embedding_provider": {"type": "varchar"},
            "embedding_model": {"type": "varchar"},
            "embedding_dimensions": {"type": "integer"},
            "filename_kwd": {"type": "varchar"},
            "filename_tks": {"type": "varchar"},
            "content_tks": {"type": "varchar"},
            "content_sm_tks": {"type": "varchar"},
        },
    )
    return db.get_table("chunks")


class TestInfinityDenseVectorIndex:
    def test_chunk_hybrid_config_defaults_match_spec(self) -> None:
        config = ChunkHybridRetrievalConfig()

        assert config.initial_recall_n == 1024
        assert config.text_weight == 0.05
        assert config.dense_weight == 0.95
        assert config.minimum_should_match == 0.3
        assert config.dense_similarity_threshold == 0.2
        assert config.fusion_normalize == "atan"
        assert config.position_prior_weight == 0.03
        assert config.position_prior_enabled is True
        assert (
            config.match_text_fields
            == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
        )

    def test_accepts_custom_chunk_hybrid_config(self, make_index) -> None:
        config = ChunkHybridRetrievalConfig(
            initial_recall_n=77,
            text_weight=0.2,
            dense_weight=0.8,
            minimum_should_match=0.4,
            dense_similarity_threshold=0.25,
            fusion_normalize="atan",
            position_prior_weight=0.01,
            position_prior_enabled=False,
        )

        _, idx = make_index(chunk_hybrid_config=config)

        assert idx._chunk_hybrid_config is config

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

    @pytest.mark.parametrize("score_column", ["SCORE", "score"])
    def test_search_accepts_live_infinity_score_column_names(
        self, make_index, monkeypatch: pytest.MonkeyPatch, score_column: str
    ) -> None:
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(
            vector=[1.0, 0.0, 0.0, 0.0],
            text="dense row",
            metadata={"source": "fixture"},
        )
        idx.index_document(asset, [chunk])

        chunk_table = client.get_database("default_db").get_table("chunks")
        original_match_dense = chunk_table.match_dense

        def match_dense_with_live_score(**kwargs: Any) -> Any:
            builder = original_match_dense(**kwargs)
            original_to_pl_dense = builder._to_pl_dense

            def to_pl_dense_with_live_score(
                match_kwargs: dict[str, Any],
            ) -> tuple[pl.DataFrame, dict]:
                df, extra = original_to_pl_dense(match_kwargs)
                if df.is_empty():
                    return df, extra
                return df.rename({"_distance": score_column}), extra

            monkeypatch.setattr(builder, "_to_pl_dense", to_pl_dense_with_live_score)
            return builder

        monkeypatch.setattr(chunk_table, "match_dense", match_dense_with_live_score)

        results = idx.search([1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk_doc_1_0"
        assert results[0].document_id == "doc_1"
        assert results[0].text == "dense row"
        assert results[0].score == pytest.approx(1.0)
        assert results[0].metadata["source"] == "fixture"
        assert results[0].metadata["filename"] == "test.txt"
        assert results[0].metadata["file_type"] == "txt"

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

    def test_creates_chunk_fielded_text_columns_and_indexes(self, make_index) -> None:
        client, _ = make_index()
        db = client.get_database("default_db")
        chunk_table = db.get_table("chunks")

        assert "filename_kwd" in chunk_table.columns
        assert "filename_tks" in chunk_table.columns
        assert "content_tks" in chunk_table.columns
        assert "content_sm_tks" in chunk_table.columns
        assert f"{chunk_table.name}_filename_kwd_fulltext_idx" in chunk_table._indexes
        assert f"{chunk_table.name}_filename_tks_fulltext_idx" in chunk_table._indexes
        assert f"{chunk_table.name}_content_tks_fulltext_idx" in chunk_table._indexes
        assert f"{chunk_table.name}_content_sm_tks_fulltext_idx" in chunk_table._indexes

    def test_index_document_writes_chunk_fielded_text(
        self, make_index, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ragflow_lite.infrastructure.vector_indexes import chunk_text_fields

        monkeypatch.setattr(
            chunk_text_fields,
            "build_chunk_text_fields",
            lambda *, filename, text: {
                "filename_kwd": filename,
                "filename_tks": "filename tokens",
                "content_tks": "content tokens",
                "content_sm_tks": "content small tokens",
            },
        )
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world")

        idx.index_document(asset, [chunk])

        chunk_table = client.get_database("default_db").get_table("chunks")
        row = chunk_table.rows[0]
        assert row["filename_kwd"] == "test.txt"
        assert row["filename_tks"] == "filename tokens"
        assert row["content_tks"] == "content tokens"
        assert row["content_sm_tks"] == "content small tokens"

    def test_init_repairs_missing_fulltext_indexes_on_existing_chunk_table(
        self,
        fake_infinity_client_factory,
    ) -> None:
        client = fake_infinity_client_factory()
        db = client.get_database("default_db")
        _create_existing_chunk_table_without_fulltext_indexes(db)

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

        chunk_table = db.get_table("chunks")
        assert chunk_table.list_indexes().index_names == [
            "chunks_text_fulltext_idx",
            "chunks_filename_fulltext_idx",
            "chunks_filename_kwd_fulltext_idx",
            "chunks_filename_tks_fulltext_idx",
            "chunks_content_tks_fulltext_idx",
            "chunks_content_sm_tks_fulltext_idx",
        ]

    def test_init_fails_when_fulltext_index_creation_fails(
        self,
        fake_infinity_client_factory,
    ) -> None:
        client = fake_infinity_client_factory()
        db = client.get_database("default_db")
        chunk_table = _create_existing_chunk_table_without_fulltext_indexes(db)

        def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("index create failed")

        chunk_table.create_index = _raise

        with pytest.raises(RuntimeError, match="index create failed"):
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

    def test_rows_to_chunks_accepts_uppercase_score_column(self, make_index) -> None:
        _, idx = make_index()
        df = pl.DataFrame(
            [
                {
                    "chunk_id": "chunk_doc_1_0",
                    "document_id": "doc_1",
                    "text": "hello world",
                    "filename": "test.txt",
                    "file_type": "txt",
                    "chunk_metadata_json": "{}",
                    "SCORE": 0.75,
                }
            ]
        )

        results = idx._rows_to_chunks(df, score_field="_score")

        assert len(results) == 1
        assert results[0].score == pytest.approx(0.75)

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

    def test_search_hybrid_uses_configured_initial_recall_window(
        self, make_index
    ) -> None:
        """search_hybrid 内部 text/dense/fusion 都使用 chunk_initial_recall_n。"""
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

        assert chunk_table.last_hybrid_text_topn == 1024
        assert chunk_table.last_hybrid_dense_topn == 1024
        assert chunk_table.last_hybrid_fusion_topn == 1024

    def test_search_hybrid_passes_text_dense_thresholds_and_fusion_config(
        self, make_index
    ) -> None:
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

        assert chunk_table.last_hybrid_text_kwargs["extra_options"] == {
            "minimum_should_match": 0.3
        }
        assert chunk_table.last_hybrid_dense_kwargs["threshold"] == 0.2
        assert chunk_table.last_fusion_kwargs["fusion_params"] == {
            "weights": "0.05,0.95",
            "normalize": "atan",
        }

    def test_search_hybrid_can_disable_position_prior(self, make_index) -> None:
        config = ChunkHybridRetrievalConfig(position_prior_enabled=False)
        _, idx = make_index(chunk_hybrid_config=config)
        asset = _make_asset()
        chunks = [
            _make_chunk(
                document_id="doc_1",
                index=0,
                text="hello world",
                vector=[0.0, 0.0, 0.0, 0.0],
            ),
            _make_chunk(
                document_id="doc_1",
                index=100,
                text="no match",
                vector=[1.0, 0.0, 0.0, 0.0],
            ),
        ]
        idx.index_document(asset, chunks)

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=2)

        assert [chunk.chunk_id for chunk in results] == [
            "chunk_doc_1_100",
            "chunk_doc_1_0",
        ]

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

    def test_search_hybrid_text_fields_use_chunk_fielded_text(
        self, make_index
    ) -> None:
        """search_hybrid 的 text 分支使用 chunk fielded text 多字段。"""
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
        assert (
            chunk_table.last_hybrid_text_fields
            == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
        )

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

    def test_search_hybrid_position_prior_prefers_earlier_chunk(
        self, make_index
    ) -> None:
        """fusion 基础分相同时，chunk_index 更小者因位置先验排在前面。"""
        _, idx = make_index()
        asset = _make_asset()
        # 两个 chunk 的 text 和 vector 完全相同，fusion 分相同；
        # chunk_index=5 的先验 boost < chunk_index=0 的 boost。
        chunks = [
            _make_chunk(
                document_id="doc_1",
                index=5,
                text="hello world",
                vector=[1.0, 0.0, 0.0, 0.0],
            ),
            _make_chunk(
                document_id="doc_1",
                index=0,
                text="hello world",
                vector=[1.0, 0.0, 0.0, 0.0],
            ),
        ]
        idx.index_document(asset, chunks)

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=2)

        assert len(results) == 2
        assert results[0].chunk_id == "chunk_doc_1_0"  # index=0
        assert results[1].chunk_id == "chunk_doc_1_5"  # index=5

    def test_search_hybrid_position_prior_does_not_override_large_score_gap(
        self, make_index
    ) -> None:
        """fusion 分差距大于最大 boost(0.03) 时，位置先验不能反转排名。"""
        _, idx = make_index()
        asset = _make_asset()
        # chunk 0：纯 text 匹配（无 dense），fusion 分较低
        # chunk 1：高 dense 分（无 text 匹配），fusion 分较高
        chunks = [
            _make_chunk(
                document_id="doc_1",
                index=0,
                text="hello world",
                vector=[0.0, 0.0, 0.0, 0.0],
            ),
            _make_chunk(
                document_id="doc_1",
                index=100,
                text="no match",
                vector=[1.0, 0.0, 0.0, 0.0],
            ),
        ]
        idx.index_document(asset, chunks)

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=2)

        assert len(results) == 2
        # dense-only chunk(index=100) 的 fusion 分应远超 text-only + 位置先验
        assert results[0].chunk_id == "chunk_doc_1_100"

    def test_search_hybrid_position_prior_not_leaked_to_metadata(
        self, make_index
    ) -> None:
        """位置先验内部字段 _chunk_index 不泄漏到返回的 metadata 中。"""
        _, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        results = idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)

        assert len(results) == 1
        assert "_chunk_index" not in results[0].metadata
        assert "chunk_index" not in results[0].metadata

    def test_search_hybrid_fusion_contract_matches_sdk(self, make_index) -> None:
        """fusion 调用必须使用 Thrift SDK 文档支持的参数形状。"""
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)

        chunk_table = client.get_database("default_db").get_table("chunks")
        fk = chunk_table.last_fusion_kwargs
        assert fk is not None
        # Only these three keys are allowed — matches Thrift SDK fusion(method, topn, fusion_params)
        assert set(fk.keys()) == {"method", "topn", "fusion_params"}
        # method: str
        assert isinstance(fk["method"], str)
        assert fk["method"] == "weighted_sum"
        # topn: int (not positional, but keyword argument)
        assert isinstance(fk["topn"], int)
        # fusion_params: dict (not extra positional argument)
        assert isinstance(fk["fusion_params"], dict)
        assert "weights" in fk["fusion_params"]

    def test_search_hybrid_fusion_error_propagates(self, make_index) -> None:
        """fusion 阶段抛异常时，错误应透传为 ProcessingError。"""
        client, idx = make_index()
        asset = _make_asset()
        chunk = _make_chunk(text="hello world", vector=[1.0, 0.0, 0.0, 0.0])
        idx.index_document(asset, [chunk])

        # monkeypatch: 让 _FakeQueryBuilder 的 _to_pl_fusion 在 fusion 阶段失败
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import conftest as test_conftest

        _FakeQueryBuilder = test_conftest._FakeQueryBuilder

        original = _FakeQueryBuilder._to_pl_fusion

        def _failing_fusion(self: Any) -> Any:
            raise RuntimeError("Infinity internal fusion error")

        _FakeQueryBuilder._to_pl_fusion = _failing_fusion  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="Infinity internal fusion error"):
                idx.search_hybrid("hello", [1.0, 0.0, 0.0, 0.0], top_k=5)
        finally:
            _FakeQueryBuilder._to_pl_fusion = original  # type: ignore[assignment]


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
