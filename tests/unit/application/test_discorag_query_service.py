from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services import discorag_query_service as discorag_module
from ragflow_lite.application.services.discorag_answer_blueprint_builder import (
    DiscoRAGAnswerBlueprintBuilder,
)
from ragflow_lite.application.services.discorag_query_service import (
    DiscoRAGQueryService,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.application.services.mini_graph_first_retriever import (
    MiniGraphFirstRetriever,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    EvidencePackage,
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    InterChunkDiscourseGraph,
    IntraChunkDiscoursePackage,
    RetrievedChunk,
    TopologyPath,
    TopologyRetrievalResult,
)
from ragflow_lite.infrastructure.evidence.structurer_retry import (  # noqa: F401
    StructurerAttemptsExhaustedError,
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
    selected_chunk_ids: list[str] = field(default_factory=list)

    def extract(self, evidence_package: EvidencePackage) -> IntraChunkDiscoursePackage:
        self.last_package = evidence_package
        self.selected_chunk_ids = [
            item.canonical_chunk_id
            for item in evidence_package.items
            if item.metadata.get("selected_for_discourse") is True
        ]
        return IntraChunkDiscoursePackage(
            query=evidence_package.query,
            evidence_package=evidence_package,
            structures=[],
            metadata={"status": "ok"},
        )


@dataclass
class RecordingGraphBuilder:
    last_package: IntraChunkDiscoursePackage | None = None
    graph: InterChunkDiscourseGraph = field(
        default_factory=lambda: InterChunkDiscourseGraph(
            query="How does MiniRAG organize evidence?",
            chunk_ids=["chunk_a"],
            relations=[],
            metadata={"builder": "fake"},
        )
    )

    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        self.last_package = package
        return self.graph


@dataclass
class RecordingBlueprintBuilder:
    last_package: IntraChunkDiscoursePackage | None = None
    last_graph: InterChunkDiscourseGraph | None = None
    blueprint: AnswerBlueprint | None = None

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
        self.last_package = package
        self.last_graph = graph
        if self.blueprint is not None:
            return self.blueprint
        ordered_chunk_ids = [
            item.canonical_chunk_id
            for item in package.evidence_package.items
            if item.metadata.get("selected_for_answer") is True
        ]
        if not ordered_chunk_ids:
            ordered_chunk_ids = [
                item.canonical_chunk_id for item in package.evidence_package.items
            ]
        return AnswerBlueprint(
            ordered_chunk_ids=ordered_chunk_ids,
            chunk_roles={chunk_id: "context" for chunk_id in ordered_chunk_ids},
            answer_constraints=["Follow ordered_chunk_ids."],
            plan_steps=["Start from the first ordered chunk."],
            metadata={"status": "ok"},
        )


@dataclass
class FailingBlueprintBuilder:
    error: ProcessingError = field(
        default_factory=lambda: ProcessingError("corrupt discourse plan")
    )

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
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


@dataclass
class _ExhaustedBlueprintBuilder:
    """Simulates a blueprint builder that exhausted retry attempts."""

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
        raise StructurerAttemptsExhaustedError(
            stage="blueprint",
            failure_type="validation_error",
            attempts=2,
            max_attempts=2,
            message="chunk_roles keys must exactly match final_answer_chunk_ids.",
        )


@dataclass
class _ExhaustedDiscourseExtractor:
    """Simulates a discourse extractor that exhausted retry attempts."""

    def extract(self, evidence_package: EvidencePackage) -> IntraChunkDiscoursePackage:
        raise StructurerAttemptsExhaustedError(
            stage="rst_extraction",
            failure_type="validation_error",
            attempts=2,
            max_attempts=2,
            message="unknown canonical_chunk_id 'missing'.",
        )


@dataclass
class _ExhaustedGraphBuilder:
    """Simulates a graph builder that exhausted retry attempts."""

    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        raise StructurerAttemptsExhaustedError(
            stage="inter_chunk_graph",
            failure_type="validation_error",
            attempts=2,
            max_attempts=2,
            message="target_chunk_id 'missing' is unknown.",
        )


class _ServiceGrounder:
    def ground(self, query: str) -> GroundedQuery:
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        )


class _ServiceEntityIndex:
    def query_entities(self, entity_texts: list[str], top_k: int) -> list[object]:
        return []


class _ServiceRelationshipIndex:
    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[object]:
        return []


class _ServicePathExpander:
    def expand_paths(
        self,
        seed_entity_ids: list[str],
        seed_relation_ids: list[str],
        max_hops: int,
    ) -> list[TopologyPath]:
        return [
            TopologyPath(
                path_id=f"path_{index}",
                document_id="doc_alpha",
                entity_ids=[f"entity_{index}"],
                relation_ids=[f"relation_{index}"],
                source_chunk_ids=[f"chunk_{index}"],
                score=1.0,
                candidate_group_id=f"entity_{index}",
                candidate_rank=1,
                metadata={"answer_type_hit_count": 11 - index},
            )
            for index in range(12)
        ]


class _ServiceChunkLookup:
    def get_chunks(self, chunk_ids: list[str]) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id="doc_alpha",
                text=f"Evidence for {chunk_id}",
                score=0.0,
            )
            for chunk_id in chunk_ids
        ]


