from __future__ import annotations

import logging

from ragflow_lite.application.services._query_observability import log_query_event
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.application.services.metadata_sanitizer import (
    sanitize_retrieval_chunks,
)
from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    RetrievedChunk,
    TopologyRetrievalResult,
)
from ragflow_lite.domain.ports import (
    Answerer,
    BlueprintBuilder,
    InterChunkDiscourseGraphBuilder,
    IntraChunkDiscourseExtractor,
    TopologyContextRetriever,
)
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptsExhaustedError,
)
from ragflow_lite.shared.observability import record_query_outcome

logger = logging.getLogger(__name__)


def _contexts_with_bounded_promotion(
    contexts: list[RetrievedChunk],
    retrieval_result: TopologyRetrievalResult,
    blueprint: AnswerBlueprint,
) -> list[RetrievedChunk]:
    """Apply planner promotions as in-place replacement of answer contexts.

    Contract reviewed 2026-05-10T12:00:00+08:00.  Each promotion replaces
    one answer chunk with one supplemental chunk.  Do not append promoted
    chunks; do not use promoted_chunk_ids as the source of truth.
    """
    promotions = blueprint.metadata.get("promotions")
    if not isinstance(promotions, list) or not promotions:
        return contexts
    budget = len(contexts)
    supplemental = retrieval_result.metadata.get("supplemental_discourse_chunks", {})
    if not isinstance(supplemental, dict):
        return contexts

    # 构建替换映射：replace_chunk_id -> with_chunk_id
    replace_map: dict[str, str] = {}
    for promo in promotions:
        if not isinstance(promo, dict):
            continue
        replace_id = promo.get("replace_chunk_id")
        with_id = promo.get("with_chunk_id")
        if isinstance(replace_id, str) and isinstance(with_id, str):
            replace_map[replace_id] = with_id

    if not replace_map:
        return contexts

    # 在原位替换：保留原始位置，替换内容
    result: list[RetrievedChunk] = []
    for context in contexts:
        replacement_id = replace_map.get(context.chunk_id)
        if replacement_id is not None:
            chunk = supplemental.get(replacement_id)
            if isinstance(chunk, RetrievedChunk):
                result.append(chunk)
            else:
                # parser 已验证 ids 存在，运行时缺失是防御性错误
                raise ProcessingError(
                    f"Promotion references supplemental chunk "
                    f"{replacement_id!r} not found at runtime."
                )
        else:
            result.append(context)

    return result[:budget]


def _filter_metadata_chunk_ids(
    metadata: dict[str, object],
    key: str,
    context_ids: set[str],
) -> None:
    value = metadata.get(key)
    if not isinstance(value, list):
        return
    metadata[key] = [
        chunk_id
        for chunk_id in value
        if isinstance(chunk_id, str) and chunk_id in context_ids
    ]


