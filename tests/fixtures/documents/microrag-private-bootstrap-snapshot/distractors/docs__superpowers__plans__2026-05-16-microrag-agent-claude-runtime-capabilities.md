# MicroRAG Agent Claude Runtime Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin ACP-backed command picker and redacted activity stream so the MicroRAG agent frontend can visibly show Claude Code-backed slash commands, skills, tools, and subagents without rebuilding Claude Code runtime capabilities.

**Architecture:** Keep Claude Code as the runtime owner for slash commands, skills, memory, subagents, tool permissions, shell execution, and transcript persistence. Add a MicroRAG-owned projection layer that converts ACP/runtime hints into UI-safe command summaries and activity rows, then render those rows in the existing FastAPI HTML + static JS/CSS agent shell. Do not implement MCP and do not persist transcript or memory content in MicroRAG SQLite.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, pytest, static HTML/CSS/vanilla JavaScript under `src/ragflow_lite/static`, existing ACP stdio adapter, `rtk` command prefix.

---

## Source Spec

Implement the approved boundaries in:

```text
docs/superpowers/specs/2026-05-16-microrag-agent-claude-runtime-capabilities.md
```

This plan intentionally depends on the existing runtime workspace specs:

```text
docs/superpowers/specs/2026-05-14-microrag-agent-demo-shell.md
docs/superpowers/specs/2026-05-15-microrag-agent-runtime-workspace-isolation.md
docs/superpowers/specs/2026-05-16-microrag-agent-system-prompt-identity-boundary.md
```

## Current Code Shape

Current backend:

```text
src/ragflow_lite/api/routes/agent.py
```

Responsibility: session list/create/resume/delete/message routes. It currently returns UI-safe session and message responses.

```text
src/ragflow_lite/api/schemas/agent.py
```

Responsibility: Pydantic request/response schemas for agent shell APIs.

```text
src/ragflow_lite/infrastructure/agent/acp_client.py
```

Responsibility: ACP stdio process startup, JSON-RPC request/response handling, message chunk collection, and redaction helpers. It currently collects `agent_message_chunk` text but does not expose command summaries or activity rows.

```text
src/ragflow_lite/infrastructure/agent/session_store.py
```

Responsibility: thin UI metadata only. Keep this invariant: no transcript body, no memory content, no full conversation copy.

Current frontend:

```text
src/ragflow_lite/api/routes/ui.py
src/ragflow_lite/static/agent-shell.js
src/ragflow_lite/static/agent-shell.css
```

Responsibility: `/agent` HTML shell plus static JavaScript/CSS. There is no React/Vite/frontend package in this repo, so this plan uses the existing static shell instead of adding a new frontend toolchain.

## File Structure

Create:

```text
src/ragflow_lite/infrastructure/agent/activity_projection.py
```

Responsibility: product-owned in-memory projection of ACP/runtime hints into UI-safe command summaries and activity rows. This file is deliberately not a Claude Code runtime clone; it only maps observed events into redacted UI state.

Modify:

```text
src/ragflow_lite/infrastructure/agent/acp_client.py
```

Responsibility: feed ACP events into `AgentRuntimeProjection` while preserving existing message chunk behavior and redaction boundaries.

Modify:

```text
src/ragflow_lite/api/schemas/agent.py
```

Responsibility: add UI-safe response schemas for command summaries and activity rows.

Modify:

```text
src/ragflow_lite/api/routes/agent.py
```

Responsibility: add read-only command/activity endpoints backed by the ACP client's projection snapshot. Do not add a slash-command execution endpoint.

Modify:

```text
src/ragflow_lite/api/routes/ui.py
src/ragflow_lite/static/agent-shell.js
src/ragflow_lite/static/agent-shell.css
```

Responsibility: render slash picker and demo activity stream in the existing static UI. Slash picker selection pre-fills input text only.

Modify tests:

```text
tests/unit/infrastructure/test_acp_client_redaction.py
tests/unit/api/test_agent_routes.py
tests/unit/infrastructure/test_agent_session_store.py
tests/integration/api/test_ui_shell.py
```

Create tests:

```text
tests/unit/infrastructure/test_agent_activity_projection.py
```

Responsibility: focused tests for redacted command summaries and activity projection without spinning up the API.

## Execution Guardrails

- The current worktree already has tracked dirty files in the agent/ACP area. Before implementation, inspect the existing diff and work with it; do not reset or overwrite it.
- Do not modify production dependency declarations, schemas outside the agent API, CI/release workflow, or secrets.
- Do not configure, surface, or depend on MCP in this stage.
- Do not parse `SKILL.md` or memory files in frontend or backend.
- Do not persist command/activity rows into SQLite in the first pass. Keep them process-local UI projection state unless a later spec changes persistence.
- Keep redaction backend-owned. Frontend receives only UI-safe product shapes.

## Task 0: Baseline Review Before Editing

Purpose: avoid trampling existing user or prior-agent changes in the dirty ACP/agent files.

**Files:**
- Read: `scripts/run_reference_claude_code.sh`
- Read: `src/ragflow_lite/api/routes/agent.py`
- Read: `src/ragflow_lite/infrastructure/agent/acp_client.py`
- Read: `tests/unit/api/test_agent_routes.py`
- Read: `tests/unit/infrastructure/test_acp_client_redaction.py`
- Read: `tests/unit/test_reference_claude_code_script.py`

