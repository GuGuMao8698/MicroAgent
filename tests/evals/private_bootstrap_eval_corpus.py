from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import infinity
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.config import Settings

try:
    from private_bootstrap_goldens import load_manifest
except ModuleNotFoundError:
    from evals.private_bootstrap_goldens import load_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_BOOTSTRAP_CORPUS_NAME = "private-bootstrap"
PRIVATE_BOOTSTRAP_SNAPSHOT_ROOT = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "documents"
    / "microrag-private-bootstrap-snapshot"
)
PRIVATE_BOOTSTRAP_CORPUS_DIR = (
    PROJECT_ROOT / "data" / "deepeval" / "corpus" / "private-bootstrap"
)
PRIVATE_BOOTSTRAP_CORPUS_MANIFEST = PRIVATE_BOOTSTRAP_CORPUS_DIR / "manifest.json"
PRIVATE_BOOTSTRAP_EVAL_TABLES = {
    "documents": "eval_private_bootstrap_documents",
    "chunks": "eval_private_bootstrap_chunks",
    "datasets": "eval_private_bootstrap_documents_datasets",
    "dataset_bindings": "eval_private_bootstrap_documents_dataset_bindings",
    "graph_entities": "eval_private_bootstrap_graph_entities",
    "graph_relationships": "eval_private_bootstrap_graph_relationships",
}

_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}


def fixed_private_bootstrap_table_names() -> list[str]:
    return [
        PRIVATE_BOOTSTRAP_EVAL_TABLES["documents"],
        PRIVATE_BOOTSTRAP_EVAL_TABLES["chunks"],
        PRIVATE_BOOTSTRAP_EVAL_TABLES["datasets"],
        PRIVATE_BOOTSTRAP_EVAL_TABLES["dataset_bindings"],
        PRIVATE_BOOTSTRAP_EVAL_TABLES["graph_entities"],
        PRIVATE_BOOTSTRAP_EVAL_TABLES["graph_relationships"],
    ]


def assign_private_bootstrap_eval_tables(settings: Settings) -> Settings:
    settings.infinity_document_table = PRIVATE_BOOTSTRAP_EVAL_TABLES["documents"]
    settings.infinity_chunk_table = PRIVATE_BOOTSTRAP_EVAL_TABLES["chunks"]
    settings.infinity_graph_entity_table = PRIVATE_BOOTSTRAP_EVAL_TABLES[
        "graph_entities"
    ]
    settings.infinity_graph_relationship_table = PRIVATE_BOOTSTRAP_EVAL_TABLES[
        "graph_relationships"
    ]
    return settings


def hash_snapshot_manifest(snapshot_root: Path) -> str:
    return hashlib.sha256((snapshot_root / "manifest.json").read_bytes()).hexdigest()


