from __future__ import annotations

import time
from typing import Any

from ragflow_lite.domain.errors import ProcessingError

_DEFAULT_JSON_MAX_TOKENS = 262144
_MAX_DEEPSEEK_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5
_DEEPSEEK_JSON_INSTRUCTION = (
    "Return only one JSON object. Do not include markdown or prose outside the JSON."
)


def _ensure_json_instruction(instructions: str) -> str:
    if "json" in instructions.lower():
        return instructions
    return f"{instructions.rstrip()}\n\n{_DEEPSEEK_JSON_INSTRUCTION}"


def _ensure_messages_json_instruction(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    result = [dict(m) for m in messages]
    for m in result:
        if m.get("role") == "system":
            m["content"] = _ensure_json_instruction(m.get("content", ""))
            return result
    # No system message present -- prepend the JSON instruction as one.
    return [{"role": "system", "content": _DEEPSEEK_JSON_INSTRUCTION}, *result]


def _validate_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    validated: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ProcessingError(f"Invalid DeepSeek message role: {role!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ProcessingError("DeepSeek message content must be non-empty text.")
        validated.append({"role": role, "content": content})
    return validated


def _should_retry_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code == 429 or status_code >= 500

    name = exc.__class__.__name__.lower()
    return (
        "ratelimit" in name
        or "rate_limit" in name
        or "timeout" in name
        or "connection" in name
    )


class DeepSeekChatCompletionsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = client or self._build_client(api_key, base_url)

    def complete(self, instructions: str, input_text: str) -> str:
        return self.complete_messages(
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ]
        )

    def complete_json(
        self,
        instructions: str,
        input_text: str,
        *,
        max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    ) -> str:
        return self.complete_messages_json(
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            max_tokens=max_tokens,
        )

    def complete_messages(
        self,
        messages: list[dict[str, str]],
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        return self._complete_messages(
            messages,
            response_format=None,
            max_tokens=None,
            timeout_seconds=timeout_seconds,
        )

    def complete_messages_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
        timeout_seconds: float | None = None,
    ) -> str:
        return self._complete_messages(
            _ensure_messages_json_instruction(messages),
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    def _complete_messages(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> str:
        validated = _validate_messages(messages)
        request: dict[str, Any] = {
            "model": self.model,
            "messages": validated,
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if response_format is not None:
            request["response_format"] = response_format
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        # Forward per-call timeout to the SDK; None means SDK default.
        if timeout_seconds is not None:
            request["timeout"] = timeout_seconds

        for attempt in range(_MAX_DEEPSEEK_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(**request)
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise ProcessingError("DeepSeek returned no content.")
                return content.strip()
            except Exception as exc:
                if isinstance(exc, ProcessingError):
                    raise
                if attempt >= _MAX_DEEPSEEK_RETRIES or not _should_retry_error(exc):
                    raise
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)
