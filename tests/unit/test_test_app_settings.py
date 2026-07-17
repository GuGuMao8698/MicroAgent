from __future__ import annotations

from pathlib import Path

import conftest
import pytest
from conftest import _configure_infinity_tables_for_test_settings
from infinity_test_support import build_test_scope_suffix

from ragflow_lite.config import Settings


class _FakeConfig:
    def __init__(self, options: dict[str, object]) -> None:
        self.options = options

    def getoption(self, name: str) -> object:
        return self.options[name]


class _FakeRequest:
    def __init__(self, options: dict[str, object]) -> None:
        self.config = _FakeConfig(options)
        self.node: object | None = None


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )


def test_app_settings_use_test_scoped_infinity_table_names(app_settings) -> None:
    assert app_settings.infinity_document_table != "documents"
    assert app_settings.infinity_chunk_table != "chunks"
    assert app_settings.infinity_document_table.startswith("documents_")
    assert app_settings.infinity_chunk_table.startswith("chunks_")
    assert app_settings.infinity_graph_entity_table.startswith("graph_entities_")
    assert app_settings.infinity_graph_relationship_table.startswith(
        "graph_relationships_"
    )
    assert app_settings.infinity_psi_node_table.startswith("psi_nodes_")


def test_app_settings_use_fixed_private_bootstrap_tables_for_deepeval_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    request = _FakeRequest(
        {
            "--run-deepeval": True,
            "--deepeval-corpus-mode": "reuse",
        }
    )
    monkeypatch.setattr(
        conftest,
        "assign_isolated_infinity_tables",
        pytest.fail,
    )
    monkeypatch.setattr(
        conftest,
        "register_infinity_table_cleanup",
        pytest.fail,
    )

    _configure_infinity_tables_for_test_settings(settings, tmp_path, request)

    assert settings.infinity_document_table == "eval_private_bootstrap_documents"
    assert settings.infinity_chunk_table == "eval_private_bootstrap_chunks"
    assert (
        settings.infinity_graph_entity_table == "eval_private_bootstrap_graph_entities"
    )
    assert (
        settings.infinity_graph_relationship_table
        == "eval_private_bootstrap_graph_relationships"
    )


def test_app_settings_use_test_scoped_tables_for_deepeval_fresh(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    request = _FakeRequest(
        {
            "--run-deepeval": True,
            "--deepeval-corpus-mode": "fresh",
        }
    )

    _configure_infinity_tables_for_test_settings(settings, tmp_path, request)

    assert settings.infinity_document_table.startswith("documents_")
    assert settings.infinity_chunk_table.startswith("chunks_")
    assert settings.infinity_graph_entity_table.startswith("graph_entities_")
    assert settings.infinity_graph_relationship_table.startswith("graph_relationships_")
    assert settings.infinity_psi_node_table.startswith("psi_nodes_")


def test_deepeval_reuse_manifest_validates_before_app_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    request = _FakeRequest(
        {
            "--run-deepeval": True,
            "--deepeval-corpus-mode": "reuse",
        }
    )
    calls: list[str] = []

    class _FakeNode:
        def get_closest_marker(self, name: str) -> object | None:
            assert name == "deepeval"
            return object()

    request.node = _FakeNode()

    def fake_validate(observed_settings: Settings) -> dict[str, object]:
        assert observed_settings is settings
        calls.append("validated")
        return {"corpus": "private-bootstrap"}

    monkeypatch.setattr(
        conftest,
        "validate_private_bootstrap_reuse_ready",
        fake_validate,
    )

    manifest = conftest._validate_deepeval_reuse_corpus_for_settings(
        settings,
        request,
    )

    assert manifest == {"corpus": "private-bootstrap"}
    assert calls == ["validated"]


def test_build_test_scope_suffix_changes_when_only_parent_path_changes() -> None:
    left = build_test_scope_suffix(Path("/tmp/pytest-of-xia/pytest-101/test_case0"))
    right = build_test_scope_suffix(Path("/tmp/pytest-of-xia/pytest-102/test_case0"))

    assert left != right
    assert left.startswith("test_case0_")
    assert right.startswith("test_case0_")