def build_private_bootstrap_corpus_manifest(
    *,
    snapshot_root: Path,
    embedding_model: str,
) -> dict[str, Any]:
    return {
        "corpus": PRIVATE_BOOTSTRAP_CORPUS_NAME,
        "snapshot_root": _snapshot_root_label(snapshot_root),
        "snapshot_manifest_sha256": hash_snapshot_manifest(snapshot_root),
        "document_count": _snapshot_document_count(snapshot_root),
        "embedding_model": embedding_model,
        "tables": dict(PRIVATE_BOOTSTRAP_EVAL_TABLES),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_private_bootstrap_corpus_manifest(
    manifest: Mapping[str, Any],
    *,
    snapshot_root: Path,
    embedding_model: str,
) -> None:
    if manifest.get("corpus") != PRIVATE_BOOTSTRAP_CORPUS_NAME:
        raise RuntimeError("private-bootstrap eval corpus manifest has wrong corpus.")

    expected_hash = hash_snapshot_manifest(snapshot_root)
    if manifest.get("snapshot_manifest_sha256") != expected_hash:
        raise RuntimeError("private-bootstrap snapshot manifest hash mismatch.")

    expected_count = _snapshot_document_count(snapshot_root)
    if manifest.get("document_count") != expected_count:
        raise RuntimeError("private-bootstrap document count mismatch.")

    if manifest.get("embedding_model") != embedding_model:
        raise RuntimeError("private-bootstrap embedding model mismatch.")

    if manifest.get("tables") != PRIVATE_BOOTSTRAP_EVAL_TABLES:
        raise RuntimeError("private-bootstrap fixed table manifest mismatch.")


def validate_private_bootstrap_reuse_ready(
    settings: Settings,
    *,
    snapshot_root: Path = PRIVATE_BOOTSTRAP_SNAPSHOT_ROOT,
    manifest_path: Path = PRIVATE_BOOTSTRAP_CORPUS_MANIFEST,
    env: Mapping[str, str | None] = os.environ,
) -> dict[str, Any]:
    embedding_model = env.get("ARK_EMBEDDING_MODEL")
    if not embedding_model:
        raise RuntimeError(
            "ARK_EMBEDDING_MODEL is required for corpus reuse validation."
        )
    if not manifest_path.exists():
        raise RuntimeError(
            "private-bootstrap eval corpus manifest is missing; rebuild with "
            "tests/evals/build_private_bootstrap_eval_corpus.py --mode rebuild."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError(
            "private-bootstrap eval corpus manifest must be a JSON object."
        )
    validate_private_bootstrap_corpus_manifest(
        manifest,
        snapshot_root=snapshot_root,
        embedding_model=embedding_model,
    )

    table_names = set(_list_table_names(settings))
    missing_tables = sorted(set(fixed_private_bootstrap_table_names()) - table_names)
    if missing_tables:
        raise RuntimeError(
            "private-bootstrap eval corpus tables are missing; rebuild corpus: "
            + ", ".join(missing_tables)
        )

    row_count = _document_row_count(settings)
    expected_count = int(manifest["document_count"])
    if row_count != expected_count:
        raise RuntimeError(
            f"private-bootstrap documents table row count is {row_count}, "
            f"expected {expected_count}; rebuild eval corpus."
        )
    return manifest


def _normalize_snapshot_root(snapshot_root: Path) -> Path:
    fixture_documents_dir = (
        PROJECT_ROOT / "tests" / "fixtures" / "documents"
    ).resolve()
    if not snapshot_root.is_absolute():
        snapshot_root = PROJECT_ROOT / snapshot_root
    normalized = snapshot_root.resolve()
    try:
        normalized.relative_to(fixture_documents_dir)
    except ValueError as exc:
        raise RuntimeError(
            f"private-bootstrap snapshot root must be under {fixture_documents_dir}."
        ) from exc
    if not (normalized / "manifest.json").is_file():
        raise RuntimeError(
            f"private-bootstrap snapshot root must contain manifest.json: {normalized}."
        )
    return normalized


def rebuild_private_bootstrap_eval_corpus(
    *,
    snapshot_root: Path = PRIVATE_BOOTSTRAP_SNAPSHOT_ROOT,
) -> dict[str, Any]:
    embedding_model = os.environ.get("ARK_EMBEDDING_MODEL")
    if not embedding_model:
        raise RuntimeError("ARK_EMBEDDING_MODEL is required to rebuild eval corpus.")

    snapshot_root = _normalize_snapshot_root(snapshot_root)
    settings = assign_private_bootstrap_eval_tables(Settings.default(PROJECT_ROOT))
    _drop_fixed_tables(settings)

    from fastapi.testclient import TestClient

    from ragflow_lite.app import create_app

    app = create_app(settings)
    fixture_documents_dir = (
        PROJECT_ROOT / "tests" / "fixtures" / "documents"
    ).resolve()
    with TestClient(app) as client:
        document_statuses = _upload_snapshot_documents(
            client=client,
            fixture_documents_dir=fixture_documents_dir,
            snapshot_root=snapshot_root,
        )

    manifest = build_private_bootstrap_corpus_manifest(
        snapshot_root=snapshot_root,
        embedding_model=embedding_model,
    )
    if len(document_statuses) != manifest["document_count"]:
        raise RuntimeError(
            "private-bootstrap rebuild indexed document count does not match snapshot."
        )

    PRIVATE_BOOTSTRAP_CORPUS_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_BOOTSTRAP_CORPUS_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build the fixed private-bootstrap DeepEval corpus."
    )
    parser.add_argument(
        "--snapshot", type=Path, default=PRIVATE_BOOTSTRAP_SNAPSHOT_ROOT
    )
    parser.add_argument("--mode", choices=("rebuild",), default="rebuild")
    args = parser.parse_args(argv)

    manifest = rebuild_private_bootstrap_eval_corpus(snapshot_root=args.snapshot)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _snapshot_root_label(snapshot_root: Path) -> str:
    try:
        return snapshot_root.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return snapshot_root.as_posix()


def _snapshot_document_count(snapshot_root: Path) -> int:
    return len(load_manifest(snapshot_root))


def _connect(settings: Settings) -> Any:
    return infinity.connect(
        NetworkAddress(settings.infinity_host, settings.infinity_port)
    )


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


def _list_table_names(settings: Settings) -> list[str]:
    client = _connect(settings)
    try:
        database = client.get_database(settings.infinity_database)
        return _coerce_table_names(database.list_tables())
    finally:
        client.disconnect()


def _document_row_count(settings: Settings) -> int:
    client = _connect(settings)
    try:
        database = client.get_database(settings.infinity_database)
        table = database.get_table(PRIVATE_BOOTSTRAP_EVAL_TABLES["documents"])
        result = table.output(["document_id"]).to_pl()
        df = result[0] if isinstance(result, tuple) else result
        return len(df)
    finally:
        client.disconnect()


def _drop_fixed_tables(settings: Settings) -> None:
    client = _connect(settings)
    try:
        database = client.get_database(settings.infinity_database)
        for table_name in fixed_private_bootstrap_table_names():
            database.drop_table(table_name, ConflictType.Ignore)
    finally:
        client.disconnect()


def _upload_snapshot_documents(
    *,
    client: Any,
    fixture_documents_dir: Path,
    snapshot_root: Path,
) -> list[dict[str, Any]]:
    document_statuses = []
    for entry in load_manifest(snapshot_root):
        fixture_name = (
            f"{snapshot_root.relative_to(fixture_documents_dir).as_posix()}/"
            f"{entry.snapshot_path}"
        )
        upload_response = _upload_fixture_document(
            client,
            fixture_documents_dir,
            fixture_name,
        )
        if upload_response.status_code != 202:
            raise RuntimeError(
                f"private-bootstrap upload failed for {fixture_name}: "
                f"HTTP {upload_response.status_code} {upload_response.text}"
            )
        final_payload = _wait_for_document_terminal_state(
            client,
            upload_response.json()["document_id"],
        )
        if final_payload["status"] != "indexed":
            raise RuntimeError(
                f"private-bootstrap document {fixture_name} reached "
                f"{final_payload['status']} instead of indexed."
            )
        document_statuses.append(final_payload)
    return document_statuses


def _upload_fixture_document(
    client: Any,
    fixture_documents_dir: Path,
    fixture_name: str,
) -> Any:
    from uuid import uuid4

    suffix = Path(fixture_name).suffix
    fixture_path = fixture_documents_dir / fixture_name
    upload_name = fixture_name.replace("/", "__")
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                upload_name,
                fixture_path.read_bytes(),
                _CONTENT_TYPES[suffix],
            )
        },
        headers={"Idempotency-Key": f"key-{uuid4().hex}"},
    )


def _wait_for_document_terminal_state(
    client: Any,
    document_id: str,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/v0/documents/{document_id}")
        if response.status_code != 200:
            raise RuntimeError(
                f"document poll failed for {document_id}: "
                f"HTTP {response.status_code} {response.text}"
            )
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"indexed", "failed"}:
            return payload
        time.sleep(0.1)

    raise RuntimeError(
        f"Document {document_id} did not reach terminal status. "
        f"Last payload: {last_payload}"
    )


if __name__ == "__main__":
    main()