def _event_names(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.event for record in caplog.records]


def test_discorag_query_service_orchestrates_blueprint_answering() -> None:
    retriever = FakeTopologyRetriever()
    evidence_package_builder = EvidencePackageBuilder()
    discourse_extractor = RecordingDiscourseExtractor()
    graph_builder = RecordingGraphBuilder()
    blueprint_builder = RecordingBlueprintBuilder()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=evidence_package_builder,
        discourse_extractor=discourse_extractor,
        inter_chunk_graph_builder=graph_builder,
        blueprint_builder=blueprint_builder,
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=3)

    assert result.answer == "done"
    assert retriever.calls == [("How does MiniRAG organize evidence?", 3)]
    assert discourse_extractor.last_package is not None
    assert discourse_extractor.last_package.items[0].canonical_chunk_id == "chunk_a"
    assert graph_builder.last_package is blueprint_builder.last_package
    assert blueprint_builder.last_graph is graph_builder.graph
    assert blueprint_builder.last_package is not None
    assert answerer.last_request is not None
    assert answerer.last_request.query == "How does MiniRAG organize evidence?"
    assert answerer.last_request.contexts == retriever.result.chunks
    assert answerer.last_request.mode == "discorag"
    assert answerer.last_request.metadata == {"source_selection": None}
    assert answerer.last_request.blueprint == AnswerBlueprint(
        ordered_chunk_ids=["chunk_a"],
        chunk_roles={"chunk_a": "context"},
        answer_constraints=["Follow ordered_chunk_ids."],
        plan_steps=["Start from the first ordered chunk."],
        metadata={"status": "ok", "answer_context_chunk_ids": ["chunk_a"]},
    )


def test_discorag_build_answer_request_returns_discorag_request_without_calling_answerer() -> (
    None
):
    retriever = FakeTopologyRetriever()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    request = service.build_answer_request(
        "How does MiniRAG organize evidence?",
        top_k=3,
    )

    assert retriever.calls == [("How does MiniRAG organize evidence?", 3)]
    assert request == AnswerRequest(
        query="How does MiniRAG organize evidence?",
        contexts=retriever.result.chunks,
        mode="discorag",
        blueprint=AnswerBlueprint(
            ordered_chunk_ids=["chunk_a"],
            chunk_roles={"chunk_a": "context"},
            answer_constraints=["Follow ordered_chunk_ids."],
            plan_steps=["Start from the first ordered chunk."],
            metadata={"status": "ok", "answer_context_chunk_ids": ["chunk_a"]},
        ),
        metadata={"source_selection": None},
    )
    assert answerer.last_request is None


def test_discorag_query_service_returns_answerer_result_unchanged() -> None:
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
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
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        service.query("q", top_k=1)

    assert "query_started" in _event_names(caplog)
    assert "query_succeeded" in _event_names(caplog)
    assert outcomes == ["succeeded"]


def test_discorag_query_service_propagates_blueprint_processing_error() -> None:
    """Plain ProcessingError from blueprint builder propagates as hard failure.

    Only StructurerAttemptsExhaustedError triggers MiniRAG fallback. Plain
    ProcessingError (from validation bugs, promotion errors, etc.) must
    propagate to the outer RagflowLiteError handler.
    """
    answerer = RecordingAnswerer()
    error = ProcessingError("corrupt discourse plan")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=FailingBlueprintBuilder(error=error),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError, match="corrupt discourse plan"):
        service.query("q", top_k=1)

    assert answerer.last_request is None


