from __future__ import annotations

from typing import Any

from ragflow_lite.domain.models import AnswerRequest, RetrievedChunk
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.answerers.deepseek_chat import DeepSeekChatAnswerer


class _FakeDeepSeekClient:
    def __init__(self, output_text: str = "回答<cite:1>。") -> None:
        self.output_text = output_text
        self.calls: list[dict[str, Any]] = []

    def complete(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return self.output_text


def _chunk(suffix: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        text=f"片段 {suffix}",
        score=score,
        metadata={"filename": f"{suffix}.md"},
    )


def _request(contexts: list[RetrievedChunk]) -> AnswerRequest:
    return AnswerRequest(query="问题", contexts=contexts)


def test_deepseek_answerer_returns_fallback_without_contexts() -> None:
    client = _FakeDeepSeekClient()
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    result = answerer.answer(_request([]))

    assert result.answer == FALLBACK_ANSWER
    assert result.contexts == []
    assert client.calls == []


def test_deepseek_answerer_cleans_citations_and_records_metadata() -> None:
    client = _FakeDeepSeekClient("项目支持 Markdown<cite:1>。")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    result = answerer.answer(_request([_chunk("a", 0.9)]))

    assert result.answer == "项目支持 Markdown[1]。"
    assert result.metadata["strategy"] == "deepseek_chat"
    assert result.metadata["model"] == "deepseek-v4-flash"
    assert result.metadata["reasoning_effort"] == "high"


def test_deepseek_answerer_orders_contexts_by_score() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)

    result = answerer.answer(_request([low, high]))

    assert result.contexts == [high, low]
    assert client.calls[0]["input_text"].index("chunk-high") < client.calls[0][
        "input_text"
    ].index("chunk-low")
