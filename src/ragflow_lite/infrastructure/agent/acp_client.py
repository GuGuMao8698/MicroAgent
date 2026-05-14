from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from subprocess import PIPE
from typing import Any, Mapping, Protocol, TextIO


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


def redact_acp_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """仅向上层暴露可安全返回给 UI 的浅层字段。"""
    return {
        key: value
        for key, value in event.items()
        if key not in BACKEND_ONLY_KEYS
    }


def redact_acp_error(message: str) -> str:
    lowered = message.lower()
    for marker in _SENSITIVE_ERROR_MARKERS:
        if marker.lower() in lowered:
            return "MicroRAG agent runtime failed."
    return message


def _default_process_factory(command: str, args: list[str], cwd: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [command, *args],
        cwd=cwd,
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
        self._next_id = 1

    def start(self) -> None:
        self._process = self._process_factory(
            self._config.command,
            self._config.args,
            self._config.cwd,
        )

    def initialize(self) -> dict[str, Any]:
        return self._request("initialize", {})

    def resume_session(self, claude_session_id: str) -> dict[str, Any]:
        return self._request("session/load", {"sessionId": claude_session_id})

    def send_message(self, claude_session_id: str, message: str) -> dict[str, Any]:
        return self._request(
            "session/prompt",
            {
                "sessionId": claude_session_id,
                "prompt": message,
            },
        )

    def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
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

        line = stdout.readline()
        if line == "":
            raise RuntimeError("ACP client process returned no response.")
        response = json.loads(line)
        error = response.get("error")
        if isinstance(error, Mapping):
            raise RuntimeError(redact_acp_error(str(error.get("message", "ACP request failed."))))

        result = response.get("result", {})
        if not isinstance(result, Mapping):
            raise RuntimeError("ACP response result must be an object.")
        return redact_acp_event(result)

    def _require_process(self) -> _AcpProcess:
        if self._process is None:
            raise RuntimeError("ACP client has not been started.")
        return self._process
