from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from infinity.common import ConflictType, InfinityException
from infinity.index import IndexInfo, IndexType

from ragflow_lite.infrastructure.evidence.psi_node_fields import (
    PSI_NODE_MATCH_TEXT_FIELDS,
    projection_row_id,
)

_DDL_RETRY_ATTEMPTS = 5
_DDL_RETRY_DELAY_SECONDS = 0.05
_REQUIRED_COLUMNS = frozenset(
    {
        "psi_node_id",
        "projection_row_id",
        "build_id",
        "document_id",
        "layer",
        "node_type",
        "abstract_type",
        "source_chunk_ids_json",
        "embedding_text",
        "psi_node_label_kwd",
        "psi_node_label_tks",
        "psi_keyword_tks",
        "psi_summary_tks",
        "psi_leaf_text_tks",
        "text_tks",
        "metadata_json",
        "vec",
    }
)


@dataclass(frozen=True)
class PsiNodeInfinityConfig:
    table_name: str = "psi_nodes"
    initial_recall_n: int = 1024
    text_weight: float = 0.05
    dense_weight: float = 0.95
    minimum_should_match: float = 0.3
    dense_similarity_threshold: float = 0.2
    fusion_normalize: str = "atan"

    def __post_init__(self) -> None:
        if not self.table_name:
            raise ValueError("Psi node table_name must be non-empty")
        if self.initial_recall_n < 1:
            raise ValueError("Psi node initial_recall_n must be >= 1")
        if self.text_weight < 0 or self.dense_weight < 0:
            raise ValueError("Psi node hybrid weights must be non-negative")
        if self.text_weight == 0 and self.dense_weight == 0:
            raise ValueError("at least one Psi node hybrid weight must be positive")
        if not 0 <= self.minimum_should_match <= 1:
            raise ValueError("minimum_should_match must be between 0 and 1")
        if self.dense_similarity_threshold < 0:
            raise ValueError("dense_similarity_threshold must be >= 0")


@dataclass(slots=True)
class PsiNodeHit:
    psi_node_id: str
    build_id: str
    document_id: str
    layer: int
    node_type: str
    abstract_type: str | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class InfinityPsiNodeIndex:
    output_fields = [
        "projection_row_id",
        "psi_node_id",
        "build_id",
        "document_id",
        "layer",
        "node_type",
        "abstract_type",
        "metadata_json",
        "_score",
    ]

    def __init__(
        self,
        *,
        client: Any,
        database: str,
        embedding_dimensions: int,
        config: PsiNodeInfinityConfig | None = None,
        client_lock: Any | None = None,
    ) -> None:
        self._lock = client_lock or threading.RLock()
        with self._lock:
            self._db = client.get_database(database)
        if embedding_dimensions < 1:
            raise ValueError("Psi node embedding_dimensions must be >= 1")
        self._embedding_dimensions = embedding_dimensions
        self._config = config or PsiNodeInfinityConfig()
        self._ensure_table()

    @property
    def table_name(self) -> str:
        return self._config.table_name

    def upsert_nodes(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        build_ids = {str(row.get("build_id", "")) for row in rows}
        if "" in build_ids or len(build_ids) != 1:
            raise ValueError("Psi node projection rows must own one non-empty build_id")
        build_id = next(iter(build_ids))
        with self._lock:
            table = self._db.get_table(self._config.table_name)
            table.delete(_equals_filter("build_id", build_id))
            table.insert(rows)

    def delete_build(self, build_id: str) -> None:
        with self._lock:
            self._db.get_table(self._config.table_name).delete(
                _equals_filter("build_id", build_id)
            )

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._db.get_table(self._config.table_name).delete(
                _equals_filter("document_id", document_id)
            )

    def get_projected_node_ids(
        self, build_id: str, *, layer: int | None = None
    ) -> list[str]:
        filter_expr = _equals_filter("build_id", build_id)
        if layer is not None:
            filter_expr = f"({filter_expr}) AND layer = {int(layer)}"
        with self._lock:
            result = (
                self._db.get_table(self._config.table_name)
                .output(["psi_node_id"])
                .filter(filter_expr)
                .to_pl()
            )
        frame = result[0] if isinstance(result, tuple) else result
        if frame.is_empty():
            return []
        return sorted(str(row["psi_node_id"]) for row in frame.iter_rows(named=True))

    def search_nodes(
        self,
        *,
        sparse_query_text: str,
        query_vector: list[float],
        allowed_projection_row_ids: list[str],
        top_k: int,
    ) -> list[PsiNodeHit]:
        if not allowed_projection_row_ids or top_k <= 0:
            return []
        recall_n = max(top_k, self._config.initial_recall_n)
        with self._lock:
            query = (
                self._db.get_table(self._config.table_name)
                .match_text(
                    fields=",".join(PSI_NODE_MATCH_TEXT_FIELDS),
                    matching_text=sparse_query_text,
                    topn=recall_n,
                    extra_options={
                        "minimum_should_match": _minimum_should_match_option(
                            self._config.minimum_should_match
                        )
                    },
                )
                .match_dense(
                    vector_column_name="vec",
                    embedding_data=query_vector,
                    embedding_data_type="float",
                    distance_type="ip",
                    topn=recall_n,
                    knn_params={
                        "threshold": str(self._config.dense_similarity_threshold)
                    },
                )
                .fusion(
                    "weighted_sum",
                    topn=recall_n,
                    fusion_params={
                        "weights": (
                            f"{self._config.text_weight},{self._config.dense_weight}"
                        ),
                        "normalize": self._config.fusion_normalize,
                    },
                )
                .filter(_in_filter("projection_row_id", allowed_projection_row_ids))
                .output(self.output_fields)
                .to_pl()
            )
        frame = query[0] if isinstance(query, tuple) else query
        if frame.is_empty():
            return []
        return [_hit_from_row(row) for row in frame.iter_rows(named=True)][:top_k]

    def _ensure_table(self) -> None:
        with self._lock:
            columns = {
                "projection_row_id": {
                    "type": "varchar",
                    "constraints": ["primary key"],
                },
                "psi_node_id": {"type": "varchar"},
                "build_id": {"type": "varchar"},
                "document_id": {"type": "varchar"},
                "layer": {"type": "integer"},
                "node_type": {"type": "varchar"},
                "abstract_type": {"type": "varchar"},
                "source_chunk_ids_json": {"type": "varchar"},
                "embedding_text": {"type": "varchar"},
                "psi_node_label_kwd": {"type": "varchar"},
                "psi_node_label_tks": {"type": "varchar"},
                "psi_keyword_tks": {"type": "varchar"},
                "psi_summary_tks": {"type": "varchar"},
                "psi_leaf_text_tks": {"type": "varchar"},
                "text_tks": {"type": "varchar"},
                "metadata_json": {"type": "varchar"},
                "vec": {"type": f"vector,{self._embedding_dimensions},float"},
            }
            _retry_ddl(
                self._db.create_table,
                self._config.table_name,
                columns,
                ConflictType.Ignore,
            )
            table = self._db.get_table(self._config.table_name)
            missing = _REQUIRED_COLUMNS - _column_names(table)
            if missing:
                missing_names = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"Infinity Psi node table '{self._config.table_name}' is missing "
                    f"required column(s): {missing_names}. Drop/recreate the table."
                )
            existing_indexes = _index_names(table)
            for column in _fulltext_columns():
                index_name = f"{self._config.table_name}_{column}_fulltext_idx"
                if index_name not in existing_indexes:
                    _retry_ddl(
                        table.create_index,
                        index_name,
                        IndexInfo(column, IndexType.FullText),
                        ConflictType.Ignore,
                    )


