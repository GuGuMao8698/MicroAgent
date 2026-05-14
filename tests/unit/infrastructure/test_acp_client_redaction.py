from __future__ import annotations

import io
import json

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


def _build_client(*, stdout_lines: list[str], stderr_text: str = "") -> tuple[AcpClient, _FakeProcess]:
    process = _FakeProcess(stdout_lines=stdout_lines, stderr_text=stderr_text)
    config = AcpRuntimeConfig(
        command="acp-agent",
        args=["--stdio"],
        cwd="/runtime/cwd",
    )
    client = AcpClient(config=config, process_factory=lambda command, args, cwd: process)
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
        (r"windows runtime path C:\agent\session.jsonl", "MicroRAG agent runtime failed."),
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
    assert request["params"] == {}
    assert result == {"session_id": "session-1"}


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
    assert request["params"] == {"sessionId": "claude-session-1"}
    assert result == {
        "session_id": "session-1",
        "title": "loaded",
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
        "prompt": "hello",
    }
    assert result == {"message": "done"}


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

    with pytest.raises(RuntimeError, match="MicroRAG agent runtime failed\\.") as exc_info:
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
        process_factory=lambda command, args, cwd: (_ for _ in ()).throw(
            FileNotFoundError(f"{command} failed in {cwd}")
        ),
    )

    with pytest.raises(RuntimeError, match="MicroRAG agent runtime failed\\.") as exc_info:
        client.start()

    message = str(exc_info.value)
    assert "missing-acp-agent" not in message
    assert "/definitely/missing/cwd" not in message