def test_discorag_query_service_logs_failed_and_records_metric_on_domain_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    error = ProcessingError("answerer failed")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=RecordingAnswerer(error=error),
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
        inter_chunk_graph_builder=RecordingGraphBuilder(),
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


def test_discorag_query_service_replaces_answer_contexts_with_promoted_within_budget() -> (
    None
):
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a", "chunk_supplemental"],
        chunk_roles={"chunk_a": "main", "chunk_supplemental": "context"},
        answer_constraints=["Respect contradiction."],
        plan_steps=["Use the supplemental qualifier."],
        metadata={
            "promoted_chunk_ids": ["chunk_supplemental"],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces weaker evidence",
                }
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    context_ids = [chunk.chunk_id for chunk in answerer.last_request.contexts]
    assert len(context_ids) == 2  # bounded: 不超过原 answer context 数
    assert "chunk_supplemental" in context_ids  # promoted 换入
    assert "chunk_a" in context_ids  # 保留的原 answer chunk
    assert "chunk_b" not in context_ids  # 被替换的原 answer chunk


def test_discorag_query_service_blueprint_preserves_promoted_context_order() -> None:
    """Calibration example: A promoted to replace B, planner orders [A, SUPP].

    Original answer contexts: [A, B]
    Planner final_answer_chunk_ids: [A, SUPP]
    Promotion: replace B with SUPP

    Runtime final contexts: [A, SUPP]  (B replaced in-place)
    Answer-facing blueprint ordered_chunk_ids: [A, SUPP]  (planner order)
    """
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a", "chunk_supplemental"],
        chunk_roles={
            "chunk_a": "main",
            "chunk_supplemental": "context",
            "chunk_b": "detail",
        },
        answer_constraints=["Respect qualification."],
        plan_steps=["Use the supplemental qualifier."],
        metadata={
            "promoted_chunk_ids": ["chunk_supplemental"],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces weaker evidence",
                }
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    # In-place replacement: chunk_b -> chunk_supplemental preserves [A, SUPP]
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_supplemental",
    ]
    assert answerer.last_request.blueprint is not None
    # Planner order [A, SUPP] preserved in blueprint
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_a",
        "chunk_supplemental",
    ]
    # Replaced chunk absent from contexts
    assert "chunk_b" not in [c.chunk_id for c in answerer.last_request.contexts]


def test_discorag_query_service_keeps_supplemental_discourse_out_of_answer_contexts() -> (
    None
):
    answer_chunks = [
        _chunk("chunk_0"),
        _chunk("chunk_1"),
        _chunk("chunk_2"),
        _chunk("chunk_3"),
        _chunk("chunk_4"),
        _chunk("chunk_5"),
    ]
    supplemental_chunks = {
        f"chunk_{index}": RetrievedChunk(
            chunk_id=f"chunk_{index}",
            document_id="doc_alpha",
            text=f"Supplemental evidence {index}",
            score=0.1,
            metadata={
                "selected_for_answer": False,
                "selected_for_discourse": True,
                "supplemental_discourse": True,
            },
        )
        for index in range(6, 12)
    }
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = supplemental_chunks
    retrieval_result.metadata["source_selection"] = {
        "selected_answer_chunk_ids": [chunk.chunk_id for chunk in answer_chunks],
        "selected_discourse_chunk_ids": [
            *(chunk.chunk_id for chunk in answer_chunks),
            *supplemental_chunks,
        ],
        "supplemental_discourse_chunk_ids": list(supplemental_chunks),
    }
    retrieval_result.source_selection = GraphFirstSourceSelection(
        sources=[
            GraphFirstSource(
                chunk_id=f"chunk_{index}",
                rank=index,
                score=float(12 - index),
                score_components={"score": float(12 - index)},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=index < 6,
                selected_for_discourse=True,
                selection_reason="graph_path_support",
                metadata={"supplemental_discourse": index >= 6},
            )
            for index in range(12)
        ],
        final_context_k=6,
        discourse_selection_k=12,
        context_token_budget=None,
        omitted_source_count=6,
        fallback_reason=None,
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=6)

    assert answerer.last_request is not None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]


