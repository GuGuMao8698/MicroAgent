from __future__ import annotations

from types import SimpleNamespace

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerBlueprint, AnswerRequest, RetrievedChunk
from ragflow_lite.infrastructure.answerers.deepseek_chat import DeepSeekChatAnswerer
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


class _FakeAnswerClient:
    def __init__(self, output: str = "回答") -> None:
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def complete(self, instructions: str, input_text: str) -> str:
        self.calls.append((instructions, input_text))
        return self.output


def _make_chunk(suffix: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        text=f"片段 {suffix}",
        score=score,
        metadata={"filename": f"{suffix}.txt", "file_type": "txt"},
    )


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
    assert request["max_tokens"] == 262144
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


def test_deepseek_answerer_uses_blueprint_chunk_order_for_discorag_mode() -> None:
    client = _FakeAnswerClient("回答")
    answerer = DeepSeekChatAnswerer(
        client=client,
        instructions="System instructions.",
    )
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-high"],
        chunk_roles={"chunk-low": "thesis", "chunk-high": "support"},
        answer_constraints=["Do not omit qualifiers."],
        plan_steps=["State the thesis first.", "Then add supporting detail."],
    )

    result = answerer.answer(
        AnswerRequest(
            query="问题",
            contexts=[low, high],
            mode="discorag",
            blueprint=blueprint,
        )
    )

    assert result.contexts == [low, high]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is True

    call_input = client.calls[0][1]
    assert "Blueprint:" in call_input
    assert "ordered_chunk_ids: chunk-low, chunk-high" in call_input
    assert "chunk_roles: chunk-low=thesis; chunk-high=support" in call_input
    assert "answer_constraints: Do not omit qualifiers." in call_input
    assert "plan_steps: State the thesis first. | Then add supporting detail." in (
        call_input
    )


def test_deepseek_answerer_discorag_mode_without_blueprint_marks_fallback() -> None:
    client = _FakeAnswerClient("回答")
    answerer = DeepSeekChatAnswerer(
        client=client,
        instructions="System instructions.",
    )
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    result = answerer.answer(
        AnswerRequest(query="问题", contexts=[low, high], mode="discorag")
    )

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "missing_blueprint"
    assert "Blueprint:" not in client.calls[0][1]


def test_deepseek_answerer_invalid_blueprint_falls_back_to_score_order() -> None:
    client = _FakeAnswerClient("回答")
    answerer = DeepSeekChatAnswerer(
        client=client,
        instructions="System instructions.",
    )
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-missing"],
        chunk_roles={"chunk-missing": "thesis"},
        answer_constraints=["Keep the answer grounded."],
        plan_steps=["Use the missing chunk first."],
    )

    result = answerer.answer(
        AnswerRequest(
            query="问题",
            contexts=[low, high],
            mode="discorag",
            blueprint=blueprint,
        )
    )

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"