def _fulltext_columns() -> list[str]:
    return [field.split("^", 1)[0] for field in PSI_NODE_MATCH_TEXT_FIELDS]


def _minimum_should_match_option(value: float) -> str:
    return f"{int(value * 100)}%"


def _escape_filter_value(value: str) -> str:
    return value.replace("'", "\\'")


def _equals_filter(field_name: str, value: str) -> str:
    return f"{field_name} = '{_escape_filter_value(value)}'"


def _in_filter(field_name: str, values: list[str]) -> str:
    escaped = ", ".join(f"'{_escape_filter_value(value)}'" for value in values)
    return f"{field_name} IN ({escaped})"


def _hit_from_row(row: dict[str, Any]) -> PsiNodeHit:
    abstract_type = str(row.get("abstract_type") or "") or None
    metadata = _parse_json_object(row.get("metadata_json"))
    metadata.update(
        {
            "retrieval_mode": "psi_node_infinity_hybrid",
            "psi_node_id": str(row.get("psi_node_id") or ""),
            "projection_row_id": str(row.get("projection_row_id") or ""),
        }
    )
    return PsiNodeHit(
        psi_node_id=str(row.get("psi_node_id") or ""),
        build_id=str(row.get("build_id") or ""),
        document_id=str(row.get("document_id") or ""),
        layer=int(row.get("layer") or 0),
        node_type=str(row.get("node_type") or ""),
        abstract_type=abstract_type,
        score=_score(row),
        metadata=metadata,
    )


def allowed_projection_row_ids(build_id: str, node_ids: list[str]) -> list[str]:
    return [projection_row_id(build_id, node_id) for node_id in node_ids]


def _score(row: dict[str, Any]) -> float:
    for field_name in ("_score", "SCORE", "score", "_distance"):
        value = row.get(field_name)
        if value is not None:
            return float(value)
    return 0.0


def _parse_json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _column_names(table: Any) -> set[str]:
    rows = table.show_columns()
    if isinstance(rows, tuple):
        rows = rows[0]
    if isinstance(rows, dict):
        rows = [rows]
    iterator = getattr(rows, "iter_rows", None)
    materialized: Any = iterator(named=True) if callable(iterator) else rows
    names: set[str] = set()
    for row in materialized:  # pyright: ignore[reportGeneralTypeIssues]
        if not isinstance(row, dict):
            continue
        name = row.get("column_name") or row.get("name")
        if name:
            names.add(str(name))
    return names


def _index_names(table: Any) -> set[str]:
    response = table.list_indexes()
    if isinstance(response, tuple):
        response = response[0]
    names = (
        response.get("index_names")
        if isinstance(response, dict)
        else getattr(response, "index_names", None)
    )
    return {str(name) for name in names or []}


def _retry_ddl(operation: Any, *args: Any) -> Any:
    for attempt in range(_DDL_RETRY_ATTEMPTS):
        try:
            return operation(*args)
        except InfinityException as exc:
            if "Resource busy" not in str(getattr(exc, "error_msg", "") or exc):
                raise
            if attempt + 1 >= _DDL_RETRY_ATTEMPTS:
                raise
            time.sleep(_DDL_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")
