from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from subprocess import PIPE
from typing import Any, Protocol, TextIO

from ragflow_lite.infrastructure.agent.activity_projection import (
    AgentActivity,
    AgentCommandSummary,
    AgentRuntimeProjection,
)

BACKEND_ONLY_KEYS = {
    "agentInfo",
    "cwd",
    "runtime_cwd",
    "command",
    "args",
    "transcript_path",
    "_meta",
    "stderr",
}

_SENSITIVE_ERROR_MARKERS = (
    "Claude Code",
    "claude-code",
    "transcript",
    "transcript_path",
    "/tmp/",
    ".jsonl",
    "runtime path",
    "cwd=",
    "cwd:",
    r":\\",
)


class _AcpProcess(Protocol):
    stdin: TextIO | None
    stdout: TextIO | None
    stderr: TextIO | None


@dataclass(frozen=True, slots=True)
class AcpRuntimeConfig:
    command: str
    args: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)


def redact_acp_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """仅向上层暴露可安全返回给 UI 的浅层字段。"""
    return {key: value for key, value in event.items() if key not in BACKEND_ONLY_KEYS}


def redact_acp_error(message: str, *, raw_runtime: bool = False) -> str:
    if raw_runtime:
        return "MicroRAG agent runtime failed."
    lowered = message.lower()
    for marker in _SENSITIVE_ERROR_MARKERS:
        if marker.lower() in lowered:
            return "MicroRAG agent runtime failed."
    return message


def _default_process_factory(
    command: str, args: list[str], cwd: str, env: Mapping[str, str] | None = None
) -> subprocess.Popen[str]:
    child_env = os.environ.copy()
    if env is not None:
        child_env.update(env)
    return subprocess.Popen(
        [command, *args],
        cwd=cwd,
        env=child_env,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
    )


class AcpClient:
    def __init__(
        self,
        *,
        config: AcpRuntimeConfig,
        process_factory: Any = _default_process_factory,
    ) -> None:
        self._config = config
        self._process_factory = process_factory
        self._process: _AcpProcess | None = None
        self._initialized = False
        self._next_id = 1
        self._projection = AgentRuntimeProjection()

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = self._process_factory(
                self._config.command,
                self._config.args,
                self._config.cwd,
                self._config.env,
            )
        except Exception:
            raise RuntimeError(redact_acp_error("", raw_runtime=True)) from None

    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientInfo": {
                    "name": "microrag",
                    "version": "0.1.0",
                },
            },
        )
        self._initialized = True
        return result

    def ensure_ready(self) -> None:
        self.start()
        if not self._initialized:
            self.initialize()

    def new_session(self) -> dict[str, Any]:
        return self._request(
            "session/new",
            {
                "cwd": self._config.cwd,
                "mcpServers": [],
            },
        )

    def resume_session(self, claude_session_id: str) -> dict[str, Any]:
        return self._request(
            "session/load",
            {
                "sessionId": claude_session_id,
                "cwd": self._config.cwd,
                "mcpServers": [],
            },
        )

    def send_message(self, claude_session_id: str, message: str) -> dict[str, Any]:
        return self._request(
            "session/prompt",
            {
                "sessionId": claude_session_id,
                "prompt": [{"type": "text", "text": message}],
            },
            collect_session_id=claude_session_id,
        )

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        collect_session_id: str | None = None,
    ) -> dict[str, Any]:
        process = self._require_process()
        stdin = process.stdin
        stdout = process.stdout
        if stdin is None or stdout is None:
            raise RuntimeError("ACP client process is missing stdio pipes.")

        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        stdin.write(json.dumps(payload) + "\n")
        stdin.flush()

        message_chunks: list[str] = []
        while True:
            line = stdout.readline()
            if line == "":
                raise RuntimeError("ACP client process returned no response.")
            response = json.loads(line)
            if isinstance(response, dict):
                self._record_projection_event(response)
            self._collect_agent_message_chunk(
                response,
                message_chunks,
                collect_session_id=collect_session_id,
            )

            if response.get("id") == request_id:
                break

        error = response.get("error")
        if isinstance(error, Mapping):
            raise RuntimeError(
                redact_acp_error(
                    str(error.get("message", "ACP request failed.")), raw_runtime=True
                )
            )

        result = response.get("result", {})
        if not isinstance(result, Mapping):
            raise RuntimeError("ACP response result must be an object.")
        redacted_result = dict(result)
        if message_chunks and "message" not in redacted_result:
            redacted_result["message"] = "".join(message_chunks)
        return redacted_result

    def _collect_agent_message_chunk(
        self,
        response: Mapping[str, Any],
        message_chunks: list[str],
        *,
        collect_session_id: str | None,
    ) -> None:
        if collect_session_id is None:
            return
        if response.get("method") != "session/update":
            return
        params = response.get("params")
        if not isinstance(params, Mapping):
            return
        if params.get("sessionId") != collect_session_id:
            return
        update = params.get("update")
        if not isinstance(update, Mapping):
            return
        if update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content")
        if not isinstance(content, Mapping):
            return
        if content.get("type") != "text":
            return
        text = content.get("text")
        if isinstance(text, str):
            message_chunks.append(text)

    def _record_projection_event(self, response: dict[str, Any]) -> None:
        if response.get("method") != "session/update":
            return
        params = response.get("params")
        if not isinstance(params, dict):
            return
        update = params.get("update")
        if not isinstance(update, dict):
            return
        session_id = params.get("sessionId")
        if isinstance(session_id, str):
            update["sessionId"] = session_id
        self._projection.record_event(update)

    def command_summaries(self) -> list[AgentCommandSummary]:
        return self._projection.command_summaries()

    def activities_for_session(self, session_id: str) -> list[AgentActivity]:
        return self._projection.activities_for_session(session_id)

    def _require_process(self) -> _AcpProcess:
        if self._process is None:
            raise RuntimeError("ACP client has not been started.")
        return self._process
