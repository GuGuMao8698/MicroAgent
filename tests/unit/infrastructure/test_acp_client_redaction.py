from __future__ import annotations

import io
import json
import traceback

import pytest

from ragflow_lite.infrastructure.agent.acp_client import (
    AcpClient,
    AcpRuntimeConfig,
    redact_acp_error,
    redact_acp_event,
)


class _FakeProcess:
    def __init__(self, *, stdout_lines: list[str], stderr_text: str = "") -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(stdout_lines))
        self.stderr = io.StringIO(stderr_text)


def _build_client(
    *, stdout_lines: list[str], stderr_text: str = ""
) -> tuple[AcpClient, _FakeProcess]:
    process = _FakeProcess(stdout_lines=stdout_lines, stderr_text=stderr_text)
    config = AcpRuntimeConfig(
        command="acp-agent",
        args=["--stdio"],
        cwd="/runtime/cwd",
    )
    client = AcpClient(
        config=config, process_factory=lambda command, args, cwd, env: process
    )
    client.start()
    return client, process


def _read_request(stdin: io.StringIO) -> dict[str, object]:
    stdin.seek(0)
    return json.loads(stdin.readline())


def test_redact_acp_event_removes_backend_only_fields() -> None:
    event = {
        "session_id": "session-1",
        "message": "ok",
        "agentInfo": {"name": "Claude Code"},
        "cwd": "/runtime/cwd",
        "runtime_cwd": "/runtime/cwd",
        "command": "claude-code",
        "args": ["--acp"],
        "transcript_path": "/runtime/session.jsonl",
        "_meta": {"token_usage": 1},
        "stderr": "debug",
    }

    redacted = redact_acp_event(event)

    assert redacted == {
        "session_id": "session-1",
        "message": "ok",
    }


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Claude Code exploded", "MicroRAG agent runtime failed."),
        ("claude-code failed", "MicroRAG agent runtime failed."),
        ("see /tmp/runtime/session.jsonl", "MicroRAG agent runtime failed."),
        ("transcript_path missing", "MicroRAG agent runtime failed."),
        (
            r"windows runtime path C:\agent\session.jsonl",
            "MicroRAG agent runtime failed.",
        ),
        ("plain failure", "plain failure"),
        ("progress 1/2 complete", "progress 1/2 complete"),
        (r"ratio a\b mismatch", r"ratio a\b mismatch"),
    ],
)
def test_redact_acp_error_rewrites_backend_runtime_details(
    message: str,
    expected: str,
) -> None:
    assert redact_acp_error(message) == expected


def test_initialize_writes_json_rpc_and_redacts_result() -> None:
    client, process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "session_id": "session-1",
                        "agentInfo": {"name": "Claude Code"},
                        "transcript_path": "/runtime/session.jsonl",
                    },
                }
            )
            + "\n"
        ]
    )

    result = client.initialize()
    request = _read_request(process.stdin)

    assert request["jsonrpc"] == "2.0"
    assert request["id"] == 1
    assert request["method"] == "initialize"
    assert request["params"]["protocolVersion"] == 1
    assert request["params"]["clientInfo"] == {
        "name": "microrag",
        "version": "0.1.0",
    }
    assert result == {
        "session_id": "session-1",
        "agentInfo": {"name": "Claude Code"},
        "transcript_path": "/runtime/session.jsonl",
    }


def test_ensure_ready_starts_and_initializes_once() -> None:
    process = _FakeProcess(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": 1,
                    },
                }
            )
            + "\n"
        ]
    )
    starts = 0

    def process_factory(command, args, cwd, env):
        nonlocal starts
        starts += 1
        return process

    client = AcpClient(
        config=AcpRuntimeConfig(
            command="acp-agent",
            args=["--stdio"],
            cwd="/runtime/cwd",
        ),
        process_factory=process_factory,
    )

    client.ensure_ready()
    client.ensure_ready()
    request = _read_request(process.stdin)

    assert starts == 1
    assert request["method"] == "initialize"
    assert process.stdin.readline() == ""


def test_resume_session_writes_session_load_and_redacts_result() -> None:
    client, process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "session_id": "session-1",
                        "title": "loaded",
                        "cwd": "/runtime/cwd",
                    },
                }
            )
            + "\n"
        ]
    )

    result = client.resume_session("claude-session-1")
    request = _read_request(process.stdin)

    assert request["method"] == "session/load"
    assert request["params"] == {
        "sessionId": "claude-session-1",
        "cwd": "/runtime/cwd",
        "mcpServers": [],
    }
    assert result == {
        "session_id": "session-1",
        "title": "loaded",
        "cwd": "/runtime/cwd",
    }


def test_new_session_writes_session_new_with_runtime_cwd() -> None:
    client, process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "sessionId": "session-1",
                    },
                }
            )
            + "\n"
        ]
    )

    result = client.new_session()
    request = _read_request(process.stdin)

    assert request["method"] == "session/new"
    assert request["params"] == {
        "cwd": "/runtime/cwd",
        "mcpServers": [],
    }
    assert result == {
        "sessionId": "session-1",
    }


def test_send_message_writes_session_prompt_and_redacts_result() -> None:
    client, process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "message": "done",
                        "_meta": {"usage": 12},
                        "stderr": "trace",
                    },
                }
            )
            + "\n"
        ]
    )

    result = client.send_message("claude-session-1", "hello")
    request = _read_request(process.stdin)

    assert request["method"] == "session/prompt"
    assert request["params"] == {
        "sessionId": "claude-session-1",
        "prompt": [{"type": "text", "text": "hello"}],
    }
    assert result == {
        "message": "done",
        "_meta": {"usage": 12},
        "stderr": "trace",
    }