- [ ] **Step 1: Inspect the dirty file list**

Run:

```bash
rtk git status --short
```

Expected current dirty files include:

```text
 M scripts/run_reference_claude_code.sh
 M src/ragflow_lite/api/routes/agent.py
 M src/ragflow_lite/infrastructure/agent/acp_client.py
 M tests/unit/api/test_agent_routes.py
 M tests/unit/infrastructure/test_acp_client_redaction.py
 M tests/unit/test_reference_claude_code_script.py
```

- [ ] **Step 2: Inspect the existing ACP/agent diff before making edits**

Run:

```bash
rtk git diff -- src/ragflow_lite/api/routes/agent.py src/ragflow_lite/infrastructure/agent/acp_client.py tests/unit/api/test_agent_routes.py tests/unit/infrastructure/test_acp_client_redaction.py
```

Expected: review output manually and identify which changes are already present. Do not revert unrelated changes.

- [ ] **Step 3: Run current focused tests as a baseline**

Run:

```bash
rtk pytest tests/unit/api/test_agent_routes.py tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/infrastructure/test_agent_session_store.py tests/integration/api/test_ui_shell.py -q
```

Expected: record pass/fail before editing. If failures are unrelated dirty-baseline failures, note them before continuing.

## Task 1: Add Product Activity Projection Unit

Purpose: create a small, testable backend projection layer for command summaries and skill/subagent/tool/permission activity rows.

**Files:**
- Create: `src/ragflow_lite/infrastructure/agent/activity_projection.py`
- Create: `tests/unit/infrastructure/test_agent_activity_projection.py`

- [ ] **Step 1: Write failing projection tests**

Create `tests/unit/infrastructure/test_agent_activity_projection.py`:

```python
from __future__ import annotations

from ragflow_lite.infrastructure.agent.activity_projection import (
    AgentRuntimeProjection,
)


def test_available_commands_update_becomes_ui_safe_summaries() -> None:
    projection = AgentRuntimeProjection()

    projection.record_event(
        {
            "method": "session/update",
            "params": {
                "update": {
                    "type": "available_commands_update",
                    "commands": [
                        {
                            "name": "microrag-search",
                            "description": "Search MicroRAG",
                            "input": {"hint": "question"},
                            "source": "/home/xia/ragflow-lite/.claude/skills/microrag-search/SKILL.md",
                        }
                    ],
                }
            },
        }
    )

    summaries = projection.command_summaries()

    assert [summary.name for summary in summaries] == ["microrag-search"]
    assert summaries[0].description == "Search MicroRAG"
    assert summaries[0].input_hint == "question"
    assert summaries[0].source == "runtime"
    assert "SKILL.md" not in summaries[0].model_dump_json()


def test_agent_tool_call_creates_and_completes_subagent_activity() -> None:
    projection = AgentRuntimeProjection()

    projection.record_event(
        {
            "method": "session/update",
            "params": {
                "sessionId": "session-1",
                "update": {
                    "type": "tool_call",
                    "toolCallId": "tool-1",
                    "name": "Agent",
                    "title": "Researching with subagent",
                },
            },
        }
    )
    projection.record_event(
        {
            "method": "session/update",
            "params": {
                "sessionId": "session-1",
                "update": {
                    "type": "tool_call_update",
                    "toolCallId": "tool-1",
                    "status": "completed",
                },
            },
        }
    )

    activities = projection.activities_for_session("session-1")

    assert len(activities) == 1
    assert activities[0].kind == "subagent"
    assert activities[0].label == "Subagent"
    assert activities[0].status == "completed"
    assert activities[0].source_tool_call_id == "tool-1"


def test_skill_progress_text_is_redacted_before_activity_summary() -> None:
    projection = AgentRuntimeProjection()

    projection.record_event(
        {
            "method": "session/update",
            "params": {
                "sessionId": "session-1",
                "update": {
                    "type": "agent_message_chunk",
                    "content": {
                        "type": "text",
                        "text": "skill_progress: running /home/xia/ragflow-lite/.claude/skills/microrag-search/SKILL.md stderr traceback",
                    },
                },
            },
        }
    )

    activities = projection.activities_for_session("session-1")

    assert len(activities) == 1
    assert activities[0].kind == "skill"
    assert activities[0].status == "running"
    assert "MicroRAG skill" in activities[0].label
    serialized = activities[0].model_dump_json()
    assert "/home/xia" not in serialized
    assert "SKILL.md" not in serialized
    assert "stderr" not in serialized
    assert "traceback" not in serialized


def test_permission_request_creates_waiting_activity_without_raw_input() -> None:
    projection = AgentRuntimeProjection()

    projection.record_event(
        {
            "method": "session/update",
            "params": {
                "sessionId": "session-1",
                "update": {
                    "type": "permission_request",
                    "toolCallId": "tool-2",
                    "toolName": "Bash",
                    "input": {"command": "cat /home/xia/secret"},
                },
            },
        }
    )

    activities = projection.activities_for_session("session-1")

    assert activities[0].kind == "permission"
    assert activities[0].status == "waiting_for_permission"
    assert activities[0].label == "Permission required"
    serialized = activities[0].model_dump_json()
    assert "cat /home/xia/secret" not in serialized
    assert "tool-2" in serialized
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_agent_activity_projection.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'ragflow_lite.infrastructure.agent.activity_projection'
```

- [ ] **Step 3: Implement the projection module**

