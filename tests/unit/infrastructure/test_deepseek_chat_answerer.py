from __future__ import annotations

from typing import Any, Literal

from ragflow_lite.domain.models import AnswerBlueprint, AnswerRequest, RetrievedChunk
from ragflow_lite.infrastructure.answerers import FALLBACK_ANSWER
from ragflow_lite.infrastructure.answerers.deepseek_chat import DeepSeekChatAnswerer


def test_deepseek_answerer_includes_retrieval_rewrite_notice() -> None:
    client = _FakeDeepSeekClient("Evidence is still limited.")
    answerer = DeepSeekChatAnswerer(client=client, instructions="Answer.")
    request = AnswerRequest(
        query="ambiguous question",
        contexts=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="limited evidence",
                score=1.0,
                metadata={},
            )
        ],
        mode="discorag",
        metadata={
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        },
    )

    answerer.answer(request)

    sent_input = client.calls[0]["input_text"]
    assert (
        "Retrieval rewrite notice:\n"
        "- Retrieval rewrite already ran, but the available evidence still appears insufficient.\n"
        "- Likely causes include missing relevant documents in the knowledge base or a query that is still too ambiguous.\n"
        "- Tell the user that they may need to rephrase the query or add the needed documents.\n"
        "\n"
        "Contexts:"
    ) in sent_input


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


def _request(
    contexts: list[RetrievedChunk],
    *,
    mode: Literal["standard", "discorag"] = "standard",
    blueprint: AnswerBlueprint | None = None,
) -> AnswerRequest:
    return AnswerRequest(
        query="问题",
        contexts=contexts,
        mode=mode,
        blueprint=blueprint,
    )


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


# -- blueprint fallback --


def test_deepseek_answerer_uses_blueprint_chunk_order_for_discorag_mode() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-high"],
        chunk_roles={"chunk-low": "thesis", "chunk-high": "support"},
        answer_constraints=["Do not omit qualifiers."],
        plan_steps=["State the thesis first.", "Then add supporting detail."],
    )

    result = answerer.answer(
        _request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [low, high]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is True


def test_deepseek_answerer_prompt_includes_blueprint_section_when_present() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    contexts = [_chunk("a", 0.9), _chunk("b", 0.4)]
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-b", "chunk-a"],
        chunk_roles={"chunk-b": "thesis", "chunk-a": "qualifier"},
        answer_constraints=["Mention the qualifier."],
        plan_steps=["Open with the thesis.", "Add the qualifier second."],
    )

    answerer.answer(_request(contexts, mode="discorag", blueprint=blueprint))

    call_input = client.calls[0]["input_text"]
    assert "Blueprint:" in call_input
    assert "ordered_chunk_ids: chunk-b, chunk-a" in call_input
    assert "chunk_roles: chunk-b=thesis; chunk-a=qualifier" in call_input
    assert "answer_constraints: Mention the qualifier." in call_input
    assert "plan_steps: Open with the thesis. | Add the qualifier second." in call_input


def test_deepseek_answerer_discorag_without_blueprint_falls_back_to_score_order() -> (
    None
):
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)

    result = answerer.answer(_request([low, high], mode="discorag"))

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "discorag"
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "missing_blueprint"


def test_deepseek_answerer_invalid_blueprint_falls_back_to_score_order() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-missing"],
        chunk_roles={"chunk-missing": "thesis"},
        answer_constraints=["Keep the answer grounded."],
        plan_steps=["Use the missing chunk first."],
    )

    result = answerer.answer(
        _request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"


def test_deepseek_answerer_standard_mode_ignores_blueprint() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-high"],
        chunk_roles={"chunk-low": "thesis", "chunk-high": "support"},
        answer_constraints=["Follow ordered_chunk_ids."],
        plan_steps=["State the thesis first."],
    )

    result = answerer.answer(_request([low, high], blueprint=blueprint))

    assert result.contexts == [high, low]
    assert result.metadata["answer_mode"] == "standard"
    assert result.metadata["blueprint_applied"] is False
    assert "blueprint_fallback_reason" not in result.metadata


def test_deepseek_answerer_partially_invalid_blueprint_falls_back() -> None:
    """Blueprint mixing known and unknown chunk IDs is invalid."""
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low", "chunk-ghost"],
        chunk_roles={"chunk-low": "thesis", "chunk-ghost": "support"},
        answer_constraints=[],
        plan_steps=[],
    )

    result = answerer.answer(
        _request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"


def test_deepseek_answerer_incomplete_blueprint_falls_back() -> None:
    client = _FakeDeepSeekClient("回答")
    answerer = DeepSeekChatAnswerer(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )
    low = _chunk("low", 0.2)
    high = _chunk("high", 0.9)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk-low"],
        chunk_roles={"chunk-low": "thesis"},
        answer_constraints=[],
        plan_steps=[],
    )

    result = answerer.answer(
        _request([low, high], mode="discorag", blueprint=blueprint)
    )

    assert result.contexts == [high, low]
    assert result.metadata["blueprint_applied"] is False
    assert result.metadata["blueprint_fallback_reason"] == "invalid_blueprint"
