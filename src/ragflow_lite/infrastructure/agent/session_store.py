from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class AgentSessionMetadata:
    id: str
    title: str
    claude_session_id: str
    transcript_path: str
    runtime_cwd: str
    created_at: str
    updated_at: str
    last_error: str | None
    ui_metadata_json: str


class AgentSessionStore:
    """仅持久化 UI 所需的 session 元数据。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def create_session(
        self,
        *,
        title: str,
        claude_session_id: str,
        transcript_path: str,
        runtime_cwd: str,
    ) -> AgentSessionMetadata:
        session = AgentSessionMetadata(
            id=str(uuid.uuid4()),
            title=title,
            claude_session_id=claude_session_id,
            transcript_path=transcript_path,
            runtime_cwd=runtime_cwd,
            created_at=_now_iso(),
            updated_at=_now_iso(),
            last_error=None,
            ui_metadata_json="{}",
        )
        session.updated_at = session.created_at
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_sessions (
                    id,
                    title,
                    claude_session_id,
                    transcript_path,
                    runtime_cwd,
                    created_at,
                    updated_at,
                    last_error,
                    ui_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.title,
                    session.claude_session_id,
                    session.transcript_path,
                    session.runtime_cwd,
                    session.created_at,
                    session.updated_at,
                    session.last_error,
                    session.ui_metadata_json,
                ),
            )
        return session

    def list_sessions(self) -> list[AgentSessionMetadata]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    title,
                    claude_session_id,
                    transcript_path,
                    runtime_cwd,
                    created_at,
                    updated_at,
                    last_error,
                    ui_metadata_json
                FROM agent_sessions
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """
            ).fetchall()
        return [_row_to_metadata(row) for row in rows]

    def get_session(self, session_id: str) -> AgentSessionMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    title,
                    claude_session_id,
                    transcript_path,
                    runtime_cwd,
                    created_at,
                    updated_at,
                    last_error,
                    ui_metadata_json
                FROM agent_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_metadata(row)

    def mark_error(self, session_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_sessions
                SET last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, _now_iso(), session_id),
            )

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM agent_sessions
                WHERE id = ?
                """,
                (session_id,),
            )
        return cursor.rowcount > 0

    def debug_columns(self, table: str) -> list[str]:
        if table != "agent_sessions":
            msg = f"unsupported debug table: {table}"
            raise ValueError(msg)
        with self._connect() as connection:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        return [str(row["name"]) for row in rows]

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    claude_session_id TEXT NOT NULL,
                    transcript_path TEXT NOT NULL,
                    runtime_cwd TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT,
                    ui_metadata_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_metadata(row: sqlite3.Row) -> AgentSessionMetadata:
    return AgentSessionMetadata(
        id=str(row["id"]),
        title=str(row["title"]),
        claude_session_id=str(row["claude_session_id"]),
        transcript_path=str(row["transcript_path"]),
        runtime_cwd=str(row["runtime_cwd"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        last_error=None if row["last_error"] is None else str(row["last_error"]),
        ui_metadata_json=str(row["ui_metadata_json"]),
    )