Create `src/ragflow_lite/infrastructure/agent/activity_projection.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Literal

from pydantic import BaseModel

ActivityKind = Literal["skill", "subagent", "tool", "command", "permission", "plan"]
ActivityStatus = Literal[
    "queued",
    "started",
    "running",
    "waiting_for_permission",
    "completed",
    "failed",
    "cancelled",
]

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_SUBAGENT_TOOLS = {"agent", "task"}
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


class AgentCommandSummary(BaseModel):
    name: str
    description: str
    input_hint: str | None = None
    updated_at: datetime
    source: Literal["runtime"] = "runtime"


class AgentActivity(BaseModel):
    activity_id: str
    session_id: str
    kind: ActivityKind
    label: str
    status: ActivityStatus
    summary: str | None = None
    source_message_id: str | None = None
    source_tool_call_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentRuntimeProjection:
    def __init__(self) -> None:
        self._commands: dict[str, AgentCommandSummary] = {}
        self._activities: dict[str, AgentActivity] = {}

    def record_event(self, event: dict[str, Any]) -> None:
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        update_type = self._update_type(update)

        if update_type == "available_commands_update":
            self._record_commands(update)
            return

        session_id = self._safe_session_id(params)
        if not session_id:
            return

        if update_type == "tool_call":
            self._record_tool_call(session_id, update)
        elif update_type == "tool_call_update":
            self._record_tool_call_update(session_id, update)
        elif update_type == "permission_request":
            self._upsert_activity(
                session_id=session_id,
                kind="permission",
                label="Permission required",
                status="waiting_for_permission",
                summary="Runtime is waiting for permission.",
                source_tool_call_id=self._safe_str(update.get("toolCallId")),
            )
        elif update_type in {"agent_message_chunk", "thought"}:
            self._record_progress_text(session_id, update)
        elif update_type == "plan":
            self._upsert_activity(
                session_id=session_id,
                kind="plan",
                label="Plan updated",
                status="running",
                summary="Runtime plan changed.",
            )

    def command_summaries(self) -> list[AgentCommandSummary]:
        return sorted(self._commands.values(), key=lambda command: command.name)

    def activities_for_session(self, session_id: str) -> list[AgentActivity]:
        return sorted(
            (
                activity
                for activity in self._activities.values()
                if activity.session_id == session_id
            ),
            key=lambda activity: (activity.created_at, activity.activity_id),
        )

    def _record_commands(self, update: dict[str, Any]) -> None:
        now = _utcnow()
        commands = update.get("commands")
        if not isinstance(commands, list):
            return
        for raw_command in commands:
            if not isinstance(raw_command, dict):
                continue
            name = self._safe_str(raw_command.get("name"))
            description = self._safe_str(raw_command.get("description"))
            if not name or not description:
                continue
            raw_input = raw_command.get("input")
            input_hint = None
            if isinstance(raw_input, dict):
                input_hint = self._sanitize(raw_input.get("hint"))
            self._commands[name] = AgentCommandSummary(
                name=name,
                description=self._sanitize(description) or "Runtime command",
                input_hint=input_hint,
                updated_at=now,
            )

    def _record_tool_call(self, session_id: str, update: dict[str, Any]) -> None:
        tool_name = self._safe_str(update.get("name") or update.get("toolName")) or "Tool"
        kind: ActivityKind = (
            "subagent" if tool_name.lower() in _SUBAGENT_TOOLS else "tool"
        )
        label = "Subagent" if kind == "subagent" else self._sanitize(tool_name) or "Tool"
        self._upsert_activity(
            session_id=session_id,
            kind=kind,
            label=label,
            status="started",
            summary=self._sanitize(update.get("title")) or f"{label} started.",
            source_tool_call_id=self._safe_str(update.get("toolCallId")),
        )

    def _record_tool_call_update(self, session_id: str, update: dict[str, Any]) -> None:
        source_tool_call_id = self._safe_str(update.get("toolCallId"))
        status = self._normalize_status(update.get("status"))
        self._upsert_activity(
            session_id=session_id,
            kind=self._existing_kind(source_tool_call_id) or "tool",
            label=self._existing_label(source_tool_call_id) or "Tool",
            status=status,
            summary=f"Activity {status}.",
            source_tool_call_id=source_tool_call_id,
        )

    def _record_progress_text(self, session_id: str, update: dict[str, Any]) -> None:
        text = self._extract_text(update)
        lowered = text.lower()
        if "skill_progress" in lowered:
            self._upsert_activity(
                session_id=session_id,
                kind="skill",
                label="MicroRAG skill running",
                status="running",
                summary=self._sanitize(text) or "Skill is running.",
            )
        elif "agent_progress" in lowered or "subagent" in lowered:
            self._upsert_activity(
                session_id=session_id,
                kind="subagent",
                label="Subagent",
                status="running",
                summary=self._sanitize(text) or "Subagent is running.",
            )

    def _upsert_activity(
        self,
        *,
        session_id: str,
        kind: ActivityKind,
        label: str,
        status: ActivityStatus,
        summary: str | None,
        source_tool_call_id: str | None = None,
        source_message_id: str | None = None,
    ) -> None:
        now = _utcnow()
        activity_id = self._activity_id(session_id, kind, source_tool_call_id, label)
        existing = self._activities.get(activity_id)
        created_at = existing.created_at if existing else now
        self._activities[activity_id] = AgentActivity(
            activity_id=activity_id,
            session_id=session_id,
            kind=kind,
            label=self._sanitize(label) or label,
            status=status,
            summary=self._sanitize(summary),
            source_message_id=source_message_id,
            source_tool_call_id=source_tool_call_id,
            created_at=created_at,
            updated_at=now,
        )

    def _activity_id(
        self,
        session_id: str,
        kind: ActivityKind,
        source_tool_call_id: str | None,
        label: str,
    ) -> str:
        source = source_tool_call_id or f"{kind}:{label}"
        digest = sha1(f"{session_id}:{source}".encode("utf-8")).hexdigest()[:12]
        return f"activity-{digest}"

    def _existing_kind(self, source_tool_call_id: str | None) -> ActivityKind | None:
        for activity in self._activities.values():
            if activity.source_tool_call_id == source_tool_call_id:
                return activity.kind
        return None

    def _existing_label(self, source_tool_call_id: str | None) -> str | None:
        for activity in self._activities.values():
            if activity.source_tool_call_id == source_tool_call_id:
                return activity.label
        return None

    def _normalize_status(self, raw_status: Any) -> ActivityStatus:
        value = self._safe_str(raw_status).lower()
        if value in _TERMINAL_STATUSES:
            return value  # type: ignore[return-value]
        if value in {"running", "started", "queued", "waiting_for_permission"}:
            return value  # type: ignore[return-value]
        return "running"

    def _update_type(self, update: dict[str, Any]) -> str:
        for key in ("type", "kind", "sessionUpdate"):
            value = self._safe_str(update.get(key))
            if value:
                return value
        return ""

    def _safe_session_id(self, params: dict[str, Any]) -> str | None:
        return self._safe_str(params.get("sessionId") or params.get("session_id"))

    def _extract_text(self, update: dict[str, Any]) -> str:
        content = update.get("content")
        if isinstance(content, dict):
            return self._safe_str(content.get("text")) or ""
        return self._safe_str(update.get("text")) or ""

    def _sanitize(self, value: Any) -> str | None:
        text = self._safe_str(value)
        if not text:
            return None
        sanitized = text
        for marker in _SENSITIVE_MARKERS:
            sanitized = sanitized.replace(marker, "[redacted]")
        return sanitized[:240]

    def _safe_str(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 4: Run the projection tests**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_agent_activity_projection.py -q
```

