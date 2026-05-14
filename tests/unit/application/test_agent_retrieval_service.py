from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services.agent_retrieval_service import (
    AgentRetrievalResult,
    AgentRetrievalService,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerBlueprint, AnswerRequest, RetrievedChunk


def _chunk(
    chunk_id: str,
    *,
    score: float,
    metadata: dict[str, object] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=f"text-{chunk_id}",
        score=score,
        metadata=dict(metadata or {}),
    )


def _blueprint() -> AnswerBlueprint:
    return AnswerBlueprint(
        ordered_chunk_ids=["c2", "c1", "c3"],
        chunk_roles={"c2": "lead", "c1": "support", "c3": "tail"},
        answer_constraints=["只基于证据"],
        plan_steps=["先看 lead", "再补 support"],
        metadata={"debug": "hidden"},
    )


@dataclass
class FakeBuilder:
    request: AnswerRequest
    calls: list[tuple[str, int]] = field(default_factory=list)

    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        self.calls.append((query, top_k))
        return self.request


def test_retrieve_standard_returns_clean_payload() -> None:
    request = AnswerRequest(
        query="MiniRAG 是什么？",
        contexts=[
            _chunk("c2", score=0.8, metadata={"rank": 2}),
            _chunk("c4", score=0.6, metadata={"rank": 4}),
            _chunk("c1", score=0.9, metadata={"rank": 1}),
            _chunk("c3", score=0.7, metadata={"rank": 3}),
        ],
        metadata={
            "retrieval_rewrite": {
                "enabled": True,
                "status": "degraded",
            }
        },
    )
    standard_builder = FakeBuilder(request=request)
    discorag_builder = FakeBuilder(
        request=AnswerRequest(query="unused", contexts=[]),
    )
    service = AgentRetrievalService(standard_builder, discorag_builder)

    result = service.retrieve("MiniRAG 是什么？", top_k=4)

    assert result == AgentRetrievalResult(
        payload={
            "query": "MiniRAG 是什么？",
            "contexts": [
                {
                    "chunk_id": "c1",
                    "document_id": "doc-c1",
                    "text": "text-c1",
                    "score": 0.9,
                    "metadata": {"rank": 1},
                },
                {
                    "chunk_id": "c3",
                    "document_id": "doc-c3",
                    "text": "text-c3",
                    "score": 0.7,
                    "metadata": {"rank": 3},
                },
                {
                    "chunk_id": "c4",
                    "document_id": "doc-c4",
                    "text": "text-c4",
                    "score": 0.6,
                    "metadata": {"rank": 4},
                },
                {
                    "chunk_id": "c2",
                    "document_id": "doc-c2",
                    "text": "text-c2",
                    "score": 0.8,
                    "metadata": {"rank": 2},
                },
            ],
        },
        runtime_metadata={
            "retrieval_rewrite": {
                "enabled": True,
                "status": "degraded",
            }
        },
    )
    assert list(result.payload.keys()) == ["query", "contexts"]
    assert "mode" not in result.payload
    assert "metadata" not in result.payload
    assert "retrieval_rewrite" not in result.payload
    assert standard_builder.calls == [("MiniRAG 是什么？", 4)]
    assert discorag_builder.calls == []


def test_retrieve_discorag_returns_contexts_then_blueprint() -> None:
    request = AnswerRequest(
        query="DiscoRAG 如何组织证据？",
        contexts=[
            _chunk("c2", score=0.7, metadata={"kind": "support"}),
            _chunk("c3", score=0.2, metadata={"kind": "tail"}),
            _chunk("c1", score=0.9, metadata={"kind": "lead"}),
        ],
        mode="discorag",
        blueprint=_blueprint(),
        metadata={
            "source_selection": {"selected": ["c1", "c2"]},
            "retrieval_rewrite": {"enabled": False},
        },
    )
    standard_builder = FakeBuilder(
        request=AnswerRequest(query="unused", contexts=[]),
    )
    discorag_builder = FakeBuilder(request=request)
    service = AgentRetrievalService(standard_builder, discorag_builder)

    result = service.retrieve(
        "DiscoRAG 如何组织证据？",
        top_k=3,
        mode="discorag",
    )

    assert list(result.payload.keys()) == ["query", "contexts", "blueprint"]
    assert [item["chunk_id"] for item in result.payload["contexts"]] == [
        "c1",
        "c2",
        "c3",
    ]
    assert list(result.payload["blueprint"].keys()) == [
        "chunk_roles",
        "answer_constraints",
        "plan_steps",
        "ordered_chunk_ids",
    ]
    assert result.payload["blueprint"]["ordered_chunk_ids"] == ["c2", "c1", "c3"]
    assert "source_selection" not in result.payload
    assert "retrieval_rewrite" not in result.payload
    assert result.runtime_metadata == {
        "source_selection": {"selected": ["c1", "c2"]},
        "retrieval_rewrite": {"enabled": False},
    }
    assert standard_builder.calls == []
    assert discorag_builder.calls == [("DiscoRAG 如何组织证据？", 3)]


def test_retrieve_discorag_requires_blueprint() -> None:
    service = AgentRetrievalService(
        FakeBuilder(request=AnswerRequest(query="unused", contexts=[])),
        FakeBuilder(
            request=AnswerRequest(
                query="q",
                contexts=[_chunk("c1", score=0.9)],
                mode="discorag",
                blueprint=None,
            )
        ),
    )

    with pytest.raises(
        ProcessingError,
        match="DiscoRAG retrieval requires a blueprint",
    ):
        service.retrieve("q", top_k=1, mode="discorag")


def test_retrieve_rejects_unknown_mode() -> None:
    service = AgentRetrievalService(
        FakeBuilder(request=AnswerRequest(query="unused", contexts=[])),
        FakeBuilder(request=AnswerRequest(query="unused", contexts=[])),
    )

    with pytest.raises(ProcessingError, match="Unknown retrieval mode"):
        service.retrieve("q", top_k=1, mode="unknown")  # type: ignore[arg-type]
