from __future__ import annotations

from typing import Literal, Protocol

from ragflow_lite.domain.models import AnswerResult

QueryMode = Literal["standard", "discorag"]


class QueryPath(Protocol):
    def query(self, query: str, top_k: int) -> AnswerResult: ...


class QueryModeRouter:
    """Dispatch query requests to the selected application query path."""

    def __init__(
        self,
        standard_service: QueryPath,
        discorag_service: QueryPath,
    ) -> None:
        self.standard_service = standard_service
        self.discorag_service = discorag_service

    def query(
        self,
        query: str,
        top_k: int,
        mode: QueryMode = "standard",
    ) -> AnswerResult:
        if mode == "standard":
            return self.standard_service.query(query, top_k)
        if mode == "discorag":
            return self.discorag_service.query(query, top_k)
        raise ValueError(f"Unsupported query mode: {mode}")
