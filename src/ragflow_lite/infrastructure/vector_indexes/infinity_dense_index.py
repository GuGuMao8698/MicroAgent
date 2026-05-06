"""V1 检索路径使用的 Infinity 稠密向量索引。

通过 Infinity 的 thrift API 落盘文档元数据和稠密向量，并在归一化后的
embedding 上执行内积检索。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import infinity
from infinity.common import ConflictType, NetworkAddress, SortType
from infinity.index import IndexInfo, IndexType

from ragflow_lite.domain.errors import (
    DatasetAlreadyExistsError,
    DatasetNotEmptyError,
    DatasetNotFoundError,
    DocumentNotFoundError,
    ProcessingError,
)
from ragflow_lite.domain.models import (
    Dataset,
    DocumentAsset,
    EmbeddedChunk,
    IndexedDocument,
    RetrievedChunk,
)
from ragflow_lite.infrastructure.vector_indexes import chunk_text_fields
from ragflow_lite.infrastructure.vector_indexes.chunk_text_fields import (
    CHUNK_FIELD_MATCH_TEXT_FIELDS,
)

logger = logging.getLogger(__name__)

EmbeddingSignature = dict[str, str | int | None]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ChunkHybridRetrievalConfig:
    """Infinity hybrid retrieval settings for chunk search."""

    initial_recall_n: int = 1024
    text_weight: float = 0.05
    dense_weight: float = 0.95
    minimum_should_match: float = 0.3
    dense_similarity_threshold: float = 0.2
    fusion_normalize: str = "atan"
    position_prior_weight: float = 0.03
    position_prior_enabled: bool = True
    match_text_fields: str = CHUNK_FIELD_MATCH_TEXT_FIELDS

    def __post_init__(self) -> None:
        if self.initial_recall_n < 1:
            raise ValueError("initial_recall_n must be >= 1")
        if self.text_weight < 0 or self.dense_weight < 0:
            raise ValueError("chunk hybrid weights must be non-negative")
        if self.text_weight == 0 and self.dense_weight == 0:
            raise ValueError("at least one chunk hybrid weight must be positive")
        if not 0 <= self.minimum_should_match <= 1:
            raise ValueError("minimum_should_match must be between 0 and 1")
        if self.dense_similarity_threshold < 0:
            raise ValueError("dense_similarity_threshold must be >= 0")
        if self.position_prior_weight < 0:
            raise ValueError("position_prior_weight must be >= 0")

    @property
    def fusion_weights(self) -> str:
        return f"{self.text_weight},{self.dense_weight}"


def _dense_knn_params(similarity_threshold: float) -> dict[str, str]:
    """Build Infinity SDK-compatible dense-match optional parameters."""
    return {"threshold": str(similarity_threshold)}


def _minimum_should_match_option(minimum_should_match: float) -> str:
    """Build Infinity fulltext option using the server's percent format."""
    return f"{int(minimum_should_match * 100)}%"


