from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.retrievers import DeepSeekChatQueryGrounder


class _FakeDeepSeekClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return self.output_text


def _grounder(output: dict[str, object]) -> DeepSeekChatQueryGrounder:
    return DeepSeekChatQueryGrounder(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeDeepSeekClient(json.dumps(output)),
    )


def test_deepseek_query_grounder_normalizes_json_output() -> None:
    grounder = _grounder(
        {
            "answer_type_keywords": [" concept ", "Concept", "mechanism"],
            "entities_from_query": [" MiniRAG ", "minirag", "chunk recovery"],
        }
    )

    result = grounder.ground("How does MiniRAG recover chunks?")

    assert result.answer_type_keywords == ["concept", "mechanism"]
    assert result.entities_from_query == ["MiniRAG", "chunk recovery"]
    assert result.metadata == {
        "grounder": "deepseek_chat",
        "model": "deepseek-v4-flash",
    }

    instructions = grounder.client.calls[0]["instructions"]
    assert "JSON object" in instructions
    assert "answer_type_keywords" in instructions
    assert "entities_from_query" in instructions
    assert '"answer_type_keywords"' in instructions


def test_deepseek_query_grounder_rejects_empty_query_without_model_call() -> None:
    client = _FakeDeepSeekClient("{}")
    grounder = DeepSeekChatQueryGrounder(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    with pytest.raises(ProcessingError, match="Query grounding requires a query."):
        grounder.ground("   ")

    assert client.calls == []
