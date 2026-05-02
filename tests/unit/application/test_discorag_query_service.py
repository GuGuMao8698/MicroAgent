from __future__ import annotations

from dataclasses import dataclass, field

from ragflow_lite.application.services.discorag_query_service import (
    DiscoRAGQueryService,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
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
class RecordingAnswerer:
    last_request: AnswerRequest | None = None

    def answer(self, request: AnswerRequest) -> AnswerResult:
        self.last_request = request
        return AnswerResult(
            answer="done", contexts=request.contexts, metadata={"ok": True}
        )


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


def test_discorag_query_service_is_exported_from_application_services() -> None:
    from ragflow_lite.application.services import DiscoRAGQueryService as Exported

    assert Exported is DiscoRAGQueryService
