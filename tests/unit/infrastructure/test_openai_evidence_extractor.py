from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import Chunk
from ragflow_lite.infrastructure.evidence import OpenAIResponsesEvidenceExtractor


class _FakeResponses:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(output_text=self.output_text)


class _FakeClient:
    def __init__(self, output_text: str) -> None:
        self.responses = _FakeResponses(output_text)


def test_openai_evidence_extractor_normalizes_json_output() -> None:
    client = _FakeClient(
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
    extractor = OpenAIResponsesEvidenceExtractor(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )
    chunks = [
        Chunk(
            chunk_id="chunk_doc_alpha_0",
            document_id="doc_alpha",
            text="MiniRAG links graph entities back to chunks.",
            index=0,
            metadata={},
        )
    ]

    batch = extractor.extract(chunks)

    assert batch.document_id == "doc_alpha"
    assert batch.entities[0].entity_id.startswith("entity_")
    assert batch.entities[0].metadata["source_id"] == "chunk_doc_alpha_0"
    assert batch.relations[0].relation_id.startswith("relation_")
    assert batch.relations[0].source_chunk_ids == ["chunk_doc_alpha_0"]
    assert client.responses.requests[0]["reasoning"] == {"effort": "medium"}


def test_openai_evidence_extractor_rejects_empty_chunks_without_model_call() -> None:
    client = _FakeClient("{}")
    extractor = OpenAIResponsesEvidenceExtractor(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    with pytest.raises(
        ProcessingError, match="Graph evidence extraction requires chunks."
    ):
        extractor.extract([])

    assert client.responses.requests == []


def test_openai_evidence_extractor_rejects_unknown_chunk_source() -> None:
    client = _FakeClient(
        json.dumps(
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
    )
    extractor = OpenAIResponsesEvidenceExtractor(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    with pytest.raises(ProcessingError, match="unknown source chunk"):
        extractor.extract(
            [
                Chunk(
                    chunk_id="chunk_doc_alpha_0",
                    document_id="doc_alpha",
                    text="MiniRAG",
                    index=0,
                    metadata={},
                )
            ]
        )
