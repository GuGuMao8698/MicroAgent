from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import infinity
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.config import Settings

_LIVE_TABLE_PREFIXES = (
    "documents_",
    "chunks_",
    "graph_entities_",
    "graph_relationships_",
)
_REGISTERED_TABLES: list[tuple[Settings, list[str]]] = []
_REGISTERED_TABLES_LOCK = threading.Lock()


def build_test_scope_suffix(tmp_path: Path, *, salt: str = "") -> str:
    base_name = tmp_path.name.replace("-", "_")
    path_hash = hashlib.sha1(f"{tmp_path}:{salt}".encode("utf-8")).hexdigest()[:10]
    return f"{base_name}_{path_hash}"


def assign_isolated_infinity_tables(
    settings: Settings,
    tmp_path: Path,
    *,
    salt: str = "",
) -> Settings:
    scope_suffix = build_test_scope_suffix(tmp_path, salt=salt)
    settings.infinity_document_table = f"documents_{scope_suffix}"
    settings.infinity_chunk_table = f"chunks_{scope_suffix}"
    settings.infinity_graph_entity_table = f"graph_entities_{scope_suffix}"
    settings.infinity_graph_relationship_table = f"graph_relationships_{scope_suffix}"
    return settings


def infinity_table_names_for(settings: Settings) -> list[str]:
    document_table = settings.infinity_document_table
    return [
        document_table,
        settings.infinity_chunk_table,
        f"{document_table}_datasets",
        f"{document_table}_dataset_bindings",
        settings.infinity_graph_entity_table,
        settings.infinity_graph_relationship_table,
    ]


def drop_infinity_tables(settings: Settings, table_names: list[str]) -> None:
    client = infinity.connect(
        NetworkAddress(settings.infinity_host, settings.infinity_port),
    )
    try:
        database = client.get_database(settings.infinity_database)
        for table_name in table_names:
            try:
                database.drop_table(table_name, ConflictType.Ignore)
            except Exception:
                pass
    finally:
        client.disconnect()


def register_infinity_table_cleanup(settings: Settings) -> Settings:
    table_names = infinity_table_names_for(settings)
    with _REGISTERED_TABLES_LOCK:
        _REGISTERED_TABLES.append((settings, table_names))
    return settings


def drop_registered_infinity_tables() -> None:
    with _REGISTERED_TABLES_LOCK:
        registered = list(reversed(_REGISTERED_TABLES))
        _REGISTERED_TABLES.clear()

    for settings, table_names in registered:
        try:
            drop_infinity_tables(settings, table_names)
        except Exception:
            pass


def clear_registered_infinity_tables() -> None:
    with _REGISTERED_TABLES_LOCK:
        _REGISTERED_TABLES.clear()


def select_live_test_tables(table_names: list[str]) -> list[str]:
    return sorted(
        name
        for name in table_names
        if any(name.startswith(prefix) for prefix in _LIVE_TABLE_PREFIXES)
    )
