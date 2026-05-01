from __future__ import annotations

from types import SimpleNamespace

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient


class _FakeCompletions:
    def __init__(
        self,
        content: str | None = "ok",
        *,
        failures: list[Exception] | None = None,
    ) -> None:
        self.content = content
        self.failures = list(failures or [])
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        message = SimpleNamespace(content=self.content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def test_deepseek_chat_sends_high_thinking_request() -> None:
    completions = _FakeCompletions("answer")
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    result = client.complete(
        instructions="System instructions.",
        input_text="User input.",
    )

    assert result == "answer"
    request = completions.requests[0]
    assert request["model"] == "deepseek-v4-flash"
    assert request["reasoning_effort"] == "high"
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["messages"] == [
        {"role": "system", "content": "System instructions."},
        {"role": "user", "content": "User input."},
    ]
    assert "instructions" not in request
    assert "input" not in request
    assert "text" not in request
    assert "store" not in request


def test_deepseek_chat_sends_json_response_format() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    client.complete_json("Return JSON.", "{}")

    assert completions.requests[0]["response_format"] == {"type": "json_object"}


def test_deepseek_chat_json_mode_injects_required_json_instruction() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    client.complete_json("Return a boolean object.", "{}")

    request = completions.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 2048
    system_message = request["messages"][0]["content"]
    assert "json" in system_message.lower()
    assert "Return only one JSON object" in system_message


def test_deepseek_chat_json_mode_preserves_existing_json_example() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    instructions = 'Return exactly one JSON object like {"ok": true}.'

    client.complete_json(instructions, "{}")

    system_message = completions.requests[0]["messages"][0]["content"]
    assert system_message == instructions


def test_deepseek_chat_rejects_missing_content() -> None:
    completions = _FakeCompletions(None)
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    with pytest.raises(ProcessingError, match="DeepSeek returned no content."):
        client.complete("System", "User")


class _RetryableStatusError(Exception):
    status_code = 500


def test_deepseek_chat_retries_transient_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions("answer", failures=[_RetryableStatusError("boom")])
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep", sleeps.append
    )

    result = client.complete("System", "User")

    assert result == "answer"
    assert len(completions.requests) == 2
    assert sleeps == [0.5]


class _NonRetryableStatusError(Exception):
    status_code = 400


def test_deepseek_chat_does_not_retry_non_retryable_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        "answer",
        failures=[_NonRetryableStatusError("bad request")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep", sleeps.append
    )

    with pytest.raises(_NonRetryableStatusError):
        client.complete("System", "User")

    assert len(completions.requests) == 1
    assert sleeps == []