def test_discorag_query_service_passes_blueprint_limited_to_final_contexts() -> None:
    answer_chunks = [
        _chunk("chunk_0"),
        _chunk("chunk_1"),
        _chunk("chunk_2"),
        _chunk("chunk_3"),
        _chunk("chunk_4"),
        _chunk("chunk_5"),
    ]
    supplemental_chunks = {
        f"chunk_{index}": RetrievedChunk(
            chunk_id=f"chunk_{index}",
            document_id="doc_alpha",
            text=f"Supplemental evidence {index}",
            score=0.1,
            metadata={
                "selected_for_answer": False,
                "selected_for_discourse": True,
                "supplemental_discourse": True,
            },
        )
        for index in range(6, 12)
    }
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = supplemental_chunks
    retrieval_result.metadata["source_selection"] = {
        "selected_answer_chunk_ids": [chunk.chunk_id for chunk in answer_chunks],
        "selected_discourse_chunk_ids": [
            *(chunk.chunk_id for chunk in answer_chunks),
            *supplemental_chunks,
        ],
        "supplemental_discourse_chunk_ids": list(supplemental_chunks),
    }
    retrieval_result.source_selection = GraphFirstSourceSelection(
        sources=[
            GraphFirstSource(
                chunk_id=f"chunk_{index}",
                rank=index,
                score=float(12 - index),
                score_components={"score": float(12 - index)},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=index < 6,
                selected_for_discourse=True,
                selection_reason="graph_path_support",
                metadata={"supplemental_discourse": index >= 6},
            )
            for index in range(12)
        ],
        final_context_k=6,
        discourse_selection_k=12,
        context_token_budget=None,
        omitted_source_count=6,
        fallback_reason=None,
    )
    discourse_extractor = RecordingDiscourseExtractor()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=discourse_extractor,
        inter_chunk_graph_builder=RecordingGraphBuilder(
            graph=InterChunkDiscourseGraph(
                query="How does MiniRAG organize evidence?",
                chunk_ids=[
                    *(chunk.chunk_id for chunk in answer_chunks),
                    *supplemental_chunks,
                ],
                relations=[],
            )
        ),
        blueprint_builder=DiscoRAGAnswerBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=6)

    assert discourse_extractor.last_package is not None
    assert [
        item.canonical_chunk_id for item in discourse_extractor.last_package.items
    ] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
        "chunk_6",
        "chunk_7",
        "chunk_8",
        "chunk_9",
        "chunk_10",
        "chunk_11",
    ]
    assert answerer.last_request is not None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]
    assert set(answerer.last_request.blueprint.chunk_roles) == {
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    }


def test_discorag_query_service_uses_real_retriever_supplemental_handoff() -> None:
    retriever = MiniGraphFirstRetriever(
        query_grounder=_ServiceGrounder(),
        entity_index=_ServiceEntityIndex(),
        relationship_index=_ServiceRelationshipIndex(),
        path_expander=_ServicePathExpander(),
        chunk_lookup=_ServiceChunkLookup(),
    )
    discourse_extractor = RecordingDiscourseExtractor()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=discourse_extractor,
        inter_chunk_graph_builder=RecordingGraphBuilder(
            graph=InterChunkDiscourseGraph(
                query="How does MiniRAG organize evidence?",
                chunk_ids=[f"chunk_{index}" for index in range(12)],
                relations=[],
            )
        ),
        blueprint_builder=DiscoRAGAnswerBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=6)

    assert discourse_extractor.last_package is not None
    assert [
        item.canonical_chunk_id for item in discourse_extractor.last_package.items
    ] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
        "chunk_6",
        "chunk_7",
        "chunk_8",
        "chunk_9",
        "chunk_10",
        "chunk_11",
    ]
    assert answerer.last_request is not None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]
    assert answerer.last_request.blueprint.metadata["selected_discourse_chunk_ids"] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]
    assert answerer.last_request.metadata["source_selection"][
        "selected_discourse_chunk_ids"
    ] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
        "chunk_6",
        "chunk_7",
        "chunk_8",
        "chunk_9",
        "chunk_10",
        "chunk_11",
    ]
    assert answerer.last_request.blueprint.metadata["answer_context_chunk_ids"] == [
        "chunk_0",
        "chunk_1",
        "chunk_2",
        "chunk_3",
        "chunk_4",
        "chunk_5",
    ]


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
        inter_chunk_graph_builder=RecordingGraphBuilder(),
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


