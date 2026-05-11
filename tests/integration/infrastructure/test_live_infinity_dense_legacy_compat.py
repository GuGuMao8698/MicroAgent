"""Focused live Infinity validation: legacy chunk table rejection.

Verifies that ``InfinityDenseVectorIndex`` rejects a chunk table that is
missing the required auxiliary text columns (``filename_kwd``,
``filename_tks``, ``content_tks``, ``content_sm_tks``).

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


def test_legacy_chunk_table_is_rejected_when_auxiliary_fields_are_missing(
    app_settings: Settings,
) -> None:
    """Constructing ``InfinityDenseVectorIndex`` against a legacy chunk table
    that lacks the required auxiliary text columns must raise ``RuntimeError``.
    """
    unique_suffix = uuid4().hex[:12]
    doc_table = f"test_legacy_doc_{unique_suffix}"
    chunk_table = f"test_legacy_chunk_{unique_suffix}"

    client = infinity.connect(
        NetworkAddress(app_settings.infinity_host, app_settings.infinity_port),
    )
    db = client.get_database(app_settings.infinity_database)

    try:
        # Manually create a table with only legacy columns.
        db.create_table(chunk_table, _LEGACY_CHUNK_COLUMNS, ConflictType.Error)
        # 最小 schema，仅满足 Infinity 非空列约束；生产代码会用 ConflictType.Ignore 覆盖。
        db.create_table(
            doc_table,
            {"document_id": {"type": "varchar", "constraints": ["primary key"]}},
            ConflictType.Error,
        )

        with pytest.raises(
            RuntimeError,
            match="Chunk table .* is missing required auxiliary text columns",
        ):
            InfinityDenseVectorIndex(
                host=app_settings.infinity_host,
                port=app_settings.infinity_port,
                database=app_settings.infinity_database,
                document_table=doc_table,
                chunk_table=chunk_table,
                embedding_dimensions=8,
                embedding_signature=_LEGACY_EMBEDDING_SIGNATURE,
            )

    finally:
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
