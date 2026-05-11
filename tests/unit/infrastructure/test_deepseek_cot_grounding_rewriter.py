from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.retrievers import DeepSeekCoTGroundingRewriter


class _FakeDeepSeekClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        output = self.outputs.pop(0)
        if output == "__raise__":
            raise RuntimeError("provider failed")
        return output


def test_deepseek_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeDeepSeekClient(
        ['{"original_query":"Q","solution_steps":["Clarify Q."]}']
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_deepseek_cot_rewriter_retries_once_then_succeeds() -> None:
    client = _FakeDeepSeekClient(
        [
            '{"original_query":"Q","solution_steps":[]}',
            '{"original_query":"Q","solution_steps":["Clarify Q."]}',
        ]
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.attempts == 2
    assert result.solution_steps == ["Clarify Q."]


def test_deepseek_cot_rewriter_returns_failed_after_exhaustion() -> None:
    client = _FakeDeepSeekClient(["not-json", "not-json"])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.strategy == "cot_grounding"
    assert result.solution_steps == []
    assert result.attempts == 2
    assert "invalid JSON" in (result.failure_reason or "")


def test_deepseek_cot_rewriter_rejects_empty_query_without_model_call() -> None:
    client = _FakeDeepSeekClient([])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    with pytest.raises(Exception, match="requires a query"):
        rewriter.rewrite("   ")

    assert client.calls == []
