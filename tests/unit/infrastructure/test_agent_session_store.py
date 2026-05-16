from pathlib import Path

import pytest

from ragflow_lite.infrastructure.agent import session_store as session_store_module
from ragflow_lite.infrastructure.agent.session_store import AgentSessionStore


def test_session_store_creates_and_lists_metadata(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")

    session = store.create_session(
        title="New chat",
        claude_session_id="claude-1",
        transcript_path="/internal/transcript.jsonl",
        runtime_cwd="/internal/cwd",
    )

    sessions = store.list_sessions()

    assert sessions[0].id == session.id
    assert sessions[0].title == "New chat"
    assert sessions[0].claude_session_id == "claude-1"
    assert sessions[0].transcript_path == "/internal/transcript.jsonl"
    assert sessions[0].runtime_cwd == "/internal/cwd"


def test_session_store_does_not_store_messages(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")
    store.create_session(
        title="New chat",
        claude_session_id="claude-1",
        transcript_path="/internal/transcript.jsonl",
        runtime_cwd="/internal/cwd",
    )

    columns = store.debug_columns("agent_sessions")

    assert "messages" not in columns
    assert "conversation" not in columns
    assert "transcript_json" not in columns


def test_session_store_gets_and_marks_error(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")
    session = store.create_session(
        title="New chat",
        claude_session_id="claude-1",
        transcript_path="/internal/transcript.jsonl",
        runtime_cwd="/internal/cwd",
    )

    assert store.get_session("missing") is None

    store.mark_error(session.id, "boom")
    updated = store.get_session(session.id)

    assert updated is not None
    assert updated.last_error == "boom"
    assert updated.updated_at >= updated.created_at


def test_session_store_deletes_metadata_only(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")
    first = store.create_session(
        title="First",
        claude_session_id="claude-1",
        transcript_path="/internal/first.jsonl",
        runtime_cwd="/internal/cwd",
    )
    second = store.create_session(
        title="Second",
        claude_session_id="claude-2",
        transcript_path="/internal/second.jsonl",
        runtime_cwd="/internal/cwd",
    )

    assert store.delete_session(first.id) is True

    assert store.get_session(first.id) is None
    assert [session.id for session in store.list_sessions()] == [second.id]
    assert store.delete_session(first.id) is False


def test_session_store_lists_same_timestamp_sessions_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")
    monkeypatch.setattr(
        session_store_module,
        "_now_iso",
        lambda: "2026-05-15T12:00:00+00:00",
    )
    ids = iter(
        [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000003",
            "00000000-0000-0000-0000-000000000002",
        ]
    )
    monkeypatch.setattr(session_store_module.uuid, "uuid4", lambda: next(ids))

    store.create_session(
        title="First",
        claude_session_id="claude-1",
        transcript_path="/internal/1.jsonl",
        runtime_cwd="/internal/cwd",
    )
    store.create_session(
        title="Second",
        claude_session_id="claude-2",
        transcript_path="/internal/2.jsonl",
        runtime_cwd="/internal/cwd",
    )
    store.create_session(
        title="Third",
        claude_session_id="claude-3",
        transcript_path="/internal/3.jsonl",
        runtime_cwd="/internal/cwd",
    )

    sessions = store.list_sessions()

    assert [session.id for session in sessions] == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]
