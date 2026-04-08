from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from ragflow_lite.application.services.query_service import QueryService
from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import AnswerResult, RetrievedChunk
from ragflow_lite.shared.observability import (
    bind_request_context,
    clear_request_context,
)

QUERY_LOGGER = "ragflow_lite.application.services.query_service"


def _chunk(text: str = "ctx") -> RetrievedChunk:
    return RetrievedChunk(chunk_id="c1", document_id="d1", text=text, score=0.9)


@dataclass
class FakeRetriever:
    results: list[RetrievedChunk] | None = None
    error: Exception | None = None

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if self.error is not None:
            raise self.error
        return self.results or []


@dataclass
class FakeAnswerer:
    answer_text: str = "回答"

    def answer(self, query: str, contexts: list[RetrievedChunk]) -> AnswerResult:
        return AnswerResult(answer=self.answer_text, contexts=contexts)


def _build_service(
    *,
    results: list[RetrievedChunk] | None = None,
    retriever_error: Exception | None = None,
    answer_text: str = "回答",
) -> QueryService:
    return QueryService(
        retriever=FakeRetriever(results=results, error=retriever_error),
        answerer=FakeAnswerer(answer_text=answer_text),
    )


def _event_names(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records]


def test_query_orchestrates_retrieve_then_answer() -> None:
    chunks = [_chunk("a"), _chunk("b")]
    service = _build_service(results=chunks, answer_text="yes")

    result = service.query("q", top_k=5)

    assert result.answer == "yes"
    assert result.contexts == chunks


def test_query_passes_through_ragflow_lite_error() -> None:
    service = _build_service(retriever_error=ProcessingError("boom"))

    with pytest.raises(RagflowLiteError, match="boom"):
        service.query("q", top_k=5)


def test_query_wraps_non_domain_exception() -> None:
    service = _build_service(retriever_error=RuntimeError("unexpected"))

    with pytest.raises(ProcessingError, match="Failed to answer query"):
        service.query("q", top_k=5)


def test_query_logs_started_and_succeeded_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _build_service(results=[_chunk("a")], answer_text="yes")

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        service.query("q", top_k=5)

    assert "query_started" in _event_names(caplog)
    assert "query_succeeded" in _event_names(caplog)


def test_query_logs_failed_on_domain_error(caplog: pytest.LogCaptureFixture) -> None:
    service = _build_service(retriever_error=ProcessingError("boom"))

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        with pytest.raises(ProcessingError):
            service.query("q", top_k=5)

    assert "query_started" in _event_names(caplog)
    assert "query_failed" in _event_names(caplog)


def test_query_logs_failed_on_unexpected_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _build_service(retriever_error=RuntimeError("unexpected"))

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        with pytest.raises(ProcessingError, match="Failed to answer query"):
            service.query("q", top_k=5)

    assert "query_started" in _event_names(caplog)
    assert "query_failed" in _event_names(caplog)


def test_query_logs_trace_id_request_id_and_error_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _build_service(retriever_error=ProcessingError("boom"))
    bind_request_context("trace-query-1")

    try:
        with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
            with pytest.raises(ProcessingError):
                service.query("secret query", top_k=5)
    finally:
        clear_request_context()

    failed_record = next(record for record in caplog.records if record.event == "query_failed")
    assert failed_record.trace_id == "trace-query-1"
    assert failed_record.request_id
    assert failed_record.outcome == "failed"
    assert failed_record.error_type == "ProcessingError"
    assert "secret query" not in str(failed_record.__dict__)