class InfinityDenseVectorIndex:
    """基于 Infinity 的稠密向量索引，维护文档表、chunk 表、dataset 表和 binding 表。"""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        document_table: str,
        chunk_table: str,
        embedding_dimensions: int,
        embedding_signature: EmbeddingSignature,
        chunk_hybrid_config: ChunkHybridRetrievalConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._document_table = document_table
        self._chunk_table = chunk_table
        self._dimensions = embedding_dimensions
        self._embedding_signature = embedding_signature
        self._chunk_hybrid_config = chunk_hybrid_config or ChunkHybridRetrievalConfig()

        if client is not None:
            self._client = client
        else:
            self._client = infinity.connect(
                NetworkAddress(host, port),
            )
        self._db: Any = self._client.get_database(database)
        self._datasets_table = f"{document_table}_datasets"
        self._dataset_bindings_table = f"{document_table}_dataset_bindings"
        self._ensure_tables()

    def disconnect(self) -> None:
        """断开与 Infinity 的连接。"""
        self._client.disconnect()

    @property
    def client(self) -> Any:
        """底层 Infinity client，供其他组件复用同一连接。"""
        return self._client

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
            "parser_metadata_json": json.dumps(asset.metadata, ensure_ascii=False),
        }
        doc_table = self._db.get_table(self._document_table)
        self._delete_document_rows(doc_table, asset.document_id)
        doc_table.insert([doc_row])

        # chunk 也按"先删旧再写新"处理，避免覆盖写入后混入旧 chunk。
        chunk_table = self._db.get_table(self._chunk_table)
        self._delete_chunk_rows(chunk_table, asset.document_id)

        if not embedded_chunks:
            return

        chunk_rows = [self._chunk_to_row(chunk, asset) for chunk in embedded_chunks]
        chunk_table.insert(chunk_rows)

    def delete_document(self, document_id: str) -> None:
        """删除文档及其对应的所有 chunk 和 dataset binding。"""
        doc_table = self._db.get_table(self._document_table)
        chunk_table = self._db.get_table(self._chunk_table)
        self._delete_chunk_rows(chunk_table, document_id)
        self._delete_document_rows(doc_table, document_id)
        # 清理该文档的 dataset binding。
        self._delete_binding_rows(document_id)

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        """使用内积在稠密向量上检索 chunk。"""
        self._validate_query_dimensions(query_vector)

        chunk_table = self._db.get_table(self._chunk_table)
        result_tuple = (
            chunk_table.match_dense(
                vector_column_name="vec",
                embedding_data=query_vector,
                embedding_data_type="float",
                distance_type="ip",
                topn=top_k,
            )
            .output(self._chunk_output_columns("_distance"))
            .to_pl()
        )

        return self._materialize_chunk_query_results(
            result_tuple,
            score_field="_distance",
            validate_embedding_signature=True,
        )

    def search_hybrid(
        self, query: str, query_vector: list[float], top_k: int
    ) -> list[RetrievedChunk]:
        """使用 Infinity 原生 fusion（weighted_sum）并行执行 sparse 全文 + dense 检索。

        参数 ``query`` 视为传给全文分支的 sparse query；dense embedding
        仍来自原始用户 query。

        fusion 结果在 top_k 裁剪前应用基于 ``chunk_index`` 的 bounded
        position prior，使文档前部 chunk 在近邻候选中稍获提升。
        """
        self._validate_query_dimensions(query_vector)

        config = self._chunk_hybrid_config
        initial_recall_n = config.initial_recall_n

        chunk_table = self._db.get_table(self._chunk_table)
        result_tuple = (
            chunk_table.match_text(
                fields=config.match_text_fields,
                matching_text=query,
                topn=initial_recall_n,
                extra_options={
                    "minimum_should_match": _minimum_should_match_option(
                        config.minimum_should_match
                    ),
                },
            )
            .match_dense(
                vector_column_name="vec",
                embedding_data=query_vector,
                embedding_data_type="float",
                distance_type="ip",
                topn=initial_recall_n,
                knn_params=_dense_knn_params(config.dense_similarity_threshold),
            )
            .fusion(
                "weighted_sum",
                topn=initial_recall_n,
                fusion_params={
                    "weights": config.fusion_weights,
                    "normalize": config.fusion_normalize,
                },
            )
            .output(self._chunk_output_columns("_score", include_chunk_index=True))
            .to_pl()
        )

        results = self._materialize_chunk_query_results(
            result_tuple,
            score_field="_score",
            validate_embedding_signature=True,
        )
        if config.position_prior_enabled:
            _apply_position_prior(results, boost=config.position_prior_weight)
        else:
            _drop_position_prior_metadata(results)
        results.sort(key=lambda c: c.score, reverse=True)
        return results[:top_k]

    def get_chunks(self, chunk_ids: list[str]) -> list[RetrievedChunk]:
        """按 chunk_id 批量查找 chunk，不存在的 ID 静默跳过。"""
        if not chunk_ids:
            return []
        unique_chunk_ids = list(dict.fromkeys(chunk_ids))
        escaped_ids = [chunk_id.replace("'", "''") for chunk_id in unique_chunk_ids]
        filter_expr = " OR ".join(
            f"chunk_id = '{chunk_id}'" for chunk_id in escaped_ids
        )
        chunk_table = self._db.get_table(self._chunk_table)
        rows = self._table_rows(
            chunk_table,
            self._chunk_output_columns("_score", include_embedding=False),
            filter_expr=filter_expr,
        )
        chunks_by_id: dict[str, RetrievedChunk] = {}
        for row in rows:
            metadata = self._parse_json(row.get("chunk_metadata_json", ""))
            metadata["filename"] = row.get("filename")
            metadata["file_type"] = row.get("file_type")
            chunks_by_id[row["chunk_id"]] = RetrievedChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                text=row["text"],
                score=0.0,
                metadata=metadata,
            )
        return [
            chunks_by_id[chunk_id]
            for chunk_id in unique_chunk_ids
            if chunk_id in chunks_by_id
        ]

    # ------------------------------------------------------------------
    # 表管理
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        """确保文档表、chunk 表、dataset 表和 binding 表存在。"""
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
            "filename_kwd": {"type": "varchar"},
            "filename_tks": {"type": "varchar"},
            "content_tks": {"type": "varchar"},
            "content_sm_tks": {"type": "varchar"},
        }
        self._db.create_table(self._chunk_table, chunk_columns, ConflictType.Ignore)

        datasets_columns = {
            "dataset_id": {"type": "varchar", "constraints": ["primary key"]},
            "name": {"type": "varchar"},
            "description": {"type": "varchar"},
            "created_at": {"type": "varchar"},
        }
        self._db.create_table(
            self._datasets_table, datasets_columns, ConflictType.Ignore
        )

        bindings_columns = {
            "document_id": {"type": "varchar", "constraints": ["primary key"]},
            "dataset_id": {"type": "varchar"},
            "bound_at": {"type": "varchar"},
        }
        self._db.create_table(
            self._dataset_bindings_table, bindings_columns, ConflictType.Ignore
        )

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
        """对 chunk 表的 text、filename 列幂等创建全文索引。"""
        chunk_table = self._db.get_table(self._chunk_table)
        required_indexes = {
            f"{self._chunk_table}_text_fulltext_idx": "text",
            f"{self._chunk_table}_filename_fulltext_idx": "filename",
            f"{self._chunk_table}_filename_kwd_fulltext_idx": "filename_kwd",
            f"{self._chunk_table}_filename_tks_fulltext_idx": "filename_tks",
            f"{self._chunk_table}_content_tks_fulltext_idx": "content_tks",
            f"{self._chunk_table}_content_sm_tks_fulltext_idx": "content_sm_tks",
        }
        # 迁移窗口：只为表中实际存在的列创建全文索引。
        available_columns = self._chunk_column_names()
        required_indexes = {
            index_name: column_name
            for index_name, column_name in required_indexes.items()
            if column_name in available_columns
        }
        existing_indexes = self._list_index_names(chunk_table)

        for index_name, column_name in required_indexes.items():
            if index_name in existing_indexes:
                continue
            chunk_table.create_index(
                index_name,
                IndexInfo(column_name, IndexType.FullText),
                ConflictType.Ignore,
            )

        existing_indexes = self._list_index_names(chunk_table)
        missing_indexes = [
            index_name
            for index_name in required_indexes
            if index_name not in existing_indexes
        ]
        if missing_indexes:
            raise RuntimeError(
                f"Chunk table '{self._chunk_table}' is missing required fulltext "
                f"indexes: {', '.join(sorted(missing_indexes))}. "
                "Drop and recreate the indexes or repair the Infinity schema."
            )

    def _chunk_column_names(self) -> set[str]:
        """读取 chunk 表当前所有列名，用于迁移窗口兼容。"""
        chunk_table = self._db.get_table(self._chunk_table)
        df = self._columns_dataframe(chunk_table.show_columns())
        names: set[str] = set()
        for row in df.iter_rows(named=True):
            name = row.get("column_name", row.get("name"))
            if name:
                names.add(str(name))
        return names

    def _list_index_names(self, table: Any) -> set[str]:
        """尽量读取 RemoteTable 上的索引列表；缺失接口时退化为空集合。"""
        list_indexes = getattr(table, "list_indexes", None)
        if not callable(list_indexes):
            return set()

        response = list_indexes()
        if response is None:
            return set()
        if isinstance(response, tuple):
            response = response[0]

        names = getattr(response, "index_names", None)
        if names is None and isinstance(response, dict):
            names = response.get("index_names")
        if names is None:
            return set()
        return {str(name) for name in names}

    # ------------------------------------------------------------------
    # DocumentCatalog 协议实现
    # ------------------------------------------------------------------

    def list_documents(self) -> list[IndexedDocument]:
        """列出所有文档，按 created_at 倒序返回。"""
        doc_table = self._db.get_table(self._document_table)
        result_tuple = (
            doc_table.output(
                [
                    "document_id",
                    "filename",
                    "file_type",
                    "size_bytes",
                    "created_at",
                    "parser_metadata_json",
                ]
            )
            .sort([["_row_id", SortType.Desc]])
            .to_pl()
        )
        df = result_tuple[0] if isinstance(result_tuple, tuple) else result_tuple
        if df.is_empty():
            return []
        docs = [self._row_to_indexed_doc(row) for row in df.iter_rows(named=True)]
        return self._enrich_docs_with_dataset_id(docs)

    def get_document(self, document_id: str) -> IndexedDocument:
        """按 document_id 精确读取单个文档，未命中抛 DocumentNotFoundError。"""
        doc_table = self._db.get_table(self._document_table)
        result_tuple = (
            doc_table.output(
                [
                    "document_id",
                    "filename",
                    "file_type",
                    "size_bytes",
                    "created_at",
                    "parser_metadata_json",
                ]
            )
            .filter(_doc_id_filter(document_id))
            .to_pl()
        )
        df = result_tuple[0] if isinstance(result_tuple, tuple) else result_tuple
        if df.is_empty():
            raise DocumentNotFoundError(document_id)
        doc = self._row_to_indexed_doc(df.row(0, named=True))
        doc.dataset_id = self.get_dataset_id_for_document(document_id)
        return doc

    # ------------------------------------------------------------------
    # DatasetStore 协议实现
    # ------------------------------------------------------------------

    def create_dataset(self, name: str, description: str) -> Dataset:
        """创建 dataset，名称做精确唯一约束。"""
        table = self._db.get_table(self._datasets_table)
        # 名称唯一性检查
        for row in self._table_rows(
            table,
            ["dataset_id", "name", "description", "created_at"],
        ):
            if row.get("name") == name:
                raise DatasetAlreadyExistsError(name)
        dataset_id = f"ds_{uuid4().hex}"
        now = _utc_now_iso()
        table.insert(
            [
                {
                    "dataset_id": dataset_id,
                    "name": name,
                    "description": description,
                    "created_at": now,
                }
            ]
        )
        return Dataset(
            dataset_id=dataset_id,
            name=name,
            description=description,
            created_at=now,
        )

    def list_datasets(self) -> list[Dataset]:
        """列出所有 dataset。"""
        table = self._db.get_table(self._datasets_table)
        return [
            Dataset(
                dataset_id=row["dataset_id"],
                name=row["name"],
                description=row["description"],
                created_at=row["created_at"],
            )
            for row in self._table_rows(
                table,
                ["dataset_id", "name", "description", "created_at"],
            )
        ]

    def get_dataset(self, dataset_id: str) -> Dataset:
        """按 dataset_id 读取单个 dataset，未命中抛 DatasetNotFoundError。"""
        table = self._db.get_table(self._datasets_table)
        for row in self._table_rows(
            table,
            ["dataset_id", "name", "description", "created_at"],
            filter_expr=_dataset_id_filter(dataset_id),
        ):
            if row.get("dataset_id") == dataset_id:
                return Dataset(
                    dataset_id=row["dataset_id"],
                    name=row["name"],
                    description=row["description"],
                    created_at=row["created_at"],
                )
        raise DatasetNotFoundError(dataset_id)

    def delete_dataset(self, dataset_id: str) -> None:
        """删除空 dataset；仍有文档归属时抛 DatasetNotEmptyError。"""
        # 先确认 dataset 存在
        self.get_dataset(dataset_id)
        # 检查是否仍有文档绑定
        count = self.get_dataset_document_count(dataset_id)
        if count > 0:
            raise DatasetNotEmptyError(dataset_id)
        table = self._db.get_table(self._datasets_table)
        table.delete(_dataset_id_filter(dataset_id))

    def bind_document(self, document_id: str, dataset_id: str) -> None:
        """将文档绑定到 dataset，单归属语义（upsert）。"""
        # 确认 dataset 存在
        self.get_dataset(dataset_id)
        table = self._db.get_table(self._dataset_bindings_table)
        # 先删除旧绑定（单归属：一个 document_id 只能绑定一个 dataset）
        table.delete(_doc_id_filter(document_id))
        table.insert(
            [
                {
                    "document_id": document_id,
                    "dataset_id": dataset_id,
                    "bound_at": _utc_now_iso(),
                }
            ]
        )

    def unbind_document(self, document_id: str) -> None:
        """解除文档与 dataset 的绑定。"""
        self._delete_binding_rows(document_id)

    def get_dataset_id_for_document(self, document_id: str) -> str | None:
        """查询文档绑定的 dataset_id，未绑定返回 None。"""
        table = self._db.get_table(self._dataset_bindings_table)
        for row in self._table_rows(
            table,
            ["document_id", "dataset_id"],
            filter_expr=_doc_id_filter(document_id),
        ):
            if row.get("document_id") == document_id:
                return row["dataset_id"]
        return None

    def get_document_ids_for_dataset(self, dataset_id: str) -> list[str]:
        """查询 dataset 下所有文档 ID。"""
        table = self._db.get_table(self._dataset_bindings_table)
        return [
            row["document_id"]
            for row in self._table_rows(
                table,
                ["document_id", "dataset_id"],
                filter_expr=_dataset_id_filter(dataset_id),
            )
            if row.get("dataset_id") == dataset_id
        ]

    def get_dataset_document_count(self, dataset_id: str) -> int:
        """查询 dataset 下的文档数量。"""
        return len(self.get_document_ids_for_dataset(dataset_id))

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
            .output(self._chunk_output_columns("_score", include_embedding=False))
            .to_pl()
        )

        return self._materialize_chunk_query_results(
            result_tuple,
            score_field="_score",
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _enrich_docs_with_dataset_id(
        self, docs: list[IndexedDocument]
    ) -> list[IndexedDocument]:
        """批量填充文档的 dataset_id 字段。"""
        bindings_table = self._db.get_table(self._dataset_bindings_table)
        doc_to_ds: dict[str, str] = {}
        for row in self._table_rows(
            bindings_table,
            ["document_id", "dataset_id"],
        ):
            doc_to_ds[row["document_id"]] = row["dataset_id"]
        for doc in docs:
            doc.dataset_id = doc_to_ds.get(doc.document_id)
        return docs

    def _delete_binding_rows(self, document_id: str) -> None:
        """删除指定文档的 dataset binding 行。"""
        table = self._db.get_table(self._dataset_bindings_table)
        table.delete(_doc_id_filter(document_id))

    @staticmethod
    def _columns_dataframe(columns_info: Any) -> Any:
        """兼容 Infinity SDK 返回 DataFrame 或 `(DataFrame, extra)`。"""
        if isinstance(columns_info, tuple):
            return columns_info[0]
        return columns_info

    @staticmethod
    def _query_dataframe(
        table: Any,
        columns: list[str],
        *,
        filter_expr: str | None = None,
    ) -> Any:
        """使用 Infinity query API 读取表数据，避免依赖非兼容的 `table.rows`。"""
        query = table.output(columns)
        if filter_expr is not None:
            query = query.filter(filter_expr)
        result = query.to_pl()
        return result[0] if isinstance(result, tuple) else result

    def _table_rows(
        self,
        table: Any,
        columns: list[str],
        *,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """将表查询结果物化为命名行列表。"""
        df = self._query_dataframe(table, columns, filter_expr=filter_expr)
        if df.is_empty():
            return []
        return list(df.iter_rows(named=True))

    def _validate_query_dimensions(self, query_vector: list[float]) -> None:
        """校验查询向量维度是否与当前 embedding 配置一致。"""
        if len(query_vector) != self._dimensions:
            raise ProcessingError(
                f"Query vector dimension {len(query_vector)} does not match "
                f"expected {self._dimensions}."
            )

    @staticmethod
    def _chunk_output_columns(
        score_field: str,
        *,
        include_embedding: bool = True,
        include_chunk_index: bool = False,
    ) -> list[str]:
        """返回 chunk 查询的输出列名列表。"""
        columns = [
            "chunk_id",
            "document_id",
            "text",
            "filename",
            "file_type",
            "chunk_metadata_json",
        ]
        if include_chunk_index:
            columns.append("chunk_index")
        if include_embedding:
            columns.extend(
                [
                    "embedding_provider",
                    "embedding_model",
                    "embedding_dimensions",
                ]
            )
        columns.append(score_field)
        return columns

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
        resolved_score_field = self._resolve_score_field_name(
            list(getattr(df, "columns", [])),
            requested=score_field,
        )
        for row in df.iter_rows(named=True):
            metadata = self._parse_json(row.get("chunk_metadata_json", ""))
            metadata["filename"] = row.get("filename")
            metadata["file_type"] = row.get("file_type")
            if "chunk_index" in row:
                metadata["_chunk_index"] = row["chunk_index"]
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    text=row["text"],
                    score=float(row[resolved_score_field]),
                    metadata=metadata,
                )
            )
        return results

    @staticmethod
    def _resolve_score_field_name(columns: list[str], *, requested: str) -> str:
        normalized_requested = requested.lstrip("_").lower()
        normalized_aliases = [normalized_requested]
        if normalized_requested == "distance":
            normalized_aliases.append("score")

        candidates: list[str] = []
        for alias in normalized_aliases:
            candidates.extend(
                [
                    f"_{alias}",
                    f"_{alias}".upper(),
                    f"_{alias}".lower(),
                    alias,
                    alias.upper(),
                    alias.lower(),
                ]
            )

        for candidate in dict.fromkeys([requested, *candidates]):
            if candidate in columns:
                return candidate

        for column in columns:
            if column.lstrip("_").lower() in normalized_aliases:
                return column

        raise KeyError(requested)

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
        text_fields = chunk_text_fields.build_chunk_text_fields(
            filename=asset.filename,
            text=chunk.text,
        )
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
            "filename_kwd": text_fields["filename_kwd"],
            "filename_tks": text_fields["filename_tks"],
            "content_tks": text_fields["content_tks"],
            "content_sm_tks": text_fields["content_sm_tks"],
        }

    @staticmethod
    def _delete_document_rows(doc_table: Any, document_id: str) -> None:
        doc_table.delete(_doc_id_filter(document_id))

    @staticmethod
    def _delete_chunk_rows(chunk_table: Any, document_id: str) -> None:
        chunk_table.delete(_doc_id_filter(document_id))

    @staticmethod
    def _row_to_indexed_doc(row: dict[str, Any]) -> IndexedDocument:
        metadata_json = row.get("parser_metadata_json", "")
        metadata: dict[str, Any] = {}
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        return IndexedDocument(
            document_id=row["document_id"],
            filename=row["filename"],
            file_type=row["file_type"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
            metadata=metadata,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}


def _pop_chunk_index(chunk: RetrievedChunk) -> int:
    """从 chunk metadata 中移除并返回 ``_chunk_index``，无效值退化为 0。"""
    raw = chunk.metadata.pop("_chunk_index", None)
    try:
        idx = int(raw)  # type: ignore[arg-type]
        if idx < 0:
            return 0
        return idx
    except (TypeError, ValueError):
        return 0


def _apply_position_prior(
    chunks: list[RetrievedChunk],
    *,
    boost: float = 0.03,
) -> None:
    """对 fusion 结果原地应用 bounded position prior。

    ``adjusted_score = score + boost / (1 + chunk_index)``；
    ``chunk_index`` 缺失、非整数或小于 0 时 boost 按 0 处理。
    """
    for chunk in chunks:
        idx = _pop_chunk_index(chunk)
        chunk.score += boost / (1 + idx)


def _drop_position_prior_metadata(chunks: list[RetrievedChunk]) -> None:
    """Remove internal chunk index metadata when position prior is disabled."""
    for chunk in chunks:
        _pop_chunk_index(chunk)


def _doc_id_filter(document_id: str) -> str:
    """构造 `document_id` 等值 filter 字符串，转义单引号。"""
    escaped = document_id.replace("'", "''")
    return f"document_id = '{escaped}'"


def _dataset_id_filter(dataset_id: str) -> str:
    """构造 `dataset_id` 等值 filter 字符串，转义单引号。"""
    escaped = dataset_id.replace("'", "''")
    return f"dataset_id = '{escaped}'"