Expected:

```text
4 passed
```

## Task 2: Wire Projection Into ACP Client

Purpose: feed runtime events into the projection without changing Claude Code execution semantics.

**Files:**
- Modify: `src/ragflow_lite/infrastructure/agent/acp_client.py`
- Modify: `tests/unit/infrastructure/test_acp_client_redaction.py`

- [ ] **Step 1: Add failing ACP client tests for projection snapshots**

Append these tests to `tests/unit/infrastructure/test_acp_client_redaction.py`, adapting existing fake process helpers in that file rather than creating a second fake framework:

```python
def test_acp_client_records_available_commands_update() -> None:
    process = FakeAcpProcess(
        responses=[
            acp_response(1, {"protocolVersion": 1}),
            acp_notification(
                "session/update",
                {
                    "update": {
                        "type": "available_commands_update",
                        "commands": [
                            {
                                "name": "microrag-search",
                                "description": "Search MicroRAG",
                                "input": {"hint": "question"},
                            }
                        ],
                    }
                },
            ),
            acp_response(2, {"sessionId": "session-1"}),
        ]
    )
    client = make_client(process)

    client.initialize()
    client.new_session()

    commands = client.command_summaries()

    assert [command.name for command in commands] == ["microrag-search"]
    assert commands[0].input_hint == "question"


def test_acp_client_records_agent_tool_activity() -> None:
    process = FakeAcpProcess(
        responses=[
            acp_response(1, {"protocolVersion": 1}),
            acp_notification(
                "session/update",
                {
                    "sessionId": "session-1",
                    "update": {
                        "type": "tool_call",
                        "toolCallId": "tool-1",
                        "name": "Task",
                    },
                },
            ),
            acp_notification(
                "session/update",
                {
                    "sessionId": "session-1",
                    "update": {
                        "type": "tool_call_update",
                        "toolCallId": "tool-1",
                        "status": "completed",
                    },
                },
            ),
            acp_response(2, {"content": [{"type": "text", "text": "done"}]}),
        ]
    )
    client = make_client(process)

    client.initialize()
    client.send_message(session_id="session-1", prompt="run task")

    activities = client.activities_for_session("session-1")

    assert len(activities) == 1
    assert activities[0].kind == "subagent"
    assert activities[0].status == "completed"
```

Use the helper names that already exist in the file. If the existing helpers are named differently, keep their current names and only add the assertions above.

- [ ] **Step 2: Run the focused ACP test and verify it fails**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_acp_client_redaction.py -q
```

Expected: new tests fail because `AcpClient` does not yet expose `command_summaries()` or `activities_for_session()`.

- [ ] **Step 3: Add projection ownership to `AcpClient`**

In `src/ragflow_lite/infrastructure/agent/acp_client.py`, import the projection classes:

```python
from ragflow_lite.infrastructure.agent.activity_projection import (
    AgentActivity,
    AgentCommandSummary,
    AgentRuntimeProjection,
)
```

In `AcpClient.__init__`, add:

```python
self._projection = AgentRuntimeProjection()
```

Add public snapshot methods:

```python
def command_summaries(self) -> list[AgentCommandSummary]:
    return self._projection.command_summaries()