def test_discorag_query_service_does_not_promote_without_promoted_ids() -> None:
    answer_chunks = [_chunk("chunk_a"), _chunk("chunk_b")]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supporting supplemental evidence",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a", "chunk_supplemental", "chunk_b"],
        chunk_roles={
            "chunk_a": "main",
            "chunk_supplemental": "context",
            "chunk_b": "detail",
        },
        answer_constraints=[],
        plan_steps=[],
        metadata={"promoted_chunk_ids": []},
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_b",
    ]
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_a",
        "chunk_b",
    ]


def test_discorag_query_service_filters_blueprint_metadata_to_final_contexts() -> None:
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunks = {
        "chunk_supplemental_1": RetrievedChunk(
            chunk_id="chunk_supplemental_1",
            document_id="doc_alpha",
            text="First supplemental qualifier",
            score=0.4,
            metadata={
                "selected_for_answer": False,
                "selected_for_discourse": True,
                "supplemental_discourse": True,
            },
        ),
        "chunk_supplemental_2": RetrievedChunk(
            chunk_id="chunk_supplemental_2",
            document_id="doc_alpha",
            text="Second supplemental qualifier",
            score=0.3,
            metadata={
                "selected_for_answer": False,
                "selected_for_discourse": True,
                "supplemental_discourse": True,
            },
        ),
    }
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = supplemental_chunks
    retrieval_result.metadata["source_selection"] = {
        "selected_answer_chunk_ids": ["chunk_a", "chunk_b"],
        "selected_discourse_chunk_ids": [
            "chunk_a",
            "chunk_b",
            "chunk_supplemental_1",
            "chunk_supplemental_2",
        ],
        "supplemental_discourse_chunk_ids": [
            "chunk_supplemental_1",
            "chunk_supplemental_2",
        ],
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=[
            "chunk_supplemental_1",
            "chunk_supplemental_2",
            "chunk_a",
            "chunk_b",
        ],
        chunk_roles={
            "chunk_supplemental_1": "context",
            "chunk_supplemental_2": "context",
            "chunk_a": "main",
            "chunk_b": "detail",
        },
        answer_constraints=["Respect qualification."],
        plan_steps=["Use promoted discourse evidence."],
        metadata={
            "selected_answer_chunk_ids": ["chunk_a", "chunk_b"],
            "selected_discourse_chunk_ids": [
                "chunk_a",
                "chunk_b",
                "chunk_supplemental_1",
                "chunk_supplemental_2",
            ],
            "supplemental_discourse_chunk_ids": [
                "chunk_supplemental_1",
                "chunk_supplemental_2",
            ],
            "promoted_chunk_ids": [
                "chunk_supplemental_1",
                "chunk_supplemental_2",
            ],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_a",
                    "with_chunk_id": "chunk_supplemental_1",
                    "reason": "supplemental_1 replaces chunk_a",
                },
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental_2",
                    "reason": "supplemental_2 replaces chunk_b",
                },
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_supplemental_1",
        "chunk_supplemental_2",
    ]
    assert answerer.last_request.blueprint is not None
    metadata = answerer.last_request.blueprint.metadata
    assert metadata["selected_answer_chunk_ids"] == []
    assert metadata["selected_discourse_chunk_ids"] == [
        "chunk_supplemental_1",
        "chunk_supplemental_2",
    ]
    assert metadata["supplemental_discourse_chunk_ids"] == [
        "chunk_supplemental_1",
        "chunk_supplemental_2",
    ]
    assert metadata["promoted_chunk_ids"] == [
        "chunk_supplemental_1",
        "chunk_supplemental_2",
    ]
    assert "promotions" not in metadata
    assert metadata["planner_raw_promotions"] == [
        {
            "replace_chunk_id": "chunk_a",
            "with_chunk_id": "chunk_supplemental_1",
            "reason": "supplemental_1 replaces chunk_a",
        },
        {
            "replace_chunk_id": "chunk_b",
            "with_chunk_id": "chunk_supplemental_2",
            "reason": "supplemental_2 replaces chunk_b",
        },
    ]
    assert metadata["applied_promotions"] == [
        {
            "replace_chunk_id": "chunk_a",
            "with_chunk_id": "chunk_supplemental_1",
            "reason": "supplemental_1 replaces chunk_a",
        },
        {
            "replace_chunk_id": "chunk_b",
            "with_chunk_id": "chunk_supplemental_2",
            "reason": "supplemental_2 replaces chunk_b",
        },
    ]
    assert metadata["answer_context_chunk_ids"] == [
        "chunk_supplemental_1",
        "chunk_supplemental_2",
    ]