def _blueprint_for_contexts(
    blueprint: AnswerBlueprint,
    contexts: list[RetrievedChunk],
) -> AnswerBlueprint:
    """Limit answer-facing blueprint references to the final context set.

    Contract reviewed 2026-05-10T12:00:00+08:00.  Preserve planner relative
    order from blueprint.ordered_chunk_ids filtered to final context ids.
    Do not derive ordering from retrieval score order.
    """
    context_ids = {context.chunk_id for context in contexts}
    answer_context_chunk_ids = [context.chunk_id for context in contexts]
    # 按 planner 排序过滤，保留 planner 相对顺序
    ordered_chunk_ids = [
        cid for cid in blueprint.ordered_chunk_ids if cid in context_ids
    ]
    ordered_set = set(ordered_chunk_ids)
    missing_context_ids = [
        context.chunk_id for context in contexts if context.chunk_id not in ordered_set
    ]
    if missing_context_ids:
        raw_promotions = blueprint.metadata.get("promotions")
        raw_promoted_chunk_ids = blueprint.metadata.get("promoted_chunk_ids")
        raise ProcessingError(
            "Answer blueprint missing final context ids after promotion/filtering: "
            f"missing_context_ids={missing_context_ids!r}; "
            f"final_context_ids={answer_context_chunk_ids!r}; "
            f"blueprint_ordered_chunk_ids={blueprint.ordered_chunk_ids!r}; "
            f"promoted_chunk_ids={raw_promoted_chunk_ids!r}; "
            f"promotions={raw_promotions!r}."
        )
    chunk_roles = {
        chunk_id: role
        for chunk_id, role in blueprint.chunk_roles.items()
        if chunk_id in context_ids
    }
    metadata = dict(blueprint.metadata)
    raw_promotions = metadata.pop("promotions", None)
    raw_promoted_chunk_ids = metadata.get("promoted_chunk_ids")
    for key in (
        "selected_answer_chunk_ids",
        "selected_discourse_chunk_ids",
        "supplemental_discourse_chunk_ids",
    ):
        _filter_metadata_chunk_ids(metadata, key, context_ids)
    if isinstance(raw_promotions, list):
        planner_raw_promotions: list[dict[str, object]] = []
        applied_promotions: list[dict[str, object]] = []
        for promotion in raw_promotions:
            if not isinstance(promotion, dict):
                raise ProcessingError(
                    "Answer blueprint promotions metadata must contain objects."
                )
            promotion_copy = dict(promotion)
            planner_raw_promotions.append(promotion_copy)
            replace_chunk_id = promotion_copy.get("replace_chunk_id")
            with_chunk_id = promotion_copy.get("with_chunk_id")
            if not isinstance(replace_chunk_id, str) or not isinstance(
                with_chunk_id, str
            ):
                raise ProcessingError(
                    "Answer blueprint promotions metadata must contain "
                    "string replace_chunk_id and with_chunk_id values."
                )
            if replace_chunk_id in context_ids or with_chunk_id not in context_ids:
                raise ProcessingError(
                    "Answer blueprint promotions are inconsistent with final "
                    f"contexts: replace_chunk_id={replace_chunk_id!r}, "
                    f"with_chunk_id={with_chunk_id!r}, "
                    f"final_context_ids={answer_context_chunk_ids!r}."
                )
            applied_promotions.append(promotion_copy)
        expected_promoted_chunk_ids = [
            promotion["with_chunk_id"]
            for promotion in applied_promotions
            if isinstance(promotion.get("with_chunk_id"), str)
        ]
        if raw_promoted_chunk_ids is not None:
            if not isinstance(raw_promoted_chunk_ids, list) or any(
                not isinstance(chunk_id, str) for chunk_id in raw_promoted_chunk_ids
            ):
                raise ProcessingError(
                    "Answer blueprint promoted_chunk_ids metadata must be a "
                    "list of strings when present."
                )
            if raw_promoted_chunk_ids != expected_promoted_chunk_ids:
                raise ProcessingError(
                    "Answer blueprint promoted_chunk_ids are inconsistent with "
                    f"promotions: promoted_chunk_ids={raw_promoted_chunk_ids!r}, "
                    f"expected={expected_promoted_chunk_ids!r}."
                )
        metadata["planner_raw_promotions"] = planner_raw_promotions
        metadata["applied_promotions"] = applied_promotions
        metadata["promoted_chunk_ids"] = expected_promoted_chunk_ids
    elif raw_promoted_chunk_ids is not None:
        if not isinstance(raw_promoted_chunk_ids, list) or any(
            not isinstance(chunk_id, str) for chunk_id in raw_promoted_chunk_ids
        ):
            raise ProcessingError(
                "Answer blueprint promoted_chunk_ids metadata must be a list "
                "of strings when present."
            )
        if raw_promoted_chunk_ids:
            raise ProcessingError(
                "Answer blueprint promoted_chunk_ids require matching promotions "
                "metadata."
            )
        metadata["promoted_chunk_ids"] = []
    metadata["answer_context_chunk_ids"] = answer_context_chunk_ids
    return AnswerBlueprint(
        ordered_chunk_ids=ordered_chunk_ids,
        chunk_roles=chunk_roles,
        answer_constraints=list(blueprint.answer_constraints),
        plan_steps=list(blueprint.plan_steps),
        metadata=metadata,
    )


