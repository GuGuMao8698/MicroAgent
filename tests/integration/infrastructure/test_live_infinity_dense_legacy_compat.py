"""Focused live Infinity validation for legacy chunk table compatibility.

Verifies that ``InfinityDenseVectorIndex`` correctly handles a chunk table
containing only legacy columns (``text``, ``filename``) and creates only the
corresponding fulltext indexes, skipping new columns (``filename_kwd``,
``content_tks``) that do not exist in the legacy schema.

Gated behind ``--run-live-infinity``.
"""

from __future__ import annotations

from uuid import uuid4

import infinity
import pytest
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.config import Settings
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)
from tests.infinity_test_support import drop_infinity_tables

pytestmark = pytest.mark.live_infinity

# Legacy chunk table schema — only columns that existed before the
# filename_kwd / content_tks / content_sm_tks / filename_tks migration.
_LEGACY_CHUNK_COLUMNS = {
    "chunk_id": {"type": "varchar", "constraints": ["primary key"]},
    "document_id": {"type": "varchar"},
    "chunk_index": {"type": "integer"},
    "text": {"type": "varchar"},
    "vec": {"type": "vector,8,float"},
    "filename": {"type": "varchar"},
    "file_type": {"type": "varchar"},
    "chunk_metadata_json": {"type": "varchar"},
    "embedding_provider": {"type": "varchar"},
    "embedding_model": {"type": "varchar"},
    "embedding_dimensions": {"type": "integer"},
}

_LEGACY_EMBEDDING_SIGNATURE = {
    "provider": "test",
    "model": "legacy-compat",
    "dimensions": 8,
}


def test_legacy_chunk_table_creates_only_legacy_indexes(
    app_settings: Settings,
) -> None:
    """Connecting to a pre-existing legacy chunk table should only create
    fulltext indexes for columns that actually exist.
    """
    unique_suffix = uuid4().hex[:12]
    doc_table = f"test_legacy_doc_{unique_suffix}"
    chunk_table = f"test_legacy_chunk_{unique_suffix}"

    client = infinity.connect(
        NetworkAddress(app_settings.infinity_host, app_settings.infinity_port),
    )
    db = client.get_database(app_settings.infinity_database)
    index: InfinityDenseVectorIndex | None = None

    try:
        # Manually create a table with only legacy columns.
        db.create_table(chunk_table, _LEGACY_CHUNK_COLUMNS, ConflictType.Error)
        # 最小 schema，仅满足 Infinity 非空列约束；生产代码会用 ConflictType.Ignore 覆盖。
        db.create_table(
            doc_table,
            {"document_id": {"type": "varchar", "constraints": ["primary key"]}},
            ConflictType.Error,
        )

        index = InfinityDenseVectorIndex(
            host=app_settings.infinity_host,
            port=app_settings.infinity_port,
            database=app_settings.infinity_database,
            document_table=doc_table,
            chunk_table=chunk_table,
            embedding_dimensions=8,
            embedding_signature=_LEGACY_EMBEDDING_SIGNATURE,
        )

        # _ensure_tables has run; verify fulltext indexes.
        table = db.get_table(chunk_table)
        index_names = _list_index_names(table)

        # Legacy columns — indexes must exist.
        expected_legacy = {
            f"{chunk_table}_text_fulltext_idx",
            f"{chunk_table}_filename_fulltext_idx",
        }
        assert expected_legacy.issubset(index_names), (
            f"Missing legacy fulltext indexes. "
            f"Expected {expected_legacy}, got {index_names}"
        )

        # New columns — indexes must NOT exist because those columns are absent.
        new_column_indexes = {
            f"{chunk_table}_filename_kwd_fulltext_idx",
            f"{chunk_table}_filename_tks_fulltext_idx",
            f"{chunk_table}_content_tks_fulltext_idx",
            f"{chunk_table}_content_sm_tks_fulltext_idx",
        }
        assert new_column_indexes.isdisjoint(index_names), (
            f"New-column indexes should not be created for legacy table. "
            f"Unexpected indexes: {new_column_indexes & index_names}"
        )

    finally:
        # 断开 InfinityDenseVectorIndex 内部连接，防止 assertion 失败时泄漏。
        if index is not None:
            try:
                index.disconnect()
            except Exception:
                pass
        # Best-effort cleanup.
        drop_infinity_tables(
            app_settings,
            [
                chunk_table,
                doc_table,
                f"{doc_table}_datasets",
                f"{doc_table}_dataset_bindings",
            ],
        )
        try:
            client.disconnect()
        except Exception:
            pass


# 复制而非 import 生产代码的私有方法，避免测试依赖内部 API。
def _list_index_names(table: object) -> set[str]:
    """Extract index names from an Infinity RemoteTable."""
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