def test_send_message_collects_agent_message_chunks_before_prompt_response() -> None:
    client, process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "claude-session-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Hello"},
                        },
                    },
                }
            )
            + "\n",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "claude-session-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": " there"},
                        },
                    },
                }
            )
            + "\n",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "stopReason": "end_turn",
                    },
                }
            )
            + "\n",
        ]
    )

    result = client.send_message("claude-session-1", "hello")
    request = _read_request(process.stdin)

    assert request["method"] == "session/prompt"
    assert result == {
        "stopReason": "end_turn",
        "message": "Hello there",
    }


def test_send_message_ignores_agent_chunks_from_other_sessions() -> None:
    client, _process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "other-session",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "wrong"},
                        },
                    },
                }
            )
            + "\n",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "claude-session-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "right"},
                        },
                    },
                }
            )
            + "\n",
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "stopReason": "end_turn",
                    },
                }
            )
            + "\n",
        ]
    )

    result = client.send_message("claude-session-1", "hello")

    assert result["message"] == "right"


def test_start_is_idempotent_after_process_exists() -> None:
    processes = [
        _FakeProcess(stdout_lines=[]),
        _FakeProcess(stdout_lines=[]),
    ]
    calls = 0

    def process_factory(
        command: str,
        args: list[str],
        cwd: str,
        env: dict[str, str],
    ) -> _FakeProcess:
        nonlocal calls
        process = processes[calls]
        calls += 1
        return process

    client = AcpClient(
        config=AcpRuntimeConfig(
            command="agent",
            args=["--acp"],
            cwd="/runtime/workspace",
        ),
        process_factory=process_factory,
    )

    client.start()
    client.start()

    assert calls == 1
    assert client._process is processes[0]


def test_request_raises_redacted_runtime_error() -> None:
    client, _process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "message": "Claude Code failed; transcript_path=/runtime/session.jsonl",
                    },
                }
            )
            + "\n"
        ]
    )

    with pytest.raises(RuntimeError, match="MicroRAG agent runtime failed\\."):
        client.initialize()


def test_request_hides_plain_runtime_error_message() -> None:
    client, _process = _build_client(
        stdout_lines=[
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "message": "plain failure",
                    },
                }
            )
            + "\n"
        ]
    )

    with pytest.raises(
        RuntimeError, match="MicroRAG agent runtime failed\\."
    ) as exc_info:
        client.initialize()

    assert "plain failure" not in str(exc_info.value)


def test_start_hides_process_factory_command_and_cwd_details() -> None:
    config = AcpRuntimeConfig(
        command="missing-acp-agent",
        args=["--stdio"],
        cwd="/definitely/missing/cwd",
    )
    client = AcpClient(
        config=config,
        process_factory=lambda command, args, cwd, env: (_ for _ in ()).throw(
            FileNotFoundError(f"{command} failed in {cwd}")
        ),
    )

    with pytest.raises(
        RuntimeError, match="MicroRAG agent runtime failed\\."
    ) as exc_info:
        client.start()

    message = str(exc_info.value)
    formatted = "".join(
        traceback.format_exception(exc_info.type, exc_info.value, exc_info.tb)
    )

    assert exc_info.value.__cause__ is None
    assert "missing-acp-agent" not in message
    assert "/definitely/missing/cwd" not in message
    assert "missing-acp-agent" not in formatted
    assert "/definitely/missing/cwd" not in formatted


def test_start_passes_configured_child_env() -> None:
    calls: list[tuple[str, list[str], str, dict[str, str]]] = []

    def process_factory(
        command: str,
        args: list[str],
        cwd: str,
        env: dict[str, str],
    ):
        calls.append((command, args, cwd, env))
        raise FileNotFoundError("missing executable")

    client = AcpClient(
        config=AcpRuntimeConfig(
            command="agent",
            args=["--acp"],
            cwd="/runtime/workspace",
            env={"CLAUDE_CONFIG_DIR": "/runtime/config"},
        ),
        process_factory=process_factory,
    )

    with pytest.raises(RuntimeError):
        client.start()

    assert calls == [
        (
            "agent",
            ["--acp"],
            "/runtime/workspace",
            {"CLAUDE_CONFIG_DIR": "/runtime/config"},
        )
    ]


def test_acp_client_records_available_commands_update() -> None:
    import json as _json

    notification = _json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "available_commands_update",
                    "commands": [
                        {
                            "name": "microrag-search",
                            "description": "Search MicroRAG",
                            "input_hint": "question",
                        }
                    ],
                }
            },
        }
    )
    init_response = _json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}}
    )

    client, proc = _build_client(
        stdout_lines=[notification + "\n", init_response + "\n"]
    )
    client.initialize()

    commands = client.command_summaries()
    assert [c.name for c in commands] == ["microrag-search"]
    assert commands[0].description == "Search MicroRAG"


def test_acp_client_records_agent_tool_activity() -> None:
    import json as _json

    tool_call_notification = _json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "claude-s-1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tc-1",
                    "toolName": "Agent",
                },
            },
        }
    )
    tool_call_update_notification = _json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "claude-s-1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tc-1",
                    "status": "completed",
                },
            },
        }
    )
    message_response = _json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "done"}]},
        }
    )

    init_resp = _json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}}
    )

    client, proc = _build_client(
        stdout_lines=[
            init_resp + "\n",
            tool_call_notification + "\n",
            tool_call_update_notification + "\n",
            message_response + "\n",
        ]
    )
    client.initialize()

    client.send_message(claude_session_id="claude-s-1", message="run task")

    activities = client.activities_for_session("claude-s-1")
    assert len(activities) == 1
    assert activities[0].kind == "subagent"
    assert activities[0].status == "completed"
