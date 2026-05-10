from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

from ragflow_lite.domain.models import AnswerBlueprint, AnswerRequest, RetrievedChunk
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.answerers.openai_responses import (
    ANSWERER_INSTRUCTIONS,
    OpenAIResponsesAnswerer,
)


class FakeResponsesAPI:
    def __init__(
        self,
        output_text: str = "基于上下文的回答。",
        errors: list[Exception | None] | None = None,
    ) -> None:
        self.output_text = output_text
        self.errors = list(errors or [])
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.errors:
            current = self.errors.pop(0)
            if current is not None:
                raise current
        return type("FakeResponse", (), {"output_text": self.output_text})()


class FakeOpenAIClient:
    def __init__(
        self,
        output_text: str = "基于上下文的回答。",
        errors: list[Exception | None] | None = None,
    ) -> None:
        self.responses = FakeResponsesAPI(
            output_text=output_text,
            errors=errors,
        )


def _build_answerer(
    client: FakeOpenAIClient | None = None,
    *,
    render_citations: bool = True,
) -> OpenAIResponsesAnswerer:
    return OpenAIResponsesAnswerer(
        api_key="test-openai-api-key",
        base_url="https://code.rayinai.com/v1",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        store=False,
        verbosity="medium",
        render_citations=render_citations,
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


def _make_pdf_chunk(
    suffix: str, score: float, page_start: int, page_end: int
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        text=f"PDF 片段 {suffix}",
        score=score,
        metadata={
            "filename": f"{suffix}.pdf",
            "file_type": "pdf",
            "page_start": page_start,
            "page_end": page_end,
        },
    )


def _make_request(
    contexts: list[RetrievedChunk],
    *,
    query: str = "问题",
    mode: str = "standard",
    blueprint: AnswerBlueprint | None = None,
) -> AnswerRequest:
    return AnswerRequest(
        query=query,
        contexts=contexts,
        mode=mode,
        blueprint=blueprint,
    )


def _make_rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://code.rayinai.com/v1/responses")
    response = httpx.Response(
        429,
        request=request,
        json={
            "error": {
                "message": "Too many pending requests, please retry later",
                "type": "rate_limit_error",
            }
        },
    )
    return openai.RateLimitError(
        "Too many pending requests, please retry later",
        response=response,
        body=response.json(),
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

    result = answerer.answer(_make_request([], query="没有文档时怎么办"))

    assert result.answer == FALLBACK_ANSWER
    assert result.contexts == []
    assert result.metadata == {
        "strategy": "fallback",
        "answer_mode": "standard",
        "blueprint_applied": False,
    }
    assert client.responses.calls == []


# -- 排序与返回顺序 --


def test_answer_returns_contexts_sorted_by_score_descending() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    result = answerer.answer(_make_request([low, high]))

    assert result.contexts == [high, low]


def test_answer_prompt_contexts_are_numbered_by_score_order() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    answerer.answer(_make_request([low, high]))

    call_input = client.responses.calls[0]["input"]
    assert call_input.index("chunk-high") < call_input.index("chunk-low")


# -- citation 清洗 --


def test_answer_preserves_valid_citations() -> None:
    client = FakeOpenAIClient(output_text="项目支持 txt<cite:1> 和 md<cite:2>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9), _make_chunk("b", 0.5)]

    result = answerer.answer(_make_request(contexts))

    assert result.answer == "项目支持 txt[1] 和 md[2]。"


def test_answer_hides_rendered_citations_when_disabled() -> None:
    client = FakeOpenAIClient(output_text="项目支持 txt<cite:1> 和 md<cite:2>。")
    answerer = _build_answerer(client, render_citations=False)
    contexts = [_make_chunk("a", 0.9), _make_chunk("b", 0.5)]

    result = answerer.answer(_make_request(contexts))

    assert result.answer == "项目支持 txt 和 md。"


def test_answer_strips_out_of_range_citations() -> None:
    client = FakeOpenAIClient(output_text="信息来自 <cite:1> 和 <cite:99>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer(_make_request(contexts))

    assert result.answer == "信息来自 [1] 和 。"


def test_answer_strips_zero_citation() -> None:
    client = FakeOpenAIClient(output_text="参考 <cite:0> 不合法。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer(_make_request(contexts))

    assert result.answer == "参考  不合法。"


def test_answer_preserves_bare_bracket_numbers_in_text() -> None:
    """裸方括号数字不是 citation token，原样保留。"""
    client = FakeOpenAIClient(
        output_text="HTTP [404] means not found <cite:1>。Use array[0] as the first slot."
    )
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer(_make_request(contexts))

    assert (
        result.answer
        == "HTTP [404] means not found [1]。Use array[0] as the first slot."
    )


def test_answer_preserves_non_digit_brackets() -> None:
    client = FakeOpenAIClient(output_text="参见 [abc] 和 <cite:1>。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer(_make_request(contexts))

    assert "[abc]" in result.answer
    assert "[1]" in result.answer


def test_answer_preserves_bare_digit_brackets_as_is() -> None:
    """裸 [1] 或 [99] 不被当作 citation，原样保留。"""
    client = FakeOpenAIClient(output_text="状态码 [404] 和端口 [80] 是常见的。")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9)]

    result = answerer.answer(_make_request(contexts))

    assert result.answer == "状态码 [404] 和端口 [80] 是常见的。"


# -- API 参数 --


def test_answer_calls_responses_api_with_expected_parameters() -> None:
    client = FakeOpenAIClient(output_text=" 支持 txt 和 md。 ")
    answerer = _build_answerer(client)
    contexts = [
        _make_chunk("low", 0.2),
        _make_chunk("high", 0.9),
    ]

    result = answerer.answer(_make_request(contexts, query="支持什么文件类型"))

    assert result.answer == "支持 txt 和 md。"
    assert result.metadata == {
        "strategy": "openai_responses",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
        "store": False,
        "answer_mode": "standard",
        "blueprint_applied": False,
    }

    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["store"] is False
    assert call["text"] == {"verbosity": "medium"}
    assert call["instructions"]


def test_answer_omits_text_verbosity_for_ark_responses_api() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = OpenAIResponsesAnswerer(
        api_key="test-openai-api-key",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="ep-20260423004926-v99zw",
        reasoning_effort="medium",
        store=False,
        verbosity="medium",
        client=client,
    )

    answerer.answer(_make_request([_make_chunk("high", 0.9)], query="支持什么文件类型"))

    call = client.responses.calls[0]
    assert call["reasoning"] == {"effort": "medium"}
    assert "text" not in call


def test_answer_uses_custom_instructions_from_path(tmp_path: Path) -> None:
    prompt_path = tmp_path / "optimized_prompt.txt"
    prompt_path.write_text("Custom optimized instructions.", encoding="utf-8")
    client = FakeOpenAIClient(output_text="回答")
    answerer = OpenAIResponsesAnswerer(
        api_key="test-openai-api-key",
        base_url="https://code.rayinai.com/v1",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        store=False,
        verbosity="medium",
        client=client,
        instructions_path=str(prompt_path),
    )

    answerer.answer(_make_request([_make_chunk("high", 0.9)], query="支持什么文件类型"))

    assert client.responses.calls[0]["instructions"] == "Custom optimized instructions."


def test_answer_bubbles_up_openai_errors() -> None:
    answerer = _build_answerer(FakeOpenAIClient(errors=[RuntimeError("boom")]))

    with pytest.raises(RuntimeError, match="boom"):
        answerer.answer(
            _make_request([_make_chunk("1", 0.8)], query="这个请求会失败吗")
        )


def test_answer_retries_rate_limit_error_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.answerers.openai_responses.time.sleep",
        lambda _: None,
    )
    client = FakeOpenAIClient(
        output_text="恢复后的回答",
        errors=[_make_rate_limit_error(), None],
    )
    answerer = _build_answerer(client)

    result = answerer.answer(
        _make_request([_make_chunk("1", 0.8)], query="这个请求会重试吗")
    )

    assert result.answer == "恢复后的回答"
    assert len(client.responses.calls) == 2


def test_answer_raises_after_retry_exhausted(monkeypatch) -> None:
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.answerers.openai_responses.time.sleep",
        lambda _: None,
    )
    client = FakeOpenAIClient(
        errors=[
            _make_rate_limit_error(),
            _make_rate_limit_error(),
            _make_rate_limit_error(),
        ]
    )
    answerer = _build_answerer(client)

    with pytest.raises(openai.RateLimitError, match="Too many pending requests"):
        answerer.answer(
            _make_request([_make_chunk("1", 0.8)], query="这个请求会失败吗")
        )

    assert len(client.responses.calls) == 3


# -- page info in prompt --


def test_build_input_includes_single_page_info() -> None:
    contexts = [_make_pdf_chunk("a", 0.9, 3, 3)]
    result = OpenAIResponsesAnswerer._build_input(_make_request(contexts), contexts)

    assert "page: 3" in result
    assert "pages:" not in result


def test_build_input_includes_page_range_info() -> None:
    contexts = [_make_pdf_chunk("a", 0.9, 2, 5)]
    result = OpenAIResponsesAnswerer._build_input(_make_request(contexts), contexts)

    assert "pages: 2-5" in result


def test_build_input_omits_page_info_when_absent() -> None:
    contexts = [_make_chunk("a", 0.9)]
    result = OpenAIResponsesAnswerer._build_input(_make_request(contexts), contexts)

    assert "page:" not in result
    assert "pages:" not in result


def test_answer_uses_blueprint_chunk_order_for_discorag_mode() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-high"],
        chunk_roles={"chunk-low": "thesis", "chunk-high": "support"},
        answer_constraints=["Do not omit qualifiers."],
        plan_steps=["State the thesis first.", "Then add supporting detail."],
    )

    result = answerer.answer(
        _make_request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [low, high]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is True


def test_answer_prompt_includes_blueprint_section_when_present() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    contexts = [_make_chunk("a", 0.9), _make_chunk("b", 0.4)]
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-b", "chunk-a"],
        chunk_roles={"chunk-b": "thesis", "chunk-a": "qualifier"},
        answer_constraints=["Mention the qualifier."],
        plan_steps=["Open with the thesis.", "Add the qualifier second."],
    )

    answerer.answer(_make_request(contexts, mode="discorag", blueprint=blueprint))

    call_input = client.responses.calls[0]["input"]
    assert "Blueprint:" in call_input
    assert "ordered_chunk_ids: chunk-b, chunk-a" in call_input
    assert "chunk_roles: chunk-b=thesis; chunk-a=qualifier" in call_input
    assert "answer_constraints: Mention the qualifier." in call_input
    assert "plan_steps: Open with the thesis. | Add the qualifier second." in call_input


def test_answer_discorag_mode_without_blueprint_falls_back_to_score_order() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)

    result = answerer.answer(_make_request([low, high], mode="discorag"))

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "missing_blueprint"