def test_discorag_query_service_raises_when_blueprint_misses_final_context() -> None:
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead", "chunk_supplemental": "context"},
        answer_constraints=[],
        plan_steps=[],
        metadata={
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces chunk_b",
                }
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError, match="missing final context ids"):
        service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is None


def test_discorag_build_answer_request_raises_when_blueprint_misses_final_context() -> (
    None
):
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead", "chunk_supplemental": "context"},
        answer_constraints=[],
        plan_steps=[],
        metadata={
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces chunk_b",
                }
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError, match="missing final context ids"):
        service.build_answer_request("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is None


def test_discorag_query_service_raises_when_promotion_metadata_is_stale() -> None:
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental_1",
        document_id="doc_alpha",
        text="First supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental_1": supplemental_chunk
    }
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_supplemental_1", "chunk_b"],
        chunk_roles={
            "chunk_supplemental_1": "context",
            "chunk_b": "detail",
        },
        answer_constraints=[],
        plan_steps=[],
        metadata={
            "promoted_chunk_ids": [
                "chunk_supplemental_1",
                "chunk_supplemental_2",
            ],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_a",
                    "with_chunk_id": "chunk_supplemental_1",
                    "reason": "supplemental_1 replaces chunk_a",
                },
                {
                    "replace_chunk_id": "chunk_missing",
                    "with_chunk_id": "chunk_supplemental_2",
                    "reason": "stale promotion should not leak",
                },
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    with pytest.raises(
        ProcessingError,
        match="promotions are inconsistent with final contexts",
    ):
        service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is None


def test_discorag_rst_boundary_receives_all_default_discourse_visible_chunks() -> None:
    chunks = [_chunk(f"chunk_{index}") for index in range(12)]
    retrieval_result = _retrieval_result(chunks[:6])
    retrieval_result.source_selection = GraphFirstSourceSelection(
        sources=[],
        final_context_k=6,
        discourse_selection_k=12,
        context_token_budget=None,
        omitted_source_count=6,
        fallback_reason=None,
    )
    supplemental: dict[str, RetrievedChunk] = {}
    for index, chunk in enumerate(chunks):
        selected_for_answer = index < 6
        selected_for_discourse = index < 12
        if not selected_for_answer:
            chunk.metadata["selected_for_discourse"] = True
            chunk.metadata["supplemental_discourse"] = True
            supplemental[chunk.chunk_id] = chunk
        retrieval_result.source_selection.sources.append(
            GraphFirstSource(
                chunk_id=chunk.chunk_id,
                rank=index,
                score=1.0 - (index * 0.01),
                score_components={"score": 1.0 - (index * 0.01)},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=selected_for_answer,
                selected_for_discourse=selected_for_discourse,
                selection_reason="graph_path_support",
                metadata={"selected_for_discourse": selected_for_discourse},
            )
        )
    retrieval_result.metadata["supplemental_discourse_chunks"] = supplemental

    retriever = FakeTopologyRetriever(retrieval_result)
    discourse_extractor = RecordingDiscourseExtractor()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=discourse_extractor,
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    service.query("How does the pipeline use discourse?", top_k=6)

    assert discourse_extractor.selected_chunk_ids == [
        f"chunk_{index}" for index in range(12)
    ]


