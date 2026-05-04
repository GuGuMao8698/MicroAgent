from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services import discorag_query_service as discorag_module
from ragflow_lite.application.services.discorag_query_service import (
    DiscoRAGQueryService,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    EvidencePackage,
    GroundedQuery,
    IntraChunkDiscoursePackage,
    RetrievedChunk,
    TopologyRetrievalResult,
)
from ragflow_lite.shared.observability import (
    bind_request_context,
    clear_request_context,
)

QUERY_LOGGER = "ragflow_lite.application.services.discorag_query_service"


def _chunk(chunk_id: str = "chunk_a") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc_alpha",
        text="MiniRAG retrieves evidence.",
        score=0.9,
    )


def _retrieval_result(
    chunks: list[RetrievedChunk] | None = None,
) -> TopologyRetrievalResult:
    return TopologyRetrievalResult(
        query="How does MiniRAG organize evidence?",
        grounded_query=GroundedQuery(
            query="How does MiniRAG organize evidence?",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        chunks=chunks if chunks is not None else [_chunk()],
        paths=[],
    )


@dataclass
class FakeTopologyRetriever:
    result: TopologyRetrievalResult = field(default_factory=_retrieval_result)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult:
        self.calls.append((query, top_k))
        return self.result


@dataclass
class RecordingDiscourseExtractor:
    last_package: EvidencePackage | None = None

    def extract(self, evidence_package: EvidencePackage) -> IntraChunkDiscoursePackage:
        self.last_package = evidence_package
        return IntraChunkDiscoursePackage(
            query=evidence_package.query,
            evidence_package=evidence_package,
            structures=[],
            metadata={"status": "ok"},
        )


@dataclass
class RecordingBlueprintBuilder:
    last_package: IntraChunkDiscoursePackage | None = None
    blueprint: AnswerBlueprint = field(
        default_factory=lambda: AnswerBlueprint(
            ordered_chunk_ids=["chunk_a"],
            chunk_roles={"chunk_a": "context"},
            answer_constraints=["Follow ordered_chunk_ids."],
            plan_steps=["Start from the first ordered chunk."],
            metadata={"status": "ok"},
        )
    )

    def build(self, package: IntraChunkDiscoursePackage) -> AnswerBlueprint:
        self.last_package = package
        return self.blueprint


@dataclass
class FailingBlueprintBuilder:
    error: ProcessingError = field(
        default_factory=lambda: ProcessingError("corrupt discourse plan")
    )

    def build(self, package: IntraChunkDiscoursePackage) -> AnswerBlueprint:
        raise self.error


@dataclass
class RecordingAnswerer:
    last_request: AnswerRequest | None = None
    error: Exception | None = None

    def answer(self, request: AnswerRequest) -> AnswerResult:
        self.last_request = request
        if self.error is not None:
            raise self.error
        return AnswerResult(
            answer="done", contexts=request.contexts, metadata={"ok": True}
        )


def _event_names(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records]


def test_discorag_query_service_orchestrates_blueprint_answering() -> None:
    retriever = FakeTopologyRetriever()
    evidence_package_builder = EvidencePackageBuilder()
    discourse_extractor = RecordingDiscourseExtractor()
    blueprint_builder = RecordingBlueprintBuilder()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=evidence_package_builder,
        discourse_extractor=discourse_extractor,
        blueprint_builder=blueprint_builder,
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=3)

    assert result.answer == "done"
    assert retriever.calls == [("How does MiniRAG organize evidence?", 3)]
    assert discourse_extractor.last_package is not None
    assert discourse_extractor.last_package.items[0].canonical_chunk_id == "chunk_a"
    assert blueprint_builder.last_package is not None
    assert answerer.last_request == AnswerRequest(
        query="How does MiniRAG organize evidence?",
        contexts=retriever.result.chunks,
        mode="discorag",
        blueprint=blueprint_builder.blueprint,
        metadata={"source_selection": None},
    )


def test_discorag_query_service_returns_answerer_result_unchanged() -> None:
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("q", top_k=1)

    assert result.contexts == answerer.last_request.contexts
    assert result.metadata == {"ok": True}


def test_discorag_query_service_logs_started_and_succeeded_and_records_metric(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        service.query("q", top_k=1)

    assert "query_started" in _event_names(caplog)
    assert "query_succeeded" in _event_names(caplog)
    assert outcomes == ["succeeded"]


def test_discorag_query_service_propagates_blueprint_processing_error() -> None:
    answerer = RecordingAnswerer()
    error = ProcessingError("corrupt discourse plan")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=FailingBlueprintBuilder(error=error),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError) as exc_info:
        service.query("q", top_k=1)

    assert exc_info.value is error
    assert answerer.last_request is None


def test_discorag_query_service_logs_failed_and_records_metric_on_domain_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    error = ProcessingError("corrupt discourse plan")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=FailingBlueprintBuilder(error=error),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        with pytest.raises(ProcessingError) as exc_info:
            service.query("q", top_k=1)

    assert exc_info.value is error
    assert "query_started" in _event_names(caplog)
    assert "query_failed" in _event_names(caplog)
    assert outcomes == ["failed"]


def test_discorag_query_service_logs_safe_failure_fields_on_unexpected_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=RecordingAnswerer(error=RuntimeError("unexpected")),
    )
    bind_request_context("trace-query-1")

    try:
        with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
            with pytest.raises(RuntimeError, match="unexpected"):
                service.query("secret query", top_k=5)
    finally:
        clear_request_context()

    failed_record = next(
        record for record in caplog.records if record.event == "query_failed"
    )
    assert failed_record.trace_id == "trace-query-1"
    assert failed_record.request_id
    assert failed_record.outcome == "failed"
    assert failed_record.error_type == "RuntimeError"
    assert "secret query" not in str(failed_record.__dict__)
    assert outcomes == ["failed"]


def test_discorag_query_service_is_exported_from_application_services() -> None:
    from ragflow_lite.application.services import DiscoRAGQueryService as Exported

    assert Exported is DiscoRAGQueryService


def test_discorag_query_service_passes_source_selection_summary_to_answer_request() -> (
    None
):
    retriever = FakeTopologyRetriever(
        result=_retrieval_result(
            chunks=[_chunk()],
        )
    )
    retriever.result.metadata["source_selection"] = {
        "selected_answer_chunk_ids": ["chunk_a"],
        "selected_discourse_chunk_ids": ["chunk_a"],
        "fallback_reason": None,
    }
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=3)

    assert answerer.last_request is not None
    assert answerer.last_request.metadata["source_selection"] == {
        "selected_answer_chunk_ids": ["chunk_a"],
        "selected_discourse_chunk_ids": ["chunk_a"],
        "fallback_reason": None,
    }
