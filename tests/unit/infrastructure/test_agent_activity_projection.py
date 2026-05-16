from __future__ import annotations

import json

from ragflow_lite.infrastructure.agent.activity_projection import (
    AgentActivity,
    AgentCommandSummary,
    AgentRuntimeProjection,
)


def _projection() -> AgentRuntimeProjection:
    return AgentRuntimeProjection(session_id="sess-1")


def test_available_commands_update_becomes_ui_safe_summaries() -> None:
    proj = _projection()
    proj.record_event(
        {
            "sessionUpdate": "available_commands_update",
            "commands": [
                {
                    "name": "microrag-search",
                    "description": "Search MicroRAG indexed documents",
                    "input_hint": "/microrag-search <query>",
                    "source": "/home/xia/.claude/skills/microrag-search/SKILL.md",
                },
            ],
        }
    )

    summaries = proj.command_summaries()

    assert len(summaries) == 1
    s = summaries[0]
    assert isinstance(s, AgentCommandSummary)
    assert s.name == "microrag-search"
    assert s.description == "Search MicroRAG indexed documents"
    assert s.input_hint == "/microrag-search <query>"
    assert s.source == "runtime"

    serialized = json.dumps(s.model_dump(mode="json"))
    assert "SKILL.md" not in serialized


def test_agent_tool_call_creates_and_completes_subagent_activity() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "tc-42",
            "toolName": "Agent",
            "input": {"prompt": "do work"},
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tc-42",
            "status": "completed",
        }
    )

    activities = proj.activities()
    assert len(activities) == 1
    a = activities[0]
    assert isinstance(a, AgentActivity)
    assert a.kind == "subagent"
    assert a.status == "completed"
    assert a.source_tool_call_id == "tc-42"


def test_skill_progress_text_is_redacted_before_activity_summary() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {
                "type": "text",
                "text": (
                    "skill_progress: running microrag-search\n"
                    "path=/home/xia/project/SKILL.md\n"
                    "stderr: something broke\n"
                    "traceback: detailed error info"
                ),
            },
        }
    )

    activities = proj.activities()
    assert len(activities) == 1
    a = activities[0]
    assert a.kind == "skill"
    assert a.status == "running"
    assert "MicroRAG skill" in a.label

    serialized = json.dumps(a.model_dump(mode="json"))
    for marker in ("/home/xia", "SKILL.md", "stderr", "traceback"):
        assert marker not in serialized, f"Leaked sensitive marker: {marker}"


def test_permission_request_creates_waiting_activity_without_raw_input() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "permission_request",
            "toolCallId": "tc-99",
            "toolName": "Bash",
            "input": {"command": "cat /home/xia/secret"},
        }
    )

    activities = proj.activities()
    assert len(activities) == 1
    a = activities[0]
    assert a.kind == "permission"
    assert a.status == "waiting_for_permission"
    assert a.source_tool_call_id == "tc-99"

    serialized = json.dumps(a.model_dump(mode="json"))
    assert "cat /home/xia/secret" not in serialized
    assert "/home/xia" not in serialized
    assert "tc-99" in serialized