def test_promotion_raises_processing_error_when_supplemental_missing_at_runtime() -> (
    None
):
    """When a promotion references a supplemental chunk absent from retrieval, ProcessingError."""
    answer_chunks = [
        _chunk("chunk_a"),
        _chunk("chunk_b"),
    ]
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    # supplemental_discourse_chunks 缺失 promoted chunk
    retrieval_result.metadata["supplemental_discourse_chunks"] = {}
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a", "chunk_supplemental"],
        chunk_roles={"chunk_a": "main", "chunk_supplemental": "context"},
        answer_constraints=[],
        plan_steps=[],
        metadata={
            "promoted_chunk_ids": ["chunk_supplemental"],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces chunk_b",
                }
            ],
        },
    )
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=RecordingAnswerer(),
    )

    with pytest.raises(ProcessingError, match="not found at runtime"):
        service.query("How does MiniRAG organize evidence?", top_k=2)


def test_planner_ordering_preserved_over_retrieval_order() -> None:
    """Answer-facing blueprint ordered_chunk_ids follows planner order, not retrieval score order."""
    answer_chunks = [
        _chunk("chunk_b"),
        _chunk("chunk_a"),
    ]
    supplemental_chunk = RetrievedChunk(
        chunk_id="chunk_supplemental",
        document_id="doc_alpha",
        text="Supplemental qualifier",
        score=0.4,
        metadata={
            "selected_for_answer": False,
            "selected_for_discourse": True,
            "supplemental_discourse": True,
        },
    )
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    # Planner orders: chunk_a first, then chunk_supplemental (替换 chunk_b)
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_a", "chunk_supplemental"],
        chunk_roles={
            "chunk_a": "lead",
            "chunk_supplemental": "context",
            "chunk_b": "detail",
        },
        answer_constraints=[],
        plan_steps=[],
        metadata={
            "promoted_chunk_ids": ["chunk_supplemental"],
            "promotions": [
                {
                    "replace_chunk_id": "chunk_b",
                    "with_chunk_id": "chunk_supplemental",
                    "reason": "supplemental replaces chunk_b",
                }
            ],
        },
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    # In-place replacement: chunk_b -> chunk_supplemental in original position
    # Original retrieval order: [chunk_b, chunk_a] -> [chunk_supplemental, chunk_a]
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_supplemental",
        "chunk_a",
    ]
    assert answerer.last_request.blueprint is not None
    # Planner order preserved: [chunk_a, chunk_supplemental]
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_a",
        "chunk_supplemental",
    ]
    # metadata reflects actual context order
    assert answerer.last_request.blueprint.metadata["answer_context_chunk_ids"] == [
        "chunk_supplemental",
        "chunk_a",
    ]


def test_non_promotion_query_unchanged() -> None:
    """When blueprint has no promotions, original answer contexts pass through unchanged."""
    answer_chunks = [_chunk("chunk_a"), _chunk("chunk_b"), _chunk("chunk_c")]
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["chunk_c", "chunk_a", "chunk_b"],
        chunk_roles={
            "chunk_a": "support",
            "chunk_b": "detail",
            "chunk_c": "lead",
        },
        answer_constraints=[],
        plan_steps=[],
        metadata={},  # 无 promotions
    )
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(
            result=_retrieval_result(chunks=answer_chunks),
        ),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )

    service.query("How does MiniRAG organize evidence?", top_k=3)

    assert answerer.last_request is not None
    # Contexts pass through unchanged (no promotion)
    assert [c.chunk_id for c in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_b",
        "chunk_c",
    ]
    # Blueprint ordering follows planner order [C, A, B]
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_c",
        "chunk_a",
        "chunk_b",
    ]
    assert answerer.last_request.blueprint.metadata["answer_context_chunk_ids"] == [
        "chunk_a",
        "chunk_b",
        "chunk_c",
    ]


def test_discorag_query_service_falls_back_to_minirag_contexts_when_blueprint_exhausts() -> (
    None
):
    answer_chunks = [_chunk("chunk_a"), _chunk("chunk_b")]
    supplemental_chunk = _chunk("chunk_supplemental")
    supplemental_chunk.metadata["selected_for_answer"] = False
    supplemental_chunk.metadata["selected_for_discourse"] = True

    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }

    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    assert answerer.last_request.mode == "standard"
    assert answerer.last_request.blueprint is None
    assert [c.chunk_id for c in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_b",
    ]
    assert "chunk_supplemental" not in [
        c.chunk_id for c in answerer.last_request.contexts
    ]
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"
    assert result.metadata["discorag_error"]["attempts"] == 2
    assert result.metadata["discorag_error"]["max_attempts"] == 2
    assert result.metadata["discorag_error"]["user_visible"] is True
    assert "chunk_roles" in result.metadata["discorag_error"]["message"]