def activities_for_session(self, session_id: str) -> list[AgentActivity]:
    return self._projection.activities_for_session(session_id)
```

- [ ] **Step 4: Record runtime notifications before existing message aggregation**

In the loop that reads ACP messages inside `_request()`, call the projection for every notification/update before the existing branch that handles `agent_message_chunk`:

```python
if isinstance(message, dict):
    self._projection.record_event(message)
```

Keep the existing `agent_message_chunk` aggregation behavior unchanged so ordinary chat responses still work.

- [ ] **Step 5: Run focused ACP tests**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/infrastructure/test_agent_activity_projection.py -q
```

Expected:

```text
passed
```

## Task 3: Add UI-Safe API Schemas And Routes

Purpose: expose command summaries and per-session activities to the frontend without exposing raw ACP/runtime internals.

**Files:**
- Modify: `src/ragflow_lite/api/schemas/agent.py`
- Modify: `src/ragflow_lite/api/routes/agent.py`
- Modify: `tests/unit/api/test_agent_routes.py`

- [ ] **Step 1: Add failing API route tests**

Append tests to `tests/unit/api/test_agent_routes.py` using the existing `TestClient` fixture and fake services pattern:

```python
def test_get_agent_commands_returns_runtime_summaries(client: TestClient) -> None:
    response = client.get("/api/v0/agent/commands")

    assert response.status_code == 200
    body = response.json()
    assert body["commands"] == [
        {
            "name": "microrag-search",
            "description": "Search MicroRAG",
            "input_hint": "question",
            "source": "runtime",
        }
    ]
    assert "SKILL.md" not in response.text
    assert "transcript_path" not in response.text


def test_get_agent_activity_returns_sanitized_rows(client: TestClient) -> None:
    response = client.get("/api/v0/agent/sessions/ui-session-1/activity")

    assert response.status_code == 200
    body = response.json()
    assert body["activities"][0]["kind"] == "subagent"
    assert body["activities"][0]["status"] == "running"
    assert body["activities"][0]["label"] == "Subagent"
    assert "/home/xia" not in response.text
    assert "stderr" not in response.text
    assert "traceback" not in response.text


def test_no_slash_command_execution_endpoint_exists(client: TestClient) -> None:
    response = client.post(
        "/api/v0/agent/commands/microrag-search",
        json={"input": "question"},
    )

    assert response.status_code == 404
```

Update the existing fake ACP client in the test file so it exposes:

```python
def command_summaries(self) -> list[AgentCommandSummary]:
    return [
        AgentCommandSummary(
            name="microrag-search",
            description="Search MicroRAG",
            input_hint="question",
            updated_at=datetime.now(timezone.utc),
        )
    ]


def activities_for_session(self, session_id: str) -> list[AgentActivity]:
    return [
        AgentActivity(
            activity_id="activity-1",
            session_id="claude-session-1",
            kind="subagent",
            label="Subagent",
            status="running",
            summary="Subagent is running.",
            source_tool_call_id="tool-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    ]
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```bash
rtk pytest tests/unit/api/test_agent_routes.py -q
```

Expected: route tests fail with 404 for the new read-only endpoints.

- [ ] **Step 3: Add response schemas**

In `src/ragflow_lite/api/schemas/agent.py`, add:

```python
class AgentCommandSummaryResponse(BaseModel):
    name: str
    description: str
    input_hint: str | None = None
    source: Literal["runtime"] = "runtime"


class AgentCommandsResponse(BaseModel):
    commands: list[AgentCommandSummaryResponse]


class AgentActivityResponse(BaseModel):
    activity_id: str
    kind: Literal["skill", "subagent", "tool", "command", "permission", "plan"]
    label: str
    status: Literal[
        "queued",
        "started",
        "running",
        "waiting_for_permission",
        "completed",
        "failed",
        "cancelled",
    ]
    summary: str | None = None
    source_message_id: str | None = None
    source_tool_call_id: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentActivitiesResponse(BaseModel):
    activities: list[AgentActivityResponse]
```

If `Literal` or `datetime` are not imported in the file, add:

```python
from datetime import datetime
from typing import Literal
```

- [ ] **Step 4: Add read-only routes**

In `src/ragflow_lite/api/routes/agent.py`, add:

```python
@router.get("/commands", response_model=AgentCommandsResponse)
def list_agent_commands(request: Request) -> AgentCommandsResponse:
    acp_client = _get_acp_client(request)
    commands = acp_client.command_summaries()
    return AgentCommandsResponse(
        commands=[
            AgentCommandSummaryResponse(
                name=command.name,
                description=command.description,
                input_hint=command.input_hint,
                source=command.source,
            )
            for command in commands
        ]
    )


@router.get("/sessions/{session_id}/activity", response_model=AgentActivitiesResponse)
def list_agent_activity(session_id: str, request: Request) -> AgentActivitiesResponse:
    store = _get_session_store(request)
    record = store.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    acp_client = _get_acp_client(request)
    activities = acp_client.activities_for_session(record.claude_session_id)
    return AgentActivitiesResponse(
        activities=[
            AgentActivityResponse(
                activity_id=activity.activity_id,
                kind=activity.kind,
                label=activity.label,
                status=activity.status,
                summary=activity.summary,
                source_message_id=activity.source_message_id,
                source_tool_call_id=activity.source_tool_call_id,
                created_at=activity.created_at,
                updated_at=activity.updated_at,
            )
            for activity in activities
        ]
    )
