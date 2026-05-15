"""Integration tests for the MicroRAG agent demo shell UI.

Verifies that the HTML shell is served correctly, contains required
branding, and excludes forbidden identifiers.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from infinity_test_support import (
    assign_isolated_infinity_tables,
    register_infinity_table_cleanup,
)

from ragflow_lite.config import Settings


def _ui_test_settings(tmp_path: Path) -> Settings:
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
    )
    assign_isolated_infinity_tables(settings, tmp_path, salt=uuid4().hex[:8])
    register_infinity_table_cleanup(settings)
    settings.ensure_directories()
    return settings


FORBIDDEN_STRINGS = (
    "Claude Code",
    "claude-code",
    "transcript_path",
    "runtime_cwd",
    "stderr",
    "agentInfo",
)


@pytest.fixture
def ui_client(tmp_path: Path):
    """TestClient wired with the real app including UI routes."""
    from ragflow_lite.app import create_app

    settings = _ui_test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app, follow_redirects=False) as client:
        yield client


class TestAgentShellUI:
    def test_get_agent_returns_200(self, ui_client: TestClient) -> None:
        response = ui_client.get("/agent")
        assert response.status_code == 200

    def test_response_contains_microrag_branding(self, ui_client: TestClient) -> None:
        response = ui_client.get("/agent")
        assert "MicroRAG" in response.text

    def test_response_is_html(self, ui_client: TestClient) -> None:
        response = ui_client.get("/agent")
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_html_lang_is_zh_cn(self, ui_client: TestClient) -> None:
        response = ui_client.get("/agent")
        assert 'lang="zh-CN"' in response.text

    @pytest.mark.parametrize("forbidden", FORBIDDEN_STRINGS)
    def test_no_forbidden_identifiers(
        self, ui_client: TestClient, forbidden: str
    ) -> None:
        response = ui_client.get("/agent")
        assert forbidden not in response.text, (
            f"Forbidden string '{forbidden}' found in HTML response"
        )

    def test_static_css_accessible(self, ui_client: TestClient) -> None:
        response = ui_client.get("/static/agent-shell.css")
        assert response.status_code == 200

    def test_static_js_accessible(self, ui_client: TestClient) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200