def _discorag_fallback_metadata(
    *,
    exc: StructurerAttemptsExhaustedError,
    source_selection: object,
    retrieval_rewrite: object | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "mode": "discorag",
        "answer_mode": "minirag_fallback",
        "discorag_degraded": True,
        "source_selection": source_selection,
        "discorag_error": exc.safe_metadata(),
    }
    if retrieval_rewrite is not None:
        metadata["retrieval_rewrite"] = retrieval_rewrite
    return metadata


class DiscoRAGQueryService:
    """Query-time DiscoRAG orchestration without changing the standard query path."""

    def __init__(
        self,
        retriever: TopologyContextRetriever,
        evidence_package_builder: EvidencePackageBuilder,
        discourse_extractor: IntraChunkDiscourseExtractor,
        inter_chunk_graph_builder: InterChunkDiscourseGraphBuilder,
        blueprint_builder: BlueprintBuilder,
        answerer: Answerer,
    ) -> None:
        self.retriever = retriever
        self.evidence_package_builder = evidence_package_builder
        self.discourse_extractor = discourse_extractor
        self.inter_chunk_graph_builder = inter_chunk_graph_builder
        self.blueprint_builder = blueprint_builder
        self.answerer = answerer

    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        retrieval_result = self.retriever.retrieve_context(query, top_k)
        return self._build_answer_request_from_retrieval(query, retrieval_result)

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
            try:
                request = self._build_answer_request_from_retrieval(
                    query,
                    retrieval_result,
                )
            except StructurerAttemptsExhaustedError as exc:
                return self._answer_with_minirag_fallback(
                    query=query,
                    top_k=top_k,
                    retrieval_result=retrieval_result,
                    exc=exc,
                )
            result = self.answerer.answer(request)
            self._record_success(query, top_k, result)
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

    def _build_answer_request_from_retrieval(
        self,
        query: str,
        retrieval_result: TopologyRetrievalResult,
    ) -> AnswerRequest:
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
        answer_contexts = sanitize_retrieval_chunks(answer_contexts)
        answer_blueprint = _blueprint_for_contexts(blueprint, answer_contexts)
        answer_metadata: dict[str, object] = {
            "source_selection": retrieval_result.metadata.get("source_selection"),
        }
        if "retrieval_rewrite" in retrieval_result.metadata:
            answer_metadata["retrieval_rewrite"] = retrieval_result.metadata[
                "retrieval_rewrite"
            ]
        return AnswerRequest(
            query=query,
            contexts=answer_contexts,
            mode="discorag",
            blueprint=answer_blueprint,
            metadata=answer_metadata,
        )

    def _answer_with_minirag_fallback(
        self,
        *,
        query: str,
        top_k: int,
        retrieval_result: TopologyRetrievalResult,
        exc: StructurerAttemptsExhaustedError,
    ) -> AnswerResult:
        metadata = _discorag_fallback_metadata(
            exc=exc,
            source_selection=retrieval_result.metadata.get("source_selection"),
            retrieval_rewrite=retrieval_result.metadata.get("retrieval_rewrite"),
        )
        result = self.answerer.answer(
            AnswerRequest(
                query=query,
                contexts=sanitize_retrieval_chunks(retrieval_result.chunks),
                mode="standard",
                blueprint=None,
                metadata=metadata,
            )
        )
        result.metadata.update(metadata)
        self._record_success(query, top_k, result)
        return result

    def _record_success(self, query: str, top_k: int, result: AnswerResult) -> None:
        log_query_event(
            logger,
            logging.INFO,
            "query_succeeded",
            query,
            top_k,
            outcome="succeeded",
            context_count=len(result.contexts),
            degraded=result.metadata.get("discorag_degraded") is True,
        )
        record_query_outcome("succeeded")
