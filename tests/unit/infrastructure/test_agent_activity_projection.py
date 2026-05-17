from __future__ import annotations

import json

from ragflow_lite.infrastructure.agent.activity_projection import (
    AgentActivity,
    AgentCommandSummary,
    AgentRuntimeProjection,
)


def _projection() -> AgentRuntimeProjection:
    return AgentRuntimeProjection()


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
            "sessionId": "sess-1",
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
            "sessionId": "sess-1",
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


def test_sanitize_redacts_runtime_paths_and_markers_but_keeps_safe_text() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "available_commands_update",
            "commands": [
                {
                    "name": "ask-agent",
                    "description": (
                        "Safe prefix Stderr JSON-RPC mcpServers MCP server "
                        "CLAUDE_CONFIG_DIR MICRORAG_AGENT_CWD transcript_path "
                        "runtime_cwd cwd=/workspace/runtime "
                        'cwd: /workspace/runtime "cwd": "/workspace/runtime" '
                        'runtime_cwd: /workspace/runtime "runtime_cwd": "/workspace/runtime" '
                        "/tmp/session.jsonl /workspace/runtime /var/log/x "
                        r"C:\agent\session.jsonl"
                    ),
                    "input": {"hint": "How are you? See SKILL.md"},
                },
            ],
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "agent_message_chunk",
            "sessionId": "sess-1",
            "content": {
                "type": "text",
                "text": (
                    "skill_progress: Safe line before redaction. "
                    "Stderr from MCP server via JSON-RPC at /tmp/run.jsonl "
                    "cwd=/workspace/runtime runtime_cwd=/workspace/runtime "
                    'cwd: /workspace/runtime "cwd": "/workspace/runtime" '
                    'runtime_cwd: /workspace/runtime "runtime_cwd": "/workspace/runtime" '
                    "transcript_path=/tmp/transcript.jsonl "
                    r"windows=C:\agent\session.jsonl "
                    "see SKILL.md and Traceback details"
                ),
            },
        }
    )

    summaries = proj.command_summaries()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.input_hint == "How are you? See [redacted]"
    assert "Safe prefix" in summary.description

    activities = proj.activities()
    assert len(activities) == 1
    activity = activities[0]
    assert activity.summary is not None
    assert "Safe line before redaction." in activity.summary

    serialized = json.dumps(
        {
            "summary": summary.model_dump(mode="json"),
            "activity": activity.model_dump(mode="json"),
        }
    )
    for leaked in (
        "Stderr",
        "JSON-RPC",
        "mcpServers",
        "MCP server",
        "CLAUDE_CONFIG_DIR",
        "MICRORAG_AGENT_CWD",
        "transcript_path",
        "runtime_cwd",
        "cwd=/workspace/runtime",
        "cwd: /workspace/runtime",
        '"cwd": "/workspace/runtime"',
        "runtime_cwd: /workspace/runtime",
        '"runtime_cwd": "/workspace/runtime"',
        "/tmp/session.jsonl",
        "/tmp/run.jsonl",
        "/workspace/runtime",
        "/var/log/x",
        r"C:\agent\session.jsonl",
        "SKILL.md",
        "Traceback",
    ):
        assert leaked not in serialized, f"Leaked sensitive marker: {leaked}"
    assert "[redacted]" in serialized


def test_traceback_frames_and_repo_relative_paths_are_redacted() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "available_commands_update",
            "commands": [
                {
                    "name": "debug-agent",
                    "description": (
                        'Investigate File "src/ragflow_lite/infrastructure/agent/foo.py", line 1 '
                        "and tests/unit/infrastructure/test_agent_activity_projection.py "
                        "plus 参考项目/claude-code/docs/runtime.md"
                    ),
                    "input": {"hint": "/microrag-search <query>"},
                }
            ],
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "agent_message_chunk",
            "sessionId": "sess-1",
            "content": {
                "type": "text",
                "text": (
                    "skill_progress: Traceback (most recent call last):\n"
                    '  File "src/ragflow_lite/infrastructure/agent/foo.py", line 1, in <module>\n'
                    '  File "tests/unit/infrastructure/test_agent_activity_projection.py", line 2, in test_case\n'
                    '  File "参考项目/claude-code/docs/runtime.md", line 3, in helper\n'
                    "ValueError: boom"
                ),
            },
        }
    )

    summaries = proj.command_summaries()
    assert len(summaries) == 1
    assert summaries[0].input_hint == "/microrag-search <query>"

    activities = proj.activities()
    assert len(activities) == 1
    assert activities[0].summary is not None

    serialized = json.dumps(
        {
            "summary": summaries[0].model_dump(mode="json"),
            "activity": activities[0].model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    for leaked in (
        'File "src/ragflow_lite/infrastructure/agent/foo.py", line 1',
        'File "tests/unit/infrastructure/test_agent_activity_projection.py", line 2',
        'File "参考项目/claude-code/docs/runtime.md", line 3',
        "src/ragflow_lite/infrastructure/agent/foo.py",
        "tests/unit/infrastructure/test_agent_activity_projection.py",
        "参考项目/claude-code/docs/runtime.md",
    ):
        assert leaked not in serialized, f"Leaked sensitive marker: {leaked}"
    assert "/microrag-search <query>" in serialized
    assert "[redacted]" in serialized


def test_documented_input_hint_keeps_safe_slash_command() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "available_commands_update",
            "commands": [
                {
                    "name": "microrag-search",
                    "description": "Search docs",
                    "input": {"hint": "/microrag-search <query>"},
                }
            ],
        }
    )

    summaries = proj.command_summaries()
    assert len(summaries) == 1
    assert summaries[0].input_hint == "/microrag-search <query>"