def test_discorag_query_service_fallback_metadata_identifies_rst_stage() -> None:
    retrieval_result = _retrieval_result(chunks=[_chunk("chunk_a")])

    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=_ExhaustedDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=1)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "rst_extraction"
    assert (
        result.metadata["discorag_error"]["error_type"]
        == "StructurerAttemptsExhaustedError"
    )
    assert result.metadata["discorag_error"]["failure_type"] == "validation_error"
    assert result.metadata["discorag_error"]["attempts"] == 2
    assert result.metadata["discorag_error"]["max_attempts"] == 2
    assert result.metadata["discorag_error"]["user_visible"] is True


def test_discorag_query_service_fallback_metadata_identifies_graph_stage() -> None:
    retrieval_result = _retrieval_result(chunks=[_chunk("chunk_a")])

    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=_ExhaustedGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=1)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "inter_chunk_graph"
    assert (
        result.metadata["discorag_error"]["error_type"]
        == "StructurerAttemptsExhaustedError"
    )
    assert result.metadata["discorag_error"]["failure_type"] == "validation_error"
    assert result.metadata["discorag_error"]["attempts"] == 2
    assert result.metadata["discorag_error"]["max_attempts"] == 2
    assert result.metadata["discorag_error"]["user_visible"] is True


def test_discorag_query_service_records_success_for_minirag_fallback(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        result = service.query("q", top_k=1)

    assert result.metadata["discorag_degraded"] is True
    assert "query_succeeded" in _event_names(caplog)
    assert outcomes == ["succeeded"]


def test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata() -> None:
    retrieval_result = TopologyRetrievalResult(
        query="ambiguous question",
        grounded_query=GroundedQuery(
            query="ambiguous question",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        chunks=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="retrieved evidence",
                score=1.0,
                metadata={"selected_for_answer": True, "selected_for_discourse": True},
            )
        ],
        paths=[],
        metadata={
            "retrieval_rewrite": {
                "enabled": True,
                "triggered": True,
                "status": "failed",
                "fallback_source": "initial_candidate_snapshot",
            },
            "supplemental_discourse_chunks": {},
        },
    )
    retriever = FakeTopologyRetriever(result=retrieval_result)
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("ambiguous question", top_k=1)

    assert answerer.last_request is not None
    assert answerer.last_request.metadata["retrieval_rewrite"]["status"] == "failed"
    assert retriever.calls == [("ambiguous question", 1)]


def test_discorag_query_service_fallback_metadata_uses_structured_error() -> None:
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    result = service.query("q", top_k=1)

    error = result.metadata["discorag_error"]
    assert error["stage"] == "blueprint"
    assert error["error_type"] == "StructurerAttemptsExhaustedError"
    assert error["failure_type"] == "validation_error"
    assert error["attempts"] == 2
    assert error["max_attempts"] == 2
    assert error["user_visible"] is True


def test_discorag_query_service_fallback_preserves_retrieval_rewrite_metadata() -> None:
    retrieval_result = _retrieval_result(chunks=[_chunk("chunk_a")])
    retrieval_result.metadata["retrieval_rewrite"] = {
        "enabled": True,
        "triggered": True,
        "status": "failed",
        "fallback_source": "initial_candidate_snapshot",
    }
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=1)

    assert answerer.last_request is not None
    assert answerer.last_request.metadata["retrieval_rewrite"] == {
        "enabled": True,
        "triggered": True,
        "status": "failed",
        "fallback_source": "initial_candidate_snapshot",
    }
    assert result.metadata["retrieval_rewrite"] == {
        "enabled": True,
        "triggered": True,
        "status": "failed",
        "fallback_source": "initial_candidate_snapshot",
    }


def test_discorag_query_service_fallback_reuses_single_retrieval_result() -> None:
    retriever = FakeTopologyRetriever()
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=2)

    assert retriever.calls == [("How does MiniRAG organize evidence?", 2)]
    assert answerer.last_request is not None
    assert answerer.last_request.mode == "standard"
    assert result.metadata["answer_mode"] == "minirag_fallback"
