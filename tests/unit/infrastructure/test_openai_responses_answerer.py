from __future__ import annotations

from typing import Any

import pytest

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.answerers.openai_responses import (
    ANSWERER_INSTRUCTIONS,
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


def _make_chunk(suffix: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        text=f"片段 {suffix}",
        score=score,
        metadata={"filename": f"{suffix}.txt", "file_type": "txt"},
    )


# -- instructions 覆盖 --


def test_instructions_require_cite_token() -> None:
    assert "<cite:n>" in ANSWERER_INSTRUCTIONS
    assert "<cite:1>" in ANSWERER_INSTRUCTIONS


def test_instructions_forbid_out_of_range_citation() -> None:
    assert "Only cite numbers that exist" in ANSWERER_INSTRUCTIONS


def test_instructions_forbid_combined_format() -> None:
    assert "<cite:1,2>" in ANSWERER_INSTRUCTIONS


# -- fallback --


def test_answer_returns_fallback_without_calling_openai_when_contexts_are_empty() -> (
    None
):
    client = FakeOpenAIClient()
    answerer = _build_answerer(client)

    result = answerer.answer("没有文档时怎么办", [])

    assert result.answer == FALLBACK_ANSWER
    assert result.contexts == []
    assert result.metadata == {"strategy": "fallback"}
    assert client.responses.calls == []


# -- 排序与返回顺序 --


def test_answer_returns_contexts_sorted_by_score_descending() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    result = answerer.answer("问题", [low, high])

    assert result.contexts == [high, low]


def test_answer_prompt_contexts_are_numbered_by_score_order() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    answerer.answer("问题", [low, high])

    call_input = client.responses.calls[0]["input"]
    assert call_input.index("chunk-high") < call_input.index("chunk-low")


# -- citation 清洗 --


def test_answer_preserves_valid_citations() -> None:
    client = FakeOpenAIClient(output_text="项目支持 txt<cite:1> 和 md<cite:2>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9), _make_chunk("b", 0.5)]

    result = answerer.answer("问题", contexts)

    assert result.answer == "项目支持 txt[1] 和 md[2]。"


def test_answer_strips_out_of_range_citations() -> None:
    client = FakeOpenAIClient(output_text="信息来自 <cite:1> 和 <cite:99>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer("问题", contexts)

    assert result.answer == "信息来自 [1] 和 。"


def test_answer_strips_zero_citation() -> None:
    client = FakeOpenAIClient(output_text="参考 <cite:0> 不合法。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer("问题", contexts)

    assert result.answer == "参考  不合法。"


def test_answer_preserves_bare_bracket_numbers_in_text() -> None:
    """裸方括号数字不是 citation token，原样保留。"""
    client = FakeOpenAIClient(
        output_text="HTTP [404] means not found <cite:1>。Use array[0] as the first slot."
    )
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer("问题", contexts)

    assert (
        result.answer
        == "HTTP [404] means not found [1]。Use array[0] as the first slot."
    )


def test_answer_preserves_non_digit_brackets() -> None:
    client = FakeOpenAIClient(output_text="参见 [abc] 和 <cite:1>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer("问题", contexts)

    assert "[abc]" in result.answer
    assert "[1]" in result.answer


def test_answer_preserves_bare_digit_brackets_as_is() -> None:
    """裸 [1] 或 [99] 不被当作 citation，原样保留。"""
    client = FakeOpenAIClient(output_text="状态码 [404] 和端口 [80] 是常见的。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer("问题", contexts)

    assert result.answer == "状态码 [404] 和端口 [80] 是常见的。"


# -- API 参数 --


def test_answer_calls_responses_api_with_expected_parameters() -> None:
    client = FakeOpenAIClient(output_text=" 支持 txt 和 md。 ")
    answerer = _build_answerer(client)
    contexts = [
        _make_chunk("low", 0.2),
        _make_chunk("high", 0.9),
    ]

    result = answerer.answer("支持什么文件类型", contexts)

    assert result.answer == "支持 txt 和 md。"
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


def test_answer_bubbles_up_openai_errors() -> None:
    answerer = _build_answerer(FakeOpenAIClient(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        answerer.answer(
            "这个请求会失败吗",
            [_make_chunk("1", 0.8)],
        )
