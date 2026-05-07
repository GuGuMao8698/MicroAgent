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
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    RetrievedChunk,
    TopologyRetrievalResult,
)
from ragflow_lite.domain.ports import (
    Answerer,
    InterChunkDiscourseGraphBuilder,
    IntraChunkDiscourseExtractor,
    TopologyContextRetriever,
)
from ragflow_lite.shared.observability import record_query_outcome

logger = logging.getLogger(__name__)


def _contexts_with_bounded_promotion(
    contexts: list[RetrievedChunk],
    retrieval_result: TopologyRetrievalResult,
    blueprint: AnswerBlueprint,
) -> list[RetrievedChunk]:
    """Promoted supplemental chunks replace weakest answer contexts, total bounded by budget."""
    promoted_ids = blueprint.metadata.get("promoted_chunk_ids", [])
    if not isinstance(promoted_ids, list) or not promoted_ids:
        return contexts
    budget = len(contexts)
    supplemental = retrieval_result.metadata.get("supplemental_discourse_chunks", {})
    if not isinstance(supplemental, dict):
        return contexts
    # Collect promoted chunk objects
    promoted_chunks: list[RetrievedChunk] = []
    promoted_id_set: set[str] = set()
    for chunk_id in promoted_ids:
        if not isinstance(chunk_id, str):
            continue
        chunk = supplemental.get(chunk_id)
        if isinstance(chunk, RetrievedChunk):
            promoted_chunks.append(chunk)
            promoted_id_set.add(chunk_id)
    if not promoted_chunks:
        return contexts
    # Promoted take priority; fill remaining slots from original contexts
    result: list[RetrievedChunk] = list(promoted_chunks)
    for context in contexts:
        if context.chunk_id in promoted_id_set:
            continue
        if len(result) >= budget:
            break
        result.append(context)
    return result[:budget]


class DiscoRAGQueryService:
    """Query-time DiscoRAG orchestration without changing the standard query path."""

    def __init__(
        self,
        retriever: TopologyContextRetriever,
        evidence_package_builder: EvidencePackageBuilder,
        discourse_extractor: IntraChunkDiscourseExtractor,
        inter_chunk_graph_builder: InterChunkDiscourseGraphBuilder,
        blueprint_builder: DiscoRAGAnswerBlueprintBuilder,
        answerer: Answerer,
    ) -> None:
        self.retriever = retriever
        self.evidence_package_builder = evidence_package_builder
        self.discourse_extractor = discourse_extractor
        self.inter_chunk_graph_builder = inter_chunk_graph_builder
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
            inter_chunk_graph = self.inter_chunk_graph_builder.build(discourse_package)
            blueprint = self.blueprint_builder.build(
                discourse_package,
                graph=inter_chunk_graph,
            )
            answer_contexts = _contexts_with_bounded_promotion(
                retrieval_result.chunks,
                retrieval_result,
                blueprint,
            )
            result = self.answerer.answer(
                AnswerRequest(
                    query=query,
                    contexts=answer_contexts,
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
