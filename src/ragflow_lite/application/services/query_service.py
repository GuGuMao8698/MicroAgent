"""查询回答服务。

该服务只负责“查询向量化 -> 检索 -> 回答”这条链路，不承载 HTTP 细节，
也不处理底层索引实现的具体逻辑。
"""

from __future__ import annotations

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerResult
from ragflow_lite.domain.ports import Answerer, Embedder, VectorIndex


class QueryService:
    """封装查询主流程的业务入口。"""

    def __init__(
        self,
        embedder: Embedder,
        vector_index: VectorIndex,
        answerer: Answerer,
    ) -> None:
        self.embedder = embedder
        self.vector_index = vector_index
        self.answerer = answerer

    def query(self, query: str, top_k: int) -> AnswerResult:
        """针对已索引内容执行检索并生成回答。"""
        try:
            query_vector = self.embedder.embed_query(query)
            contexts = self.vector_index.search(query_vector, top_k)
            return self.answerer.answer(query, contexts)
        except Exception as exc:  # pragma: no cover - guarded by integration coverage
            raise ProcessingError("Failed to answer query.") from exc
