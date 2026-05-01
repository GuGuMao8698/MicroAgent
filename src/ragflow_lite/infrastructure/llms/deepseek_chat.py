from __future__ import annotations

import time
from typing import Any

from ragflow_lite.domain.errors import ProcessingError

_DEFAULT_JSON_MAX_TOKENS = 2048
_MAX_DEEPSEEK_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5
_DEEPSEEK_JSON_INSTRUCTION = (
    "Return only one JSON object. Do not include markdown or prose outside the JSON."
)


def _ensure_json_instruction(instructions: str) -> str:
    if "json" in instructions.lower():
        return instructions
    return f"{instructions.rstrip()}\n\n{_DEEPSEEK_JSON_INSTRUCTION}"


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
        return self._complete(
            instructions,
            input_text,
            response_format=None,
            max_tokens=None,
        )

    def complete_json(
        self,
        instructions: str,
        input_text: str,
        *,
        max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    ) -> str:
        return self._complete(
            _ensure_json_instruction(instructions),
            input_text,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )

    def _complete(
        self,
        instructions: str,
        input_text: str,
        response_format: dict[str, str] | None,
        max_tokens: int | None,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if response_format is not None:
            request["response_format"] = response_format
        if max_tokens is not None:
            request["max_tokens"] = max_tokens

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