```

Import the new schema classes from `ragflow_lite.api.schemas.agent`.

- [ ] **Step 5: Run route tests**

Run:

```bash
rtk pytest tests/unit/api/test_agent_routes.py -q
```

Expected:

```text
passed
```

## Task 4: Add Slash Picker And Activity Stream To Static UI

Purpose: make runtime command suggestions and demo-visible skill/subagent/tool activity visible in `/agent`.

**Files:**
- Modify: `src/ragflow_lite/api/routes/ui.py`
- Modify: `src/ragflow_lite/static/agent-shell.js`
- Modify: `src/ragflow_lite/static/agent-shell.css`
- Modify: `tests/integration/api/test_ui_shell.py`

- [ ] **Step 1: Add failing UI shell tests**

In `tests/integration/api/test_ui_shell.py`, add:

```python
def test_agent_shell_contains_command_picker_and_activity_hosts(client: TestClient) -> None:
    response = client.get("/agent")

    assert response.status_code == 200
    assert 'id="slash-picker"' in response.text
    assert 'id="activity-stream"' in response.text
    assert 'id="composer-toolbar"' in response.text
    assert "Claude Code" not in response.text
    assert "transcript_path" not in response.text
    assert "runtime_cwd" not in response.text


def test_agent_shell_script_contains_slash_prefill_not_command_execution(
    client: TestClient,
) -> None:
    response = client.get("/static/agent-shell.js")

    assert response.status_code == 200
    assert "loadCommandSummaries" in response.text
    assert "renderSlashPicker" in response.text
    assert "selectSlashCommand" in response.text
    assert "renderActivityStream" in response.text
    assert "/api/v0/agent/commands/" not in response.text
```

- [ ] **Step 2: Run UI integration tests and verify they fail**

Run:

```bash
rtk pytest tests/integration/api/test_ui_shell.py -q
```

Expected: new DOM/script assertions fail because picker/activity hosts do not exist yet.

- [ ] **Step 3: Add HTML hosts to `/agent` shell**

In `src/ragflow_lite/api/routes/ui.py`, add these elements near the existing chat/composer area:

```html
<div id="activity-stream" class="activity-stream" aria-live="polite"></div>
<div id="composer-toolbar" class="composer-toolbar">
  <div id="slash-picker" class="slash-picker" hidden></div>
</div>
```

Place `activity-stream` between the chat area and composer. Place `slash-picker` close to the composer input so it behaves like a command popover.

- [ ] **Step 4: Add command and activity JavaScript**

In `src/ragflow_lite/static/agent-shell.js`, add state near the top of the IIFE:

```javascript
let commandSummaries = [];
let localActivities = [];
```

Add these functions:

```javascript
async function loadCommandSummaries() {
  const data = await api('/api/v0/agent/commands');
  commandSummaries = Array.isArray(data.commands) ? data.commands : [];
  renderSlashPicker();
}

async function loadActivityStream() {
  if (!currentSessionId) {
    renderActivityStream([]);
    return;
  }
  const data = await api(`/api/v0/agent/sessions/${currentSessionId}/activity`);
  const runtimeActivities = Array.isArray(data.activities) ? data.activities : [];
  renderActivityStream([...localActivities, ...runtimeActivities]);
}

function renderSlashPicker() {
  const picker = document.getElementById('slash-picker');
  const input = document.getElementById('composer-input');
  if (!picker || !input) {
    return;
  }
  const value = input.value.trimStart();
  if (!value.startsWith('/')) {
    picker.hidden = true;
    picker.replaceChildren();
    return;
  }
  const query = value.slice(1).toLowerCase();
  const matches = commandSummaries
    .filter((command) => command.name.toLowerCase().startsWith(query))
    .slice(0, 8);
  if (matches.length === 0) {
    picker.hidden = true;
    picker.replaceChildren();
    return;
  }
  picker.hidden = false;
  picker.replaceChildren(
    ...matches.map((command) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'slash-picker-item';
      button.dataset.commandName = command.name;
      button.innerHTML = `<strong>/${escapeHtml(command.name)}</strong><span>${escapeHtml(command.description || '')}</span>`;
      button.addEventListener('click', () => selectSlashCommand(command));
      return button;
    }),
  );
}

function selectSlashCommand(command) {
  const input = document.getElementById('composer-input');
  if (!input) {
    return;
  }
  input.value = `/${command.name} `;
  input.focus();
  addLocalActivity({
    kind: 'command',
    label: `/${command.name}`,
    status: 'queued',
    summary: 'Command selected. It will run only when the message is sent.',
  });
  renderSlashPicker();
}

function addLocalActivity(activity) {
  const now = new Date().toISOString();
  localActivities = [
    {
      activity_id: `local-${now}-${activity.kind}-${activity.label}`,
      created_at: now,
      updated_at: now,
      ...activity,
    },
    ...localActivities,
  ].slice(0, 10);
  renderActivityStream(localActivities);
}

