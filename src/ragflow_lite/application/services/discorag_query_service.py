from __future__ import annotations

import logging

from ragflow_lite.application.services._query_observability import log_query_event
from ragflow_lite.application.services.discorag_answer_blueprint_builder import (
    DiscoRAGAnswerBlueprintBuilder,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.errors import RagflowLiteError
from ragflow_lite.domain.models import AnswerRequest, AnswerResult
from ragflow_lite.domain.ports import (
    Answerer,
    IntraChunkDiscourseExtractor,
    TopologyContextRetriever,
)
from ragflow_lite.shared.observability import record_query_outcome

logger = logging.getLogger(__name__)


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
        log_query_event(
            logger,
            logging.INFO,
            "query_started",
            query,
            top_k,
            outcome="started",
        )
        try:
            retrieval_result = self.retriever.retrieve_context(query, top_k)
            evidence_package = self.evidence_package_builder.build(retrieval_result)
            discourse_package = self.discourse_extractor.extract(evidence_package)
            blueprint = self.blueprint_builder.build(discourse_package)
            result = self.answerer.answer(
                AnswerRequest(
                    query=query,
                    contexts=retrieval_result.chunks,
                    mode="discorag",
                    blueprint=blueprint,
                    metadata={
                        "source_selection": retrieval_result.metadata.get(
                            "source_selection"
                        ),
                    },
                )
            )
            log_query_event(
                logger,
                logging.INFO,
                "query_succeeded",
                query,
                top_k,
                outcome="succeeded",
                context_count=len(result.contexts),
            )
            record_query_outcome("succeeded")
            return result
        except RagflowLiteError as exc:
            log_query_event(
                logger,
                logging.ERROR,
                "query_failed",
                query,
                top_k,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            record_query_outcome("failed")
            raise
        except Exception as exc:
            log_query_event(
                logger,
                logging.ERROR,
                "query_failed",
                query,
                top_k,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            record_query_outcome("failed")
            raise