def test_permission_request_creates_waiting_activity_without_raw_input() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "permission_request",
            "sessionId": "sess-1",
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


def test_skilltool_tool_call_creates_skill_activity() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tool-sk-1",
            "toolName": "SkillTool",
            "title": "Running microrag-search",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-sk-1",
            "status": "completed",
        }
    )

    activities = proj.activities()

    assert len(activities) == 1
    assert activities[0].kind == "skill"
    assert activities[0].status == "completed"


def test_permission_request_updates_existing_tool_call_activity() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tc-perm",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "permission_request",
            "sessionId": "sess-1",
            "toolCallId": "tc-perm",
            "toolName": "Bash",
            "input": {"command": "cat /home/xia/secret"},
        }
    )

    activities = proj.activities()
    assert len(activities) == 1
    a = activities[0]
    assert a.kind == "tool"
    assert a.status == "waiting_for_permission"

    serialized = json.dumps(a.model_dump(mode="json"))
    assert "cat /home/xia/secret" not in serialized


def test_permission_request_before_tool_call_keeps_waiting_permission_state() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "permission_request",
            "sessionId": "sess-1",
            "toolCallId": "tc-perm-first",
            "toolName": "Bash",
        }
    )
    first_activity = proj.activities()[0]

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tc-perm-first",
            "toolName": "Bash",
        }
    )

    activities = proj.activities_for_session("sess-1")
    assert len(activities) == 1
    activity = activities[0]
    assert activity.kind == "tool"
    assert activity.label == "Bash call"
    assert activity.status == "waiting_for_permission"
    assert activity.source_tool_call_id == "tc-perm-first"
    assert activity.created_at == first_activity.created_at


def test_permission_request_with_wrong_session_creates_current_session_activity() -> (
    None
):
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tc-perm",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "permission_request",
            "sessionId": "sess-2",
            "toolCallId": "tc-perm",
            "toolName": "Bash",
        }
    )

    session_one = proj.activities_for_session("sess-1")
    session_two = proj.activities_for_session("sess-2")

    assert len(session_one) == 1
    assert len(session_two) == 1
    assert session_one[0].status == "running"
    assert session_two[0].kind == "permission"
    assert session_two[0].status == "waiting_for_permission"


def test_same_tool_call_id_across_sessions_does_not_cross_update() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tc-shared",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-2",
            "toolCallId": "tc-shared",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call_update",
            "sessionId": "sess-1",
            "toolCallId": "tc-shared",
            "status": "completed",
        }
    )

    activities = {
        activity.session_id: activity
        for activity in proj.activities_for_session("sess-1")
        + proj.activities_for_session("sess-2")
    }
    assert activities["sess-1"].status == "completed"
    assert activities["sess-2"].status == "running"


def test_tool_call_update_without_session_id_skips_ambiguous_match() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-1",
            "toolCallId": "tc-shared",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "sess-2",
            "toolCallId": "tc-shared",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tc-shared",
            "status": "completed",
        }
    )

    activities = proj.activities()
    assert len(activities) == 2
    assert {activity.status for activity in activities} == {"running"}


def test_activities_are_isolated_by_session() -> None:
    proj = AgentRuntimeProjection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "s1",
            "toolCallId": "tc-1",
            "toolName": "Bash",
        }
    )
    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "sessionId": "s2",
            "toolCallId": "tc-2",
            "toolName": "Bash",
        }
    )

    assert len(proj.activities_for_session("s1")) == 1
    assert len(proj.activities_for_session("s2")) == 1
    assert len(proj.activities()) == 2


def test_tool_call_without_session_id_is_skipped() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "tc-no-session",
            "toolName": "Bash",
        }
    )

    assert len(proj.activities()) == 0


def test_relative_skill_paths_are_fully_redacted() -> None:
    proj = _projection()

    proj.record_event(
        {
            "sessionUpdate": "agent_message_chunk",
            "sessionId": "sess-1",
            "content": {
                "type": "text",
                "text": (
                    "skill_progress: loading .claude/skills/microrag-search/SKILL.md "
                    "and skills/microrag-search/SKILL.md safely"
                ),
            },
        }
    )

    activities = proj.activities()
    assert len(activities) == 1
    summary = activities[0].summary
    assert summary is not None
    assert ".claude/skills/microrag-search/SKILL.md" not in summary
    assert "skills/microrag-search/SKILL.md" not in summary
    assert ".claude/skills" not in summary
    assert "skills/microrag-search" not in summary
    assert "[redacted]" in summary
