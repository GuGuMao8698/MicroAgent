from __future__ import annotations

import hashlib
import re
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

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(?:stderr|traceback|json-rpc|mcpservers|mcp server)\b"),
    re.compile(r'(?i)File\s+"(?:src|tests|参考项目)/[^"]+",\s+line\s+\d+[^\n]*'),
    re.compile(
        r"(?i)\b(?:claude_config_dir|microrag_agent_cwd|transcript_path|runtime_cwd|cwd)\s*=\s*[^\s,;]+"
    ),
    re.compile(
        r'(?i)"?(?:claude_config_dir|microrag_agent_cwd|transcript_path|runtime_cwd|cwd)"?\s*:\s*"[^"]+"'
    ),
    re.compile(
        r"(?i)\b(?:claude_config_dir|microrag_agent_cwd|transcript_path|runtime_cwd|cwd)\s*:\s*[^\s,;]+"
    ),
    re.compile(r"(?i)(?:\.claude/)?skills/[^\s,;]+/skill\.md\b"),
    re.compile(r"(?i)\b(?:src|tests|参考项目)/[^\s,;]+"),
    re.compile(
        r"(?i)\b(?:claude_config_dir|microrag_agent_cwd|transcript_path|runtime_cwd|cwd)\b"
    ),
    re.compile(r"(?i)\bskill\.md\b"),
    re.compile(r"(?i)\b[a-z]:\\(?:[^\\\s]+\\)*[^\\\s]+"),
    re.compile(
        r"(?<![A-Za-z0-9._-])/(?:tmp|workspace|var|home|Users|etc|opt|srv|root|mnt|private|proc|dev|run)(?:/[^\s,;]+)*"
    ),
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
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[redacted]", text)
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
        self._tool_call_index: dict[tuple[str, str], str] = {}

    def _index_tool_call(
        self, session_id: str, tool_call_id: str, activity_id: str
    ) -> None:
        self._tool_call_index[(session_id, tool_call_id)] = activity_id

    def _tool_call_activity_id(
        self, session_id: str | None, tool_call_id: str
    ) -> str | None:
        if session_id is not None:
            return self._tool_call_index.get((session_id, tool_call_id))

        matches = [
            activity_id
            for (
                indexed_session_id,
                indexed_tool_call_id,
            ), activity_id in self._tool_call_index.items()
            if indexed_tool_call_id == tool_call_id
        ]
        if len(matches) == 1:
            return matches[0]
        return None

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
        commands = event.get("availableCommands", event.get("commands"))
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
                input_hint=self._command_input_hint(cmd),
                updated_at=now,
            )

    def _command_input_hint(self, command: dict[str, Any]) -> str | None:
        input_hint = command.get("input_hint")
        if isinstance(input_hint, str):
            return _sanitize(input_hint)
        input_payload = command.get("input")
        if isinstance(input_payload, dict) and isinstance(
            input_payload.get("hint"), str
        ):
            return _sanitize(input_payload["hint"])
        return None

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
        existing = self._activities.get(aid)
        if existing is not None:
            self._activities[aid] = existing.model_copy(
                update={
                    "kind": kind,
                    "label": _sanitize(f"{tool_name} call"),
                    "status": existing.status,
                    "updated_at": now,
                    "source_tool_call_id": tool_call_id,
                }
            )
        else:
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
        self._index_tool_call(session_id, tool_call_id, aid)

    def _on_tool_call_update(self, event: dict[str, Any]) -> None:
        session_id = event.get("sessionId")
        if session_id is not None and not isinstance(session_id, str):
            return
        tool_call_id = event.get("toolCallId")
        if not isinstance(tool_call_id, str):
            return
        aid = self._tool_call_activity_id(session_id, tool_call_id)
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
        aid = self._tool_call_activity_id(session_id, tool_call_id)
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
        self._index_tool_call(session_id, tool_call_id, aid)

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