function renderActivityStream(activities) {
  const stream = document.getElementById('activity-stream');
  if (!stream) {
    return;
  }
  const visible = activities.slice(-8);
  stream.replaceChildren(
    ...visible.map((activity) => {
      const row = document.createElement('div');
      row.className = `activity-row activity-${activity.kind} activity-${activity.status}`;
      row.innerHTML = `
        <span class="activity-dot" aria-hidden="true"></span>
        <span class="activity-main">
          <strong>${escapeHtml(activity.label || 'Activity')}</strong>
          <small>${escapeHtml(activity.summary || activity.status || '')}</small>
        </span>
        <span class="activity-status">${escapeHtml(activity.status || '')}</span>
      `;
      return row;
    }),
  );
}
```

Add this helper if the script does not already have it:

```javascript
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
```

Call `loadCommandSummaries()` during startup and after session creation/resume. Add `input` event handling:

```javascript
document.getElementById('composer-input')?.addEventListener('input', renderSlashPicker);
```

After `sendMessage()` receives a response, call:

```javascript
await loadActivityStream();
```

If the outgoing message starts with `/`, add a local started row before posting:

```javascript
if (message.trimStart().startsWith('/')) {
  addLocalActivity({
    kind: 'command',
    label: message.trimStart().split(/\s+/, 1)[0],
    status: 'started',
    summary: 'Command submitted to runtime.',
  });
}
```

Do not add any `fetch('/api/v0/agent/commands/<name>')` or command execution endpoint call.

- [ ] **Step 5: Add CSS for picker and activity animation**

In `src/ragflow_lite/static/agent-shell.css`, add:

```css
.composer-toolbar {
  position: relative;
}

.slash-picker {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0.5rem;
  z-index: 20;
  display: grid;
  gap: 0.25rem;
  max-height: 14rem;
  overflow: auto;
  padding: 0.4rem;
  border: 1px solid rgba(31, 41, 55, 0.16);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
}

.slash-picker[hidden] {
  display: none;
}

.slash-picker-item {
  display: grid;
  grid-template-columns: minmax(8rem, 1fr) minmax(0, 2fr);
  gap: 0.75rem;
  align-items: center;
  width: 100%;
  min-height: 2.25rem;
  padding: 0.45rem 0.6rem;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #111827;
  text-align: left;
  cursor: pointer;
}

.slash-picker-item:hover,
.slash-picker-item:focus-visible {
  background: #eef2ff;
  outline: none;
}

.slash-picker-item span {
  overflow: hidden;
  color: #4b5563;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-stream {
  display: grid;
  gap: 0.45rem;
  min-height: 0;
  padding: 0.5rem 1rem;
  border-top: 1px solid rgba(31, 41, 55, 0.08);
  background: #f8fafc;
}

.activity-row {
  display: grid;
  grid-template-columns: 0.7rem minmax(0, 1fr) auto;
  gap: 0.65rem;
  align-items: center;
  min-height: 2.25rem;
  padding: 0.45rem 0.6rem;
  border: 1px solid rgba(31, 41, 55, 0.08);
  border-radius: 8px;
  background: #ffffff;
  animation: activity-enter 160ms ease-out;
}

.activity-dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  background: #2563eb;
}

.activity-running .activity-dot,
.activity-started .activity-dot,
.activity-waiting_for_permission .activity-dot {
  animation: activity-pulse 1.1s ease-in-out infinite;
}

.activity-completed .activity-dot {
  background: #059669;
}

.activity-failed .activity-dot {
  background: #dc2626;
}

.activity-cancelled .activity-dot {
  background: #6b7280;
}

.activity-main {
  display: grid;
  gap: 0.1rem;
  min-width: 0;
}

.activity-main strong,
.activity-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-main small,
.activity-status {
  color: #6b7280;
  font-size: 0.78rem;
}

@keyframes activity-enter {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes activity-pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.86);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}
```

- [ ] **Step 6: Run UI integration tests**

Run:

```bash
rtk pytest tests/integration/api/test_ui_shell.py -q
```

Expected:

```text
passed
```

## Task 5: Preserve Metadata, Runtime Workspace, And MCP Boundaries

Purpose: pin the negative requirements from the spec so implementation cannot accidentally leak transcript/memory/runtime details or surface MCP.

**Files:**
- Modify: `tests/unit/infrastructure/test_agent_session_store.py`
- Modify: `tests/unit/api/test_agent_routes.py`
- Modify: `tests/integration/api/test_ui_shell.py`
- Modify only if tests expose a real gap: `src/ragflow_lite/infrastructure/agent/session_store.py`, `src/ragflow_lite/api/routes/agent.py`, `src/ragflow_lite/static/agent-shell.js`

- [ ] **Step 1: Add metadata-store negative assertions**

In `tests/unit/infrastructure/test_agent_session_store.py`, add or extend a test:

```python
def test_agent_session_store_does_not_persist_activity_transcript_or_memory(
    tmp_path: Path,
) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")

    store.create(
        title="Session",
        claude_session_id="claude-session-1",
        transcript_path="/runtime/transcript.jsonl",
        runtime_cwd="/runtime/workspace",
    )

    with sqlite3.connect(tmp_path / "agent_sessions.sqlite3") as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_sessions)").fetchall()
        }

    assert "messages" not in columns
    assert "conversation" not in columns
    assert "transcript_json" not in columns
    assert "memory" not in columns
    assert "activities" not in columns
    assert "command_summaries" not in columns
