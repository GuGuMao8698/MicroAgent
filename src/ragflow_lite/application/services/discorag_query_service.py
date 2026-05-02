from __future__ import annotations

from ragflow_lite.application.services.discorag_answer_blueprint_builder import (
    DiscoRAGAnswerBlueprintBuilder,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.models import AnswerRequest, AnswerResult
from ragflow_lite.domain.ports import (
    Answerer,
    IntraChunkDiscourseExtractor,
    TopologyContextRetriever,
)


class DiscoRAGQueryService:
    """Query-time DiscoRAG orchestration without changing the standard query path."""

    def __init__(
        self,
        retriever: TopologyContextRetriever,
        evidence_package_builder: EvidencePackageBuilder,
        discourse_extractor: IntraChunkDiscourseExtractor,
        blueprint_builder: DiscoRAGAnswerBlueprintBuilder,
        answerer: Answerer,
    ) -> None:
        self.retriever = retriever
        self.evidence_package_builder = evidence_package_builder
        self.discourse_extractor = discourse_extractor
        self.blueprint_builder = blueprint_builder
        self.answerer = answerer

    def query(self, query: str, top_k: int) -> AnswerResult:
        retrieval_result = self.retriever.retrieve_context(query, top_k)
        evidence_package = self.evidence_package_builder.build(retrieval_result)
        discourse_package = self.discourse_extractor.extract(evidence_package)
        blueprint = self.blueprint_builder.build(discourse_package)
        return self.answerer.answer(
            AnswerRequest(
                query=query,
                contexts=retrieval_result.chunks,
                mode="discorag",
                blueprint=blueprint,
            )
        )
