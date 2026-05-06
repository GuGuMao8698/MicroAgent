from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

import infinity
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.config import Settings


def select_eval_cleanup_tables(table_names: Iterable[str]) -> list[str]:
    selected = {
        name
        for name in table_names
        if name
        in {
            "documents",
            "chunks",
            "documents_datasets",
            "documents_dataset_bindings",
            "graph_entities",
            "graph_relationships",
        }
        or name.startswith("documents_")
        or name.startswith("chunks_")
        or name.startswith("graph_entities_")
        or name.startswith("graph_relationships_")
        or name.startswith("test_legacy_doc_")
        or name.startswith("test_legacy_chunk_")
    }
    return sorted(selected)


def list_table_names(settings: Settings) -> list[str]:
    client = infinity.connect(
        NetworkAddress(settings.infinity_host, settings.infinity_port),
    )
    try:
        database = client.get_database(settings.infinity_database)
        return _coerce_table_names(database.list_tables())
    finally:
        client.disconnect()


def drop_tables(settings: Settings, table_names: Iterable[str]) -> None:
    client = infinity.connect(
        NetworkAddress(settings.infinity_host, settings.infinity_port),
    )
    try:
        database = client.get_database(settings.infinity_database)
        for name in table_names:
            database.drop_table(name, ConflictType.Ignore)
    finally:
        client.disconnect()


def _coerce_table_names(raw: Any) -> list[str]:
    response_names = getattr(raw, "table_names", None)
    if response_names is not None:
        return [str(name) for name in response_names]
    if hasattr(raw, "to_pl"):
        raw = raw.to_pl().to_dicts()
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("table_name", "name"):
                    value = item.get(key)
                    if isinstance(value, str):
                        names.append(value)
                        break
        return names
    raise RuntimeError("Unable to read Infinity table names from list_tables().")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List or drop eval-related Infinity residue from default_db."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="drop the selected tables instead of printing a dry-run list",
    )
    args = parser.parse_args()

    settings = Settings.default(Path(__file__).resolve().parents[2])
    all_tables = list_table_names(settings)
    selected = select_eval_cleanup_tables(all_tables)

    if not args.execute:
        print("\n".join(selected))
        return

    drop_tables(settings, selected)
    print("\n".join(selected))


if __name__ == "__main__":
    main()
