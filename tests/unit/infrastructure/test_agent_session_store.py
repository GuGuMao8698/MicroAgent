from pathlib import Path

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
