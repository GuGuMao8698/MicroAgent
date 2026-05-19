from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import Chunk
from ragflow_lite.infrastructure.evidence import DeepSeekChatEvidenceExtractor


class _FakeDeepSeekClient:
    def __init__(self, output_text_or_responses: str | list[str]) -> None:
        if isinstance(output_text_or_responses, str):
            self._responses = [output_text_or_responses]
        else:
            self._responses = list(output_text_or_responses)
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return self._next_response()

    def complete_messages_json(self, messages: list[dict[str, str]]) -> str:
        self.calls.append({"messages": messages})
        return self._next_response()

    def _next_response(self) -> str:
        if not self._responses:
            raise RuntimeError("No more fake responses")
        return self._responses.pop(0)


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="chunk_doc_alpha_0",
        document_id="doc_alpha",
        text="MiniRAG links graph entities back to chunks.",
        index=0,
        metadata={},
    )


def test_deepseek_evidence_extractor_normalizes_json_output() -> None:
    client = _FakeDeepSeekClient(
        json.dumps(
            {
                "entities": [
                    {
                        "name": "MiniRAG",
                        "entity_type": "concept",
                        "description": "Lightweight graph retrieval.",
                        "source_chunk_ids": ["chunk_doc_alpha_0"],
                    },
                    {
                        "name": "chunk",
                        "entity_type": "concept",
                        "description": "Text evidence unit.",
                        "source_chunk_ids": ["chunk_doc_alpha_0"],
                    },
                ],
                "relations": [
                    {
                        "source_entity_name": "MiniRAG",
                        "target_entity_name": "chunk",
                        "description": "MiniRAG uses chunks as evidence.",
                        "keywords": ["provenance"],
                        "weight": 1.0,
                        "source_chunk_ids": ["chunk_doc_alpha_0"],
                    }
                ],
            }
        )
    )
    extractor = DeepSeekChatEvidenceExtractor(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    batch = extractor.extract([_chunk()])

    assert batch.document_id == "doc_alpha"
    assert batch.metadata == {
        "extractor": "deepseek_chat",
        "model": "deepseek-v4-flash",
    }
    assert batch.entities[0].entity_id.startswith("entity_")
    assert batch.relations[0].relation_id.startswith("relation_")

    instructions = client.calls[0]["instructions"]
    assert "JSON object" in instructions
    assert '"entities"' in instructions
    assert '"relations"' in instructions
    assert '"source_chunk_ids"' in instructions


def test_deepseek_evidence_extractor_rejects_empty_chunks_without_model_call() -> None:
    client = _FakeDeepSeekClient("{}")
    extractor = DeepSeekChatEvidenceExtractor(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    with pytest.raises(
        ProcessingError, match="Graph evidence extraction requires chunks."
    ):
        extractor.extract([])

    assert client.calls == []


def test_deepseek_evidence_extractor_rejects_unknown_chunk_source() -> None:
    invalid_output = json.dumps(
        {
            "entities": [
                {
                    "name": "MiniRAG",
                    "entity_type": "concept",
                    "description": "Lightweight graph retrieval.",
                    "source_chunk_ids": ["chunk_missing"],
                }
            ],
            "relations": [],
        }
    )
    client = _FakeDeepSeekClient([invalid_output, invalid_output])
    extractor = DeepSeekChatEvidenceExtractor(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    with pytest.raises(ProcessingError, match="unknown source chunk"):
        extractor.extract([_chunk()])

    assert len(client.calls) == 2


def test_deepseek_evidence_extractor_repairs_relation_unknown_entity() -> None:
    invalid = json.dumps(
        {
            "entities": [
                {
                    "name": "MiniRAG",
                    "entity_type": "concept",
                    "description": "Lightweight graph retrieval.",
                    "source_chunk_ids": ["chunk_doc_alpha_0"],
                }
            ],
            "relations": [
                {
                    "source_entity_name": "MiniRAG",
                    "target_entity_name": "Graph evidence",
                    "description": "MiniRAG uses graph evidence.",
                    "keywords": ["graph"],
                    "weight": 1.0,
                    "source_chunk_ids": ["chunk_doc_alpha_0"],
                }
            ],
        }
    )
    repaired = json.dumps(
        {
            "entities": [
                {
                    "name": "MiniRAG",
                    "entity_type": "concept",
                    "description": "Lightweight graph retrieval.",
                    "source_chunk_ids": ["chunk_doc_alpha_0"],
                },
                {
                    "name": "Graph evidence",
                    "entity_type": "concept",
                    "description": "Graph evidence extracted from chunks.",
                    "source_chunk_ids": ["chunk_doc_alpha_0"],
                },
            ],
            "relations": [
                {
                    "source_entity_name": "MiniRAG",
                    "target_entity_name": "Graph evidence",
                    "description": "MiniRAG uses graph evidence.",
                    "keywords": ["graph"],
                    "weight": 1.0,
                    "source_chunk_ids": ["chunk_doc_alpha_0"],
                }
            ],
        }
    )
    client = _FakeDeepSeekClient([invalid, repaired])
    extractor = DeepSeekChatEvidenceExtractor(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    batch = extractor.extract([_chunk()])

    assert [entity.name for entity in batch.entities] == ["MiniRAG", "Graph evidence"]
    assert batch.relations[0].target_entity_name == "Graph evidence"
    assert len(client.calls) == 2
    repair_messages = client.calls[1]["messages"]
    assert repair_messages[2]["content"] == invalid
    assert (
        "Graph relation references an unknown entity." in repair_messages[3]["content"]
    )
