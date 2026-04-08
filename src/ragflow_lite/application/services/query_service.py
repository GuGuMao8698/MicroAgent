"""查询回答服务。

该服务只负责"检索 -> 回答"这条链路，不承载 HTTP 细节，
也不处理底层索引实现的具体逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import AnswerResult
from ragflow_lite.domain.ports import Answerer, Retriever
from ragflow_lite.shared.observability import log_event, record_query_outcome

logger = logging.getLogger(__name__)


def _log_query_event(
    level: int,
    event: str,
    query: str,
    top_k: int,
    **fields: Any,
) -> None:
    log_event(
        logger,
        level,
        event,
        top_k=top_k,
        query_length=len(query),
        **fields,
    )


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
        _log_query_event(logging.INFO, "query_started", query, top_k, outcome="started")
        try:
            contexts = self.retriever.retrieve(query, top_k)
            result = self.answerer.answer(query, contexts)
            _log_query_event(
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
            _log_query_event(
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
            _log_query_event(
                logging.ERROR,
                "query_failed",
                query,
                top_k,
                outcome="failed",
                error_type=type(exc).__name__,
            )
            record_query_outcome("failed")
            raise ProcessingError("Failed to answer query.") from exc
