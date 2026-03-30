"""查询回答服务。

该服务只负责"检索 -> 回答"这条链路，不承载 HTTP 细节，
也不处理底层索引实现的具体逻辑。
"""

from __future__ import annotations

from ragflow_lite.domain.errors import ProcessingError, RagflowLiteError
from ragflow_lite.domain.models import AnswerResult
from ragflow_lite.domain.ports import Answerer, Retriever


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
        try:
            contexts = self.retriever.retrieve(query, top_k)
            return self.answerer.answer(query, contexts)
        except RagflowLiteError:
            raise
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
            raise ProcessingError("Failed to answer query.") from exc
