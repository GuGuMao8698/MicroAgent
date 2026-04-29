from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.retrievers import OpenAIResponsesQueryGrounder


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.output_text)


class _FakeClient:
    def __init__(self, output_text: str) -> None:
        self.responses = _FakeResponses(output_text)


def _grounder(output: dict[str, object]) -> OpenAIResponsesQueryGrounder:
    return OpenAIResponsesQueryGrounder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=_FakeClient(json.dumps(output)),
    )


def test_openai_query_grounder_normalizes_json_output() -> None:
    grounder = _grounder(
        {
            "answer_type_keywords": [" concept ", "Concept", "mechanism"],
            "entities_from_query": [" MiniRAG ", "minirag", "chunk recovery"],
        }
    )

    result = grounder.ground("How does MiniRAG recover chunks?")

    assert result.query == "How does MiniRAG recover chunks?"
    assert result.answer_type_keywords == ["concept", "mechanism"]
    assert result.entities_from_query == ["MiniRAG", "chunk recovery"]
    assert result.metadata == {
        "grounder": "openai_responses",
        "model": "test-model",
    }


def test_openai_query_grounder_rejects_empty_query_without_model_call() -> None:
    client = _FakeClient(
        json.dumps({"answer_type_keywords": [], "entities_from_query": []})
    )
    grounder = OpenAIResponsesQueryGrounder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    with pytest.raises(ProcessingError, match="Query grounding requires a query."):
        grounder.ground("   ")

    assert client.responses.calls == []


def test_openai_query_grounder_rejects_invalid_json() -> None:
    grounder = OpenAIResponsesQueryGrounder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=_FakeClient("not-json"),
    )

    with pytest.raises(ProcessingError, match="Query grounder returned invalid JSON."):
        grounder.ground("What is MiniRAG?")
