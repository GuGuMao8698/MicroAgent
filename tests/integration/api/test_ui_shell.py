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
    from helpers.agent_runtime import setup_test_agent_runtime

    paths = setup_test_agent_runtime(tmp_path)
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

    def test_static_js_contains_session_management_hooks(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        assert "startInitialSession" in response.text
        assert "await createSession();" in response.text
        assert "await startInitialSession();" in response.text
        assert "deleteSession" in response.text
        assert 'method: "DELETE"' in response.text
        assert "session-delete" in response.text
        assert "resp.status === 204" in response.text
        assert "return {};" in response.text

    def test_agent_shell_contains_command_picker_and_activity_hosts(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/agent")
        assert response.status_code == 200
        assert 'id="slash-picker"' in response.text
        assert 'id="activity-stream"' in response.text
        assert 'id="composer-toolbar"' in response.text

    def test_agent_shell_script_contains_slash_prefill_not_command_execution(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200
        assert "loadCommandSummaries" in response.text
        assert "renderSlashPicker" in response.text
        assert "selectSlashCommand" in response.text
        assert "renderActivityStream" in response.text
        assert "/api/v0/agent/commands/" not in response.text

    def test_select_slash_command_only_prefills_text(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        select_slash_command = response.text.split(
            "function selectSlashCommand(command) {", 1
        )[1].split("function addLocalActivity(activity) {", 1)[0]
        assert 'input.value = "/" + command.name + " ";' in select_slash_command
        assert "renderSlashPicker();" in select_slash_command
        assert "addLocalActivity(" not in select_slash_command

    def test_static_js_uses_per_session_local_activity_storage(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        assert "localActivitiesBySession" in response.text
        assert "localActivities = []" not in response.text
        assert "localActivitiesBySession[activeSessionId]" in response.text
        assert "getLocalActivities(activeSessionId)" in response.text
        assert (
            "renderCurrentSessionActivities(requestedSessionId, runtimeActivities);"
            in (response.text)
        )
        assert "delete localActivitiesBySession[id];" in response.text

    def test_static_js_guards_activity_rendering_by_expected_session(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        assert "async function loadActivityStream(sessionId)" in response.text
        assert (
            "const requestedSessionId = sessionId || activeSessionId;" in response.text
        )
        assert "if (requestedSessionId !== activeSessionId) return;" in response.text
        assert (
            "renderCurrentSessionActivities(requestedSessionId, runtimeActivities);"
            in (response.text)
        )

    def test_static_js_polls_activity_stream_while_message_is_in_flight(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        assert "startActivityPolling" in response.text
        assert "stopActivityPolling" in response.text
        assert "clearInterval(activityPollTimer);" in response.text
        assert "activityPollTimer = window.setInterval" in response.text
        assert "loadActivityStream(pollSessionId).catch" in response.text
        assert "refreshActivityStreamBestEffort();" in response.text

    def test_static_js_keeps_activity_refresh_out_of_message_success_path(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        send_message = response.text.split("async function sendMessage() {", 1)[
            1
        ].split("// ── Event binding ──", 1)[0]
        assert (
            'const result = await api("/sessions/" + sendSessionId + "/messages",'
            in (send_message)
        )
        assert "await refreshActivityStreamBestEffort();" in send_message
        assert "await loadActivityStream();" not in send_message

    def test_send_message_snapshots_session_and_guards_success_ui_updates(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        send_message = response.text.split("async function sendMessage() {", 1)[
            1
        ].split("// ── Event binding ──", 1)[0]
        assert "let sendSessionId = null;" in send_message
        assert "sendSessionId = activeSessionId;" in send_message
        assert "startActivityPolling(sendSessionId);" in send_message
        assert "if (sendSessionId !== activeSessionId) return;" in send_message
        assert (
            'const result = await api("/sessions/" + sendSessionId + "/messages",'
            in (send_message)
        )

    def test_send_message_guards_stale_error_and_ui_cleanup_paths(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        send_message = response.text.split("async function sendMessage() {", 1)[
            1
        ].split("// ── Event binding ──", 1)[0]
        assert "let sendSessionId = null;" in send_message
        assert "if (sendSessionId === activeSessionId) {" in send_message
        assert 'appendMessage("Network error: " + err.message, "assistant");' in (
            send_message
        )
        assert "if (!sendSessionId || sendSessionId === activeSessionId) {" in (
            send_message
        )
        assert "clearStatus();" in send_message
        assert "composerInput.focus();" in send_message

    def test_create_session_resets_visible_activity_stream(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/static/agent-shell.js")
        assert response.status_code == 200

        create_session = response.text.split("async function createSession() {", 1)[
            1
        ].split("async function selectSession(id) {", 1)[0]
        assert "activeSessionId = session.id;" in create_session
        assert (
            "renderActivityStream([]);" in create_session
            or "await loadActivityStream(session.id);" in create_session
        )

    def test_agent_shell_does_not_surface_mcp_or_runtime_paths(
        self, ui_client: TestClient
    ) -> None:
        response = ui_client.get("/agent")
        assert response.status_code == 200
        forbidden = [
            "MCP server",
            "mcp server",
            "mcpServers",
            "CLAUDE_CONFIG_DIR",
            "MICRORAG_AGENT_CWD",
            "transcript_path",
            "runtime_cwd",
            "stderr",
            "traceback",
        ]
        for token in forbidden:
            assert token not in response.text, f"Forbidden token found: {token}"
