from __future__ import annotations

from typing import Any

import pytest

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.answerers.openai_responses import (
    OpenAIResponsesAnswerer,
)


class FakeResponsesAPI:
    def __init__(
        self,
        output_text: str = "基于上下文的回答。",
        error: Exception | None = None,
    ) -> None:
        self.output_text = output_text
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return type("FakeResponse", (), {"output_text": self.output_text})()


class FakeOpenAIClient:
    def __init__(
        self,
        output_text: str = "基于上下文的回答。",
        error: Exception | None = None,
    ) -> None:
        self.responses = FakeResponsesAPI(output_text=output_text, error=error)


def _build_answerer(client: FakeOpenAIClient | None = None) -> OpenAIResponsesAnswerer:
    return OpenAIResponsesAnswerer(
        api_key="test-openai-api-key",
        base_url="https://code.rayinai.com/v1",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        store=False,
        verbosity="medium",
        client=client or FakeOpenAIClient(),
    )


def test_answer_returns_fallback_without_calling_openai_when_contexts_are_empty() -> None:
    client = FakeOpenAIClient()
    answerer = _build_answerer(client)

    result = answerer.answer("没有文档时怎么办", [])

    assert result.answer == FALLBACK_ANSWER
    assert result.contexts == []
    assert result.metadata == {"strategy": "fallback"}
    assert client.responses.calls == []


def test_answer_calls_responses_api_with_expected_parameters() -> None:
    client = FakeOpenAIClient(output_text=" 支持 txt 和 md。 ")
    answerer = _build_answerer(client)
    contexts = [
        RetrievedChunk(
            chunk_id="chunk-low",
            document_id="doc-low",
            text="低分片段",
            score=0.2,
            metadata={"filename": "low.txt", "file_type": "txt"},
        ),
        RetrievedChunk(
            chunk_id="chunk-high",
            document_id="doc-high",
            text="高分片段",
            score=0.9,
            metadata={"filename": "high.md", "file_type": "md"},
        ),
    ]

    result = answerer.answer("支持什么文件类型", contexts)

    assert result.answer == "支持 txt 和 md。"
    assert result.contexts == contexts
    assert result.metadata == {
        "strategy": "openai_responses",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "store": False,
    }

    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["store"] is False
    assert call["text"] == {"verbosity": "medium"}
    assert call["instructions"]
    assert "chunk-high" in call["input"]
    assert "high.md" in call["input"]
    assert call["input"].index("chunk-high") < call["input"].index("chunk-low")


def test_answer_bubbles_up_openai_errors() -> None:
    answerer = _build_answerer(FakeOpenAIClient(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        answerer.answer(
            "这个请求会失败吗",
            [
                RetrievedChunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    text="上下文",
                    score=0.8,
                    metadata={"filename": "sample.txt", "file_type": "txt"},
                )
            ],
        )