def test_answer_invalid_blueprint_falls_back_to_score_order() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-missing"],
        chunk_roles={"chunk-missing": "thesis"},
        answer_constraints=["Keep the answer grounded."],
        plan_steps=["Use the missing chunk first."],
    )

    result = answerer.answer(
        _make_request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"


def test_answer_partially_invalid_blueprint_falls_back() -> None:
    """Blueprint mixing known and unknown chunk IDs is invalid."""
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-ghost"],
        chunk_roles={"chunk-low": "thesis", "chunk-ghost": "support"},
        answer_constraints=[],
        plan_steps=[],
    )

    result = answerer.answer(
        _make_request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"


def test_answer_incomplete_blueprint_falls_back() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low"],
        chunk_roles={"chunk-low": "thesis"},
        answer_constraints=[],
        plan_steps=[],
    )

    result = answerer.answer(
        _make_request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"


def test_answer_standard_mode_ignores_blueprint_and_uses_score_order() -> None:
    client = FakeOpenAIClient(output_text="回答")
    answerer = _build_answerer(client)
    low = _make_chunk("low", 0.2)
    high = _make_chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-high"],
        chunk_roles={"chunk-low": "thesis", "chunk-high": "support"},
        answer_constraints=["Follow ordered_chunk_ids."],
        plan_steps=["State the thesis first."],
    )

    result = answerer.answer(_make_request([low, high], blueprint=blueprint))

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "standard"
    assert result.metadata["blueprint_applied"] is False
    assert "blueprint_fallback_reason" not in result.metadata
