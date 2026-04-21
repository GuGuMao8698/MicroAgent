from __future__ import annotations

from pathlib import Path

from conftest import _build_test_scope_suffix


def test_app_settings_use_test_scoped_infinity_table_names(app_settings) -> None:
    assert app_settings.infinity_document_table != "documents"
    assert app_settings.infinity_chunk_table != "chunks"
    assert app_settings.infinity_document_table.startswith("documents_")
    assert app_settings.infinity_chunk_table.startswith("chunks_")


def test_build_test_scope_suffix_changes_when_only_parent_path_changes() -> None:
    left = _build_test_scope_suffix(Path("/tmp/pytest-of-xia/pytest-101/test_case0"))
    right = _build_test_scope_suffix(Path("/tmp/pytest-of-xia/pytest-102/test_case0"))

    assert left != right
    assert left.startswith("test_case0_")
    assert right.startswith("test_case0_")
