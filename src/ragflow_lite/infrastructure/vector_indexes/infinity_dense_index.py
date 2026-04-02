"""V1 检索路径使用的 Infinity 稠密向量索引。

通过 Infinity 的 thrift API 落盘文档元数据和稠密向量，并在归一化后的
embedding 上执行内积检索。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import infinity
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk, RetrievedChunk

logger = logging.getLogger(__name__)

EmbeddingSignature = dict[str, str | int | None]


class InfinityDenseVectorIndex:
    """基于 Infinity 的稠密向量索引，维护文档表和 chunk 表。"""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        document_table: str,
        chunk_table: str,
        embedding_dimensions: int,
        embedding_signature: EmbeddingSignature,
        client: Any | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._document_table = document_table
        self._chunk_table = chunk_table
        self._dimensions = embedding_dimensions
        self._embedding_signature = embedding_signature

        if client is not None:
            self._client = client
        else:
            self._client = infinity.connect(
                NetworkAddress(host, port),
            )
        self._db = self._client.get_database(database)
        self._ensure_tables()

    def disconnect(self) -> None:
        """断开与 Infinity 的连接。"""
        self._client.disconnect()

    # ------------------------------------------------------------------
    # VectorIndex 协议实现
    # ------------------------------------------------------------------

    def index_document(
        self,
        asset: DocumentAsset,
        embedded_chunks: list[EmbeddedChunk],
    ) -> None:
        """把文档元数据和 embedding 后的 chunk 写入 Infinity。"""
        self._validate_embedding_signature(embedded_chunks)

        # 先删后写文档行，保证重建同一 document_id 时不会残留旧元数据。
        doc_row: dict[str, Any] = {
            "document_id": asset.document_id,
            "filename": asset.filename,
            "file_type": asset.file_type,
            "storage_path": str(asset.storage_path),
            "size_bytes": asset.size_bytes,
            "created_at": asset.created_at.isoformat(),
            "embedding_provider": self._embedding_signature["provider"],
            "embedding_model": self._embedding_signature["model"],
            "embedding_dimensions": self._embedding_signature["dimensions"],
            "parser_metadata_json": "",
        }
        doc_table = self._db.get_table(self._document_table)
        self._delete_document_rows(doc_table, asset.document_id)
        doc_table.insert([doc_row])

        # chunk 也按“先删旧再写新”处理，避免覆盖写入后混入旧 chunk。
        chunk_table = self._db.get_table(self._chunk_table)
        self._delete_chunk_rows(chunk_table, asset.document_id)

        if not embedded_chunks:
            return

        chunk_rows = [self._chunk_to_row(chunk, asset) for chunk in embedded_chunks]
        chunk_table.insert(chunk_rows)

    def delete_document(self, document_id: str) -> None:
        """删除文档及其对应的所有 chunk。"""
        doc_table = self._db.get_table(self._document_table)
        chunk_table = self._db.get_table(self._chunk_table)
        self._delete_chunk_rows(chunk_table, document_id)
        self._delete_document_rows(doc_table, document_id)

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        """使用内积在稠密向量上检索 chunk。"""
        if len(query_vector) != self._dimensions:
            raise ProcessingError(
                f"Query vector dimension {len(query_vector)} does not match "
                f"expected {self._dimensions}."
            )

        chunk_table = self._db.get_table(self._chunk_table)
        result_tuple = (
            chunk_table.match_dense(
                vector_column_name="vec",
                embedding_data=query_vector,
                embedding_data_type="float",
                distance_type="ip",
                topn=top_k,
            )
            .output(
                [
                    "chunk_id",
                    "document_id",
                    "text",
                    "filename",
                    "file_type",
                    "chunk_metadata_json",
                    "embedding_provider",
                    "embedding_model",
                    "embedding_dimensions",
                    "_distance",
                ]
            )
            .to_pl()
        )

        return self._materialize_chunk_query_results(
            result_tuple,
            score_field="_distance",
            validate_embedding_signature=True,
        )

    # ------------------------------------------------------------------
    # 表管理
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """确保文档表和 chunk 表存在，不存在时即时创建。"""
        doc_columns = {
            "document_id": {"type": "varchar", "constraints": ["primary key"]},
            "filename": {"type": "varchar"},
            "file_type": {"type": "varchar"},
            "storage_path": {"type": "varchar"},
            "size_bytes": {"type": "integer"},
            "created_at": {"type": "varchar"},
            "embedding_provider": {"type": "varchar"},
            "embedding_model": {"type": "varchar"},
            "embedding_dimensions": {"type": "integer"},
            "parser_metadata_json": {"type": "varchar"},
        }
        self._db.create_table(self._document_table, doc_columns, ConflictType.Ignore)

        chunk_columns = {
            "chunk_id": {"type": "varchar", "constraints": ["primary key"]},
            "document_id": {"type": "varchar"},
            "chunk_index": {"type": "integer"},
            "text": {"type": "varchar"},
            "vec": {"type": f"vector,{self._dimensions},float"},
            "filename": {"type": "varchar"},
            "file_type": {"type": "varchar"},
            "chunk_metadata_json": {"type": "varchar"},
            "embedding_provider": {"type": "varchar"},
            "embedding_model": {"type": "varchar"},
            "embedding_dimensions": {"type": "integer"},
        }
        self._db.create_table(self._chunk_table, chunk_columns, ConflictType.Ignore)

        self._validate_chunk_table_dimensions()
        self._ensure_fulltext_index()

    def _validate_chunk_table_dimensions(self) -> None:
        """校验 chunk 表中的 `vec` 列维度是否与当前配置一致。"""
        chunk_table = self._db.get_table(self._chunk_table)
        df = self._columns_dataframe(chunk_table.show_columns())
        for row in df.iter_rows(named=True):
            if row.get("column_name") == "vec" or row.get("name") == "vec":
                col_type = str(row.get("column_type", row.get("type", "")))
                if str(self._dimensions) not in col_type:
                    raise RuntimeError(
                        f"Chunk table '{self._chunk_table}' vector column has type "
                        f"'{col_type}' which does not match expected "
                        f"{self._dimensions} dimensions. "
                        "Drop and recreate the table, or update the configuration."
                    )
                return
        raise RuntimeError(
            f"Chunk table '{self._chunk_table}' does not contain a 'vec' column. "
            f"The existing table schema is incompatible. "
            f"Drop and recreate the table to proceed."
        )

    def _ensure_fulltext_index(self) -> None:
        """对 chunk 表的 text 列幂等创建全文索引。"""
        from infinity.index import IndexType

        index_name = f"{self._chunk_table}_text_fulltext_idx"
        chunk_table = self._db.get_table(self._chunk_table)
        try:
            chunk_table.create_index(
                index_name,
                IndexType.FullText,
                {"text"},
            )
        except Exception:
            logger.debug("Fulltext index %s may already exist, skipping.", index_name)

    # ------------------------------------------------------------------
    # 全文检索
    # ------------------------------------------------------------------

    def search_text(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """使用全文匹配在 chunk 的 text 列上检索。"""
        chunk_table = self._db.get_table(self._chunk_table)
        result_tuple = (
            chunk_table.match_text(
                fields="text",
                matching_text=query,
                topn=top_k,
            )
            .output(
                [
                    "chunk_id",
                    "document_id",
                    "text",
                    "filename",
                    "file_type",
                    "chunk_metadata_json",
                    "_score",
                ]
            )
            .to_pl()
        )

        return self._materialize_chunk_query_results(
            result_tuple,
            score_field="_score",
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _columns_dataframe(columns_info: Any) -> Any:
        """兼容 Infinity SDK 返回 DataFrame 或 `(DataFrame, extra)`。"""
        if isinstance(columns_info, tuple):
            return columns_info[0]
        return columns_info

    def _materialize_chunk_query_results(
        self,
        result_tuple: tuple[Any, Any],
        *,
        score_field: str,
        validate_embedding_signature: bool = False,
    ) -> list[RetrievedChunk]:
        """将 Infinity 查询结果映射为 `RetrievedChunk` 列表。"""
        df, _extra = result_tuple
        if df.is_empty():
            return []

        if validate_embedding_signature:
            for row in df.iter_rows(named=True):
                self._check_row_embedding_signature(row)

        return self._rows_to_chunks(df, score_field=score_field)

    def _rows_to_chunks(self, df: Any, *, score_field: str) -> list[RetrievedChunk]:
        """将 polars DataFrame 行映射为 `RetrievedChunk` 列表。"""
        results: list[RetrievedChunk] = []
        for row in df.iter_rows(named=True):
            metadata = self._parse_json(row.get("chunk_metadata_json", ""))
            metadata["filename"] = row.get("filename")
            metadata["file_type"] = row.get("file_type")
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    text=row["text"],
                    score=float(row[score_field]),
                    metadata=metadata,
                )
            )
        return results

    def _validate_embedding_signature(self, chunks: list[EmbeddedChunk]) -> None:
        """校验 chunk 向量维度是否与当前 embedding 配置一致。"""
        for chunk in chunks:
            if len(chunk.vector) != self._dimensions:
                raise ProcessingError(
                    f"Chunk '{chunk.chunk_id}' vector dimension "
                    f"{len(chunk.vector)} does not match expected "
                    f"{self._dimensions}."
                )

    def _check_row_embedding_signature(self, row: dict[str, Any]) -> None:
        """当检索结果的 embedding 签名不匹配时抛出 `ProcessingError`。"""
        sig = self._embedding_signature
        for key, expected_val in [
            ("embedding_provider", sig["provider"]),
            ("embedding_model", sig["model"]),
            ("embedding_dimensions", sig["dimensions"]),
        ]:
            actual = row.get(key)
            if actual != expected_val:
                raise ProcessingError(
                    f"Embedding signature mismatch in chunk table: "
                    f"{key} is '{actual}', expected '{expected_val}'. "
                    f"The Infinity chunk data was written with a different embedding "
                    f"configuration. Drop and rebuild the chunk table, or re-ingest "
                    f"all documents with the current embedding settings."
                )

    def _chunk_to_row(
        self, chunk: EmbeddedChunk, asset: DocumentAsset
    ) -> dict[str, Any]:
        """把 `EmbeddedChunk` 转成 Infinity 可写入的行数据。"""
        metadata_json = json.dumps(chunk.metadata, ensure_ascii=False)
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.index,
            "text": chunk.text,
            "vec": chunk.vector,
            "filename": asset.filename,
            "file_type": asset.file_type,
            "chunk_metadata_json": metadata_json,
            "embedding_provider": self._embedding_signature["provider"],
            "embedding_model": self._embedding_signature["model"],
            "embedding_dimensions": self._embedding_signature["dimensions"],
        }

    @staticmethod
    def _delete_document_rows(doc_table: Any, document_id: str) -> None:
        doc_table.delete(f"document_id = '{document_id}'")

    @staticmethod
    def _delete_chunk_rows(chunk_table: Any, document_id: str) -> None:
        chunk_table.delete(f"document_id = '{document_id}'")

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
