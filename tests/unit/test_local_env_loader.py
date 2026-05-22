from __future__ import annotations

import os

from helpers.local_env import load_export_env_file


def test_load_export_env_file_sets_missing_export_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "\n".join(
            [
                "export DEEPSEEK_API_KEY=deepseek-real",
                'export ARK_API_KEY="ark real"',
                "export ARK_EMBEDDING_MODEL='ep-real'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)

    load_export_env_file(env_file, os.environ)

    assert os.environ["DEEPSEEK_API_KEY"] == "deepseek-real"
    assert os.environ["ARK_API_KEY"] == "ark real"
    assert os.environ["ARK_EMBEDDING_MODEL"] == "ep-real"


def test_load_export_env_file_keeps_existing_non_placeholder_values(
    tmp_path, monkeypatch
) -> None:
    env_file = tmp_path / "local.env"
    env_file.write_text("export DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-shell")

    load_export_env_file(env_file, os.environ)

    assert os.environ["DEEPSEEK_API_KEY"] == "from-shell"


def test_load_export_env_file_replaces_test_placeholders(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "local.env"
    env_file.write_text(
        "\n".join(
            [
                "export DEEPSEEK_API_KEY=deepseek-real",
                "export ARK_API_KEY=ark-real",
                "export ARK_EMBEDDING_MODEL=ep-real",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    load_export_env_file(env_file, os.environ)

    assert os.environ["DEEPSEEK_API_KEY"] == "deepseek-real"
    assert os.environ["ARK_API_KEY"] == "ark-real"
    assert os.environ["ARK_EMBEDDING_MODEL"] == "ep-real"
