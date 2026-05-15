"""Test agent session API routes: list, create, resume, send message.

Each test builds a standalone FastAPI app with fake services so the routes
exercise real logic without touching SQLite or ACP subprocesses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ragflow_lite.api.routes.agent import router as agent_router

# ---------------------------------------------------------------------------
# Fake service objects
# ---------------------------------------------------------------------------

_SENTINEL_CLAUDE_ID = "claude-abc-123"


@dataclass(slots=True)
class _FakeAgentSessionMetadata:
    """Mimics AgentSessionMetadata for route-level tests."""

    id: str
    title: str
    claude_session_id: str
    transcript_path: str
    runtime_cwd: str
    created_at: str
    updated_at: str
    last_error: str | None
    ui_metadata_json: str = "{}"


@dataclass(slots=True)
class _FakeServices:
    """Subset of AppServices used by agent routes, plus acp_client."""

    agent_session_store: Any
    acp_client: Any


def _make_session(
    session_id: str = "sess-1",
    title: str = "Test session",
    claude_session_id: str = _SENTINEL_CLAUDE_ID,
    transcript_path: str = "/tmp/transcripts/sess-1.jsonl",
    runtime_cwd: str = "/home/user/project",
) -> _FakeAgentSessionMetadata:
    return _FakeAgentSessionMetadata(
        id=session_id,
        title=title,
        claude_session_id=claude_session_id,
        transcript_path=transcript_path,
        runtime_cwd=runtime_cwd,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:01:00Z",
        last_error=None,
    )


def _build_app(*, acp_client: Any, session_store: Any) -> FastAPI:
    """Build a minimal FastAPI app with fake services wired into state."""
    app = FastAPI()
    services = _FakeServices(
        agent_session_store=session_store,
        acp_client=acp_client,
    )
    app.state.services = services
    app.include_router(agent_router, prefix="/api/v0/agent")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListSessions:
    """GET /sessions must return UI-safe fields only."""

    def test_list_sessions_redacts_backend_only_fields(self) -> None:
        session = _make_session()
        store = MagicMock()
        store.list_sessions.return_value = [session]

        app = _build_app(acp_client=MagicMock(), session_store=store)
        client = TestClient(app)

        response = client.get("/api/v0/agent/sessions")
        assert response.status_code == 200

        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1

        item = body[0]
        # Must have UI-safe fields
        assert "id" in item
        assert "title" in item
        assert "created_at" in item
        assert "updated_at" in item

        raw = json.dumps(item)

        # Must NOT expose backend-only identifiers
        assert "claude_session_id" not in item
        assert "transcript_path" not in item
        assert "runtime_cwd" not in item

        # Must not leak backend implementation names
        assert "Claude Code" not in raw
        assert "claude-code" not in raw
        assert "transcript" not in raw


class TestCreateSession:
    """POST /sessions creates a new session and returns UI-safe fields."""

    def test_create_session_returns_ui_metadata_only(self) -> None:
        session = _make_session(session_id="sess-new", title="My session")
        store = MagicMock()
        store.create_session.return_value = session

        acp = MagicMock()
        acp.initialize.return_value = {"sessionId": _SENTINEL_CLAUDE_ID}

        app = _build_app(acp_client=acp, session_store=store)
        client = TestClient(app)

        response = client.post(
            "/api/v0/agent/sessions",
            json={"title": "My session"},
        )
        assert response.status_code == 201

        item = response.json()
        assert item["id"] == "sess-new"
        assert item["title"] == "My session"

        # Must NOT expose backend fields
        assert "claude_session_id" not in item
        assert "transcript_path" not in item

        # acp_client.start() and initialize() must have been called
        acp.start.assert_called_once()
        acp.initialize.assert_called_once()

        # Session store must have been called with the claude session id
        store.create_session.assert_called_once()
        call_kwargs = store.create_session.call_args
        assert call_kwargs.kwargs["claude_session_id"] == _SENTINEL_CLAUDE_ID


class TestResumeSession:
    """POST /sessions/{session_id}/resume resumes an existing session."""

    def test_resume_session_attaches_by_ui_session_id_without_leaking_transcript(
        self,
    ) -> None:
        session = _make_session()
        store = MagicMock()
        store.get_session.return_value = session

        acp = MagicMock()
        acp.resume_session.return_value = {"status": "loaded"}

        app = _build_app(acp_client=acp, session_store=store)
        client = TestClient(app)

        response = client.post("/api/v0/agent/sessions/sess-1/resume")
        assert response.status_code == 200

        item = response.json()
        assert item["session_id"] == "sess-1"
        assert item["status"] == "resumed"

        raw = json.dumps(item)
        assert "transcript_path" not in item
        assert "Claude Code" not in raw

        # acp_client.resume_session called with the internal claude_session_id
        acp.resume_session.assert_called_once_with(_SENTINEL_CLAUDE_ID)

    def test_resume_session_returns_recoverable_error_on_runtime_error(self) -> None:
        session = _make_session()
        store = MagicMock()
        store.get_session.return_value = session

        acp = MagicMock()
        acp.resume_session.side_effect = RuntimeError("process crashed")

        app = _build_app(acp_client=acp, session_store=store)
        client = TestClient(app)

        response = client.post("/api/v0/agent/sessions/sess-1/resume")
        assert response.status_code == 200

        item = response.json()
        assert item["status"] == "recoverable_error"

        # store.mark_error should have been called
        store.mark_error.assert_called_once_with("sess-1", "process crashed")

    def test_resume_session_returns_404_for_unknown_session(self) -> None:
        store = MagicMock()
        store.get_session.return_value = None

        app = _build_app(acp_client=MagicMock(), session_store=store)
        client = TestClient(app)

        response = client.post("/api/v0/agent/sessions/unknown/resume")
        assert response.status_code == 404


class TestSendMessage:
    """POST /sessions/{session_id}/messages sends a message to the session."""

    def test_send_message_uses_resumed_session_and_returns_redacted_content(
        self,
    ) -> None:
        session = _make_session()
        store = MagicMock()
        store.get_session.return_value = session

        acp = MagicMock()
        acp.resume_session.return_value = {"status": "loaded"}
        acp.send_message.return_value = {"reply": "Hello from agent"}

        app = _build_app(acp_client=acp, session_store=store)
        client = TestClient(app)

        response = client.post(
            "/api/v0/agent/sessions/sess-1/messages",
            json={"message": "Hello"},
        )
        assert response.status_code == 200

        item = response.json()
        assert item["session_id"] == "sess-1"
        assert item["status"] == "sent"

        raw = json.dumps(item)
        assert "claude-session-id" not in raw
        assert "Claude Code" not in raw

        # resume_session called before send_message
        acp.resume_session.assert_called_once_with(_SENTINEL_CLAUDE_ID)
        acp.send_message.assert_called_once_with(_SENTINEL_CLAUDE_ID, "Hello")

    def test_send_message_returns_404_for_unknown_session(self) -> None:
        store = MagicMock()
        store.get_session.return_value = None

        app = _build_app(acp_client=MagicMock(), session_store=store)
        client = TestClient(app)

        response = client.post(
            "/api/v0/agent/sessions/unknown/messages",
            json={"message": "Hello"},
        )
        assert response.status_code == 404

    def test_send_message_returns_recoverable_error_on_runtime_error(self) -> None:
        session = _make_session()
        store = MagicMock()
        store.get_session.return_value = session

        acp = MagicMock()
        acp.resume_session.return_value = {"status": "loaded"}
        acp.send_message.side_effect = RuntimeError("connection lost")

        app = _build_app(acp_client=acp, session_store=store)
        client = TestClient(app)

        response = client.post(
            "/api/v0/agent/sessions/sess-1/messages",
            json={"message": "Hello"},
        )
        assert response.status_code == 200

        item = response.json()
        assert item["status"] == "recoverable_error"

        store.mark_error.assert_called_once_with("sess-1", "connection lost")
