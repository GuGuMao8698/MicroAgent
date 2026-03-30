from __future__ import annotations

from dataclasses import dataclass

import pytest

from ragflow_lite.application.services.query_service import QueryService
from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import AnswerResult, RetrievedChunk


def _chunk(text: str = "ctx") -> RetrievedChunk:
    return RetrievedChunk(chunk_id="c1", document_id="d1", text=text, score=0.9)


@dataclass
class FakeRetriever:
    results: list[RetrievedChunk]

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.results


@dataclass
class FakeAnswerer:
    answer_text: str = "回答"

    def answer(self, query: str, contexts: list[RetrievedChunk]) -> AnswerResult:
        return AnswerResult(answer=self.answer_text, contexts=contexts)


def test_query_orchestrates_retrieve_then_answer() -> None:
    chunks = [_chunk("a"), _chunk("b")]
    service = QueryService(
        retriever=FakeRetriever(results=chunks),
        answerer=FakeAnswerer(answer_text="yes"),
    )

    result = service.query("q", top_k=5)

    assert result.answer == "yes"
    assert result.contexts == chunks


def test_query_passes_through_ragflow_lite_error() -> None:
    @dataclass
    class BrokenRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            raise ProcessingError("boom")

    service = QueryService(
        retriever=BrokenRetriever(),
        answerer=FakeAnswerer(),
    )

    with pytest.raises(RagflowLiteError, match="boom"):
        service.query("q", top_k=5)


def test_query_wraps_non_domain_exception() -> None:
    @dataclass
    class BrokenRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            raise RuntimeError("unexpected")

    service = QueryService(
        retriever=BrokenRetriever(),
        answerer=FakeAnswerer(),
    )

    with pytest.raises(ProcessingError, match="Failed to answer query"):
        service.query("q", top_k=5)
