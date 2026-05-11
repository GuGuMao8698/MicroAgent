"""查询回答服务。

该服务只负责"检索 -> 回答"这条链路，不承载 HTTP 细节，
也不处理底层索引实现的具体逻辑。
"""

from __future__ import annotations

import logging
from typing import cast

from ragflow_lite.application.services._query_observability import log_query_event
from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import AnswerRequest, AnswerResult
from ragflow_lite.domain.ports import Answerer, Retriever, TopologyContextRetriever
from ragflow_lite.shared.observability import record_query_outcome

logger = logging.getLogger(__name__)


class QueryService:
    """封装查询主流程的业务入口。"""

    def __init__(
        self,
        retriever: Retriever,
        answerer: Answerer,
    ) -> None:
        self.retriever = retriever
        self.answerer = answerer

    def query(self, query: str, top_k: int) -> AnswerResult:
        """针对已索引内容执行检索并生成回答。"""
        log_query_event(
            logger,
            logging.INFO,
            "query_started",
            query,
            top_k,
            outcome="started",
        )
        try:
            contexts, request_metadata = self._retrieve_contexts_and_metadata(
                query,
                top_k,
            )
            result = self.answerer.answer(
                AnswerRequest(
                    query=query,
                    contexts=contexts,
                    metadata=request_metadata,
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
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
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
            raise ProcessingError("Failed to answer query.") from exc

    def _retrieve_contexts_and_metadata(
        self,
        query: str,
        top_k: int,
    ) -> tuple[list, dict[str, object]]:
        request_metadata: dict[str, object] = {}
        retrieve_context = getattr(self.retriever, "retrieve_context", None)
        if not callable(retrieve_context):
            return self.retriever.retrieve(query, top_k), request_metadata

        retrieval_result = cast(TopologyContextRetriever, self.retriever).retrieve_context(
            query,
            top_k,
        )
        retrieval_rewrite = retrieval_result.metadata.get("retrieval_rewrite")
        if retrieval_rewrite is not None:
            request_metadata["retrieval_rewrite"] = retrieval_rewrite
        return retrieval_result.chunks, request_metadata
