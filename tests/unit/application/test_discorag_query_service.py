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
    blueprint: AnswerBlueprint = field(
        default_factory=lambda: AnswerBlueprint(
            ordered_chunk_ids=["chunk_a"],
            chunk_roles={"chunk_a": "context"},
            answer_constraints=["Follow ordered_chunk_ids."],
            plan_steps=["Start from the first ordered chunk."],
            metadata={"status": "ok"},
        )
    )

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
        self.last_package = package
        self.last_graph = graph
        return self.blueprint


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
        inter_chunk_graph_builder=RecordingGraphBuilder(),
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
        metadata={"promoted_chunk_ids": ["chunk_supplemental"]},
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
    # chunk_b 被挤掉，因为 promoted chunk 替换了最弱位置


def test_discorag_query_service_blueprint_preserves_promoted_context_order() -> None:
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
        ordered_chunk_ids=["chunk_a", "chunk_supplemental", "chunk_b"],
        chunk_roles={
            "chunk_a": "main",
            "chunk_supplemental": "context",
            "chunk_b": "detail",
        },
        answer_constraints=["Respect qualification."],
        plan_steps=["Use the supplemental qualifier."],
        metadata={"promoted_chunk_ids": ["chunk_supplemental"]},
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
        "chunk_supplemental",
        "chunk_a",
    ]
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.blueprint.ordered_chunk_ids == [
        "chunk_supplemental",
        "chunk_a",
    ]


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
