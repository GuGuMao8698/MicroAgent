from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

ACTIVITY_STATUSES = frozenset(
    {
        "queued",
        "started",
        "running",
        "waiting_for_permission",
        "completed",
        "failed",
        "cancelled",
    }
)

_SENSITIVE_MARKERS = (
    "/home/",
    "\\home\\",
    "SKILL.md",
    "stderr",
    "traceback",
    "JSON-RPC",
    "transcript_path",
    "runtime_cwd",
    "CLAUDE_CONFIG_DIR",
    "MICRORAG_AGENT_CWD",
)

_MAX_TEXT_LEN = 240

_SUBAGENT_TOOL_NAMES = frozenset({"agent", "task"})

_SKILL_TOOL_NAMES = frozenset({"skilltool"})


class AgentCommandSummary(BaseModel):
    name: str
    description: str
    input_hint: str | None = None
    updated_at: datetime
    source: str = "runtime"


class AgentActivity(BaseModel):
    activity_id: str
    session_id: str
    kind: str
    label: str
    status: str
    summary: str | None = None
    source_message_id: str | None = None
    source_tool_call_id: str | None = None
    created_at: datetime
    updated_at: datetime


def _sanitize(text: str) -> str:
    for marker in _SENSITIVE_MARKERS:
        text = text.replace(marker, "[redacted]")
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN]
    return text


def _activity_id(session_id: str, source: str) -> str:
    digest = hashlib.sha1(f"{session_id}:{source}".encode()).hexdigest()
    return f"activity-{digest}"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class AgentRuntimeProjection:
    def __init__(self) -> None:
        self._commands: dict[str, AgentCommandSummary] = {}
        self._activities: dict[str, AgentActivity] = {}
        self._tool_call_index: dict[str, str] = {}

    def record_event(self, event: dict[str, Any]) -> None:
        handler = {
            "available_commands_update": self._on_available_commands_update,
            "tool_call": self._on_tool_call,
            "tool_call_update": self._on_tool_call_update,
            "permission_request": self._on_permission_request,
            "agent_message_chunk": self._on_message_chunk,
            "thought": self._on_message_chunk,
        }.get(event.get("sessionUpdate", ""))
        if handler is not None:
            handler(event)

    def command_summaries(self) -> list[AgentCommandSummary]:
        return sorted(self._commands.values(), key=lambda s: s.name)

    def activities(self) -> list[AgentActivity]:
        return sorted(self._activities.values(), key=lambda a: a.created_at)

    def activities_for_session(self, session_id: str) -> list[AgentActivity]:
        return sorted(
            [a for a in self._activities.values() if a.session_id == session_id],
            key=lambda a: a.created_at,
        )

    def _on_available_commands_update(self, event: dict[str, Any]) -> None:
        commands = event.get("commands")
        if not isinstance(commands, list):
            return
        now = _now()
        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            name = cmd.get("name")
            if not isinstance(name, str):
                continue
            self._commands[name] = AgentCommandSummary(
                name=name,
                description=_sanitize(cmd.get("description", "")),
                input_hint=_sanitize(cmd["input_hint"])
                if isinstance(cmd.get("input_hint"), str)
                else None,
                updated_at=now,
            )

    def _on_tool_call(self, event: dict[str, Any]) -> None:
        session_id = event.get("sessionId")
        if not isinstance(session_id, str):
            return
        tool_call_id = event.get("toolCallId")
        if not isinstance(tool_call_id, str):
            return
        tool_name = event.get("toolName", "")
        lowered = tool_name.lower() if isinstance(tool_name, str) else ""
        if lowered in _SUBAGENT_TOOL_NAMES:
            kind = "subagent"
        elif lowered in _SKILL_TOOL_NAMES:
            kind = "skill"
        else:
            kind = "tool"
        now = _now()
        aid = _activity_id(session_id, tool_call_id)
        activity = AgentActivity(
            activity_id=aid,
            session_id=session_id,
            kind=kind,
            label=_sanitize(f"{tool_name} call"),
            status="running",
            created_at=now,
            updated_at=now,
            source_tool_call_id=tool_call_id,
        )
        self._activities[aid] = activity
        self._tool_call_index[tool_call_id] = aid

    def _on_tool_call_update(self, event: dict[str, Any]) -> None:
        tool_call_id = event.get("toolCallId")
        if not isinstance(tool_call_id, str):
            return
        aid = self._tool_call_index.get(tool_call_id)
        if aid is None:
            return
        raw_status = event.get("status", "")
        status = (
            str(raw_status) if str(raw_status) in ACTIVITY_STATUSES else "completed"
        )
        existing = self._activities[aid]
        self._activities[aid] = existing.model_copy(
            update={"status": status, "updated_at": _now()}
        )

    def _on_permission_request(self, event: dict[str, Any]) -> None:
        session_id = event.get("sessionId")
        if not isinstance(session_id, str):
            return
        tool_call_id = event.get("toolCallId")
        if not isinstance(tool_call_id, str):
            return
        aid = self._tool_call_index.get(tool_call_id)
        if aid is not None:
            existing = self._activities[aid]
            self._activities[aid] = existing.model_copy(
                update={"status": "waiting_for_permission", "updated_at": _now()}
            )
            return
        tool_name = event.get("toolName", "")
        now = _now()
        aid = _activity_id(session_id, tool_call_id)
        self._activities[aid] = AgentActivity(
            activity_id=aid,
            session_id=session_id,
            kind="permission",
            label=_sanitize(f"Permission: {tool_name}"),
            status="waiting_for_permission",
            created_at=now,
            updated_at=now,
            source_tool_call_id=tool_call_id,
        )
        self._tool_call_index[tool_call_id] = aid

    def _on_message_chunk(self, event: dict[str, Any]) -> None:
        session_id = event.get("sessionId")
        if not isinstance(session_id, str):
            return
        content = event.get("content")
        if isinstance(content, dict):
            text = content.get("text", "")
        elif isinstance(content, str):
            text = content
        else:
            return
        if not isinstance(text, str):
            return

        lowered = text.lower()
        if "skill_progress" in lowered:
            kind = "skill"
            label = "MicroRAG skill"
        elif "agent_progress" in lowered or "subagent" in lowered:
            kind = "subagent"
            label = "Subagent progress"
        else:
            return

        # 单例设计：每种 kind 只保留最新进度行，避免在只有扁平文本时产生重复行
        source_key = f"chunk:{kind}"
        aid = _activity_id(session_id, source_key)
        now = _now()
        sanitized_summary = _sanitize(text)
        existing = self._activities.get(aid)
        if existing is not None:
            self._activities[aid] = existing.model_copy(
                update={
                    "summary": sanitized_summary,
                    "status": "running",
                    "updated_at": now,
                }
            )
        else:
            self._activities[aid] = AgentActivity(
                activity_id=aid,
                session_id=session_id,
                kind=kind,
                label=label,
                status="running",
                summary=sanitized_summary,
                created_at=now,
                updated_at=now,
            )