```

Use the existing imports in the file. Add `sqlite3` or `Path` imports only if they are not already present.

- [ ] **Step 2: Add UI/API MCP and runtime-leak negative checks**

Extend `tests/integration/api/test_ui_shell.py`:

```python
def test_agent_shell_does_not_surface_mcp_or_runtime_paths(client: TestClient) -> None:
    response = client.get("/agent")

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
        assert token not in response.text
```

Extend `tests/unit/api/test_agent_routes.py`:

```python
def test_activity_and_commands_do_not_expose_mcp_or_runtime_internals(
    client: TestClient,
) -> None:
    command_response = client.get("/api/v0/agent/commands")
    activity_response = client.get("/api/v0/agent/sessions/ui-session-1/activity")

    combined = command_response.text + activity_response.text
    for token in [
        "MCP server",
        "mcpServers",
        "CLAUDE_CONFIG_DIR",
        "MICRORAG_AGENT_CWD",
        "transcript_path",
        "runtime_cwd",
        "stderr",
        "traceback",
        "SKILL.md",
    ]:
        assert token not in combined
```

- [ ] **Step 3: Run boundary tests and fix only real gaps**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_agent_session_store.py tests/unit/api/test_agent_routes.py tests/integration/api/test_ui_shell.py -q
```

Expected:

```text
passed
```

If a failure shows a raw runtime field in a UI response, fix the route/projection mapping. If a failure shows a new SQLite column, remove that persistence from this stage.

## Task 6: Full Focused Validation And Manual Demo Check

Purpose: prove the feature works across backend projection, API, static shell, and existing redaction boundaries.

**Files:**
- No planned edits.

- [ ] **Step 1: Run focused automated tests**

Run:

```bash
rtk pytest tests/unit/infrastructure/test_agent_activity_projection.py tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/api/test_agent_routes.py tests/unit/infrastructure/test_agent_session_store.py tests/unit/api/test_acp_wiring.py tests/unit/agent_runtime/test_setup.py tests/integration/api/test_ui_shell.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run a broader unit smoke if focused tests pass**

Run:

```bash
rtk pytest tests/unit/infrastructure tests/unit/api tests/unit/agent_runtime tests/integration/api -q
```

Expected:

```text
passed
```

- [ ] **Step 3: Start the local app for manual UI check**

Use the repo's existing app entrypoint. If the project convention has a known `rtk` server wrapper, use that. Otherwise use the existing FastAPI app target verified in the repo:

```bash
rtk uvicorn ragflow_lite.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

Expected: server starts without exposing raw Claude Code startup errors in the browser UI.

- [ ] **Step 4: Manually verify `/agent` demo behavior**

Open:

```text
http://127.0.0.1:8000/agent
```

Check:

```text
Typing "/" opens a slash picker when runtime command summaries exist.
Selecting a command pre-fills "/<command> " and does not call a command execution endpoint.
Submitting the message still goes through the ordinary message submit path.
Skill/command activity appears visibly in the activity stream.
Agent/Task tool-call events appear as subagent rows when the ACP runtime emits them.
Running rows animate with the CSS pulse.
Terminal rows show completed/failed/cancelled without raw runtime internals.
The page does not show Claude Code branding, transcript paths, cwd, stderr, tracebacks, JSON-RPC details, or MCP controls.
```

- [ ] **Step 5: Inspect final diff**

Run:

```bash
rtk git diff -- src/ragflow_lite/infrastructure/agent/activity_projection.py src/ragflow_lite/infrastructure/agent/acp_client.py src/ragflow_lite/api/schemas/agent.py src/ragflow_lite/api/routes/agent.py src/ragflow_lite/api/routes/ui.py src/ragflow_lite/static/agent-shell.js src/ragflow_lite/static/agent-shell.css tests/unit/infrastructure/test_agent_activity_projection.py tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/api/test_agent_routes.py tests/unit/infrastructure/test_agent_session_store.py tests/integration/api/test_ui_shell.py
```

Expected:

```text
Diff is limited to projection, agent API, static agent shell, and focused tests.
No MCP configuration is added.
No transcript or memory content persistence is added.
No frontend command execution endpoint is added.
```

## Self-Review Against Spec

Spec coverage:

```text
Slash command suggestions from runtime summaries -> Task 1, Task 2, Task 3, Task 4
Slash selection pre-fills text only -> Task 4
Claude Code owns slash execution -> Task 3 and Task 4 explicitly avoid execution endpoint
Skill runtime remains Claude Code -> Task 1 and Task 2 project events only
Memory runtime remains Claude Code -> Task 5 prevents memory persistence/display
Subagent runtime remains Claude Code -> Task 1 and Task 2 derive from Agent/Task tool calls only
Tool permission/runtime remains Claude Code -> Task 1 derives permission activity only
Demo-visible activity stream -> Task 4
Backend redaction boundary -> Task 1, Task 3, Task 5
MCP out of stage scope -> Task 5
No transcript duplication in SQLite -> Task 5
Manual demo validation -> Task 6
```

Known implementation risks:

```text
The exact ACP update shape may vary across Claude Code versions. The projection accepts common `type`, `kind`, and `sessionUpdate` discriminators, and tests should be adjusted only to match observed ACP bridge payloads, not to invent a new frontend protocol.
The first pass uses process-local projection state. This is acceptable for demo activity visibility but not durable activity history.
There is no browser test stack in the repo. This plan keeps frontend validation to TestClient static checks plus manual demo verification.
The existing worktree is dirty in ACP/agent files. Execution must inspect and preserve those changes before editing.
```
