from __future__ import annotations

from ragflow_lite.infrastructure.retrievers import OpenAIResponsesCoTGroundingRewriter


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.outputs.pop(0))


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = _FakeResponses(outputs)


def test_openai_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeClient(['{"original_query":"Q","solution_steps":["Clarify Q."]}'])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    request = client.responses.calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert "solution_steps" in str(request["instructions"])


def test_openai_cot_rewriter_retries_once_then_failed() -> None:
    client = _FakeClient(["not-json", "not-json"])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.failure_reason is not None
    assert len(client.responses.calls) == 2
