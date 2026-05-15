from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ragflow_lite.application.services.model_facing_retrieval import (
    model_facing_retrieval_payload,
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerRequest

RetrievalMode = Literal["standard", "discorag"]


class AnswerRequestBuilder(Protocol):
    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest: ...


@dataclass(slots=True)
class AgentRetrievalResult:
    payload: dict[str, object]
    runtime_metadata: dict[str, object] = field(default_factory=dict)


class AgentRetrievalService:
    def __init__(
        self,
        standard_service: AnswerRequestBuilder,
        discorag_service: AnswerRequestBuilder,
    ) -> None:
        self.standard_service = standard_service
        self.discorag_service = discorag_service

    def retrieve(
        self,
        query: str,
        top_k: int,
        mode: RetrievalMode = "standard",
    ) -> AgentRetrievalResult:
        if mode == "standard":
            request = self.standard_service.build_answer_request(query, top_k)
            ordered_contexts = order_standard_contexts_for_model(request.contexts)
            payload = model_facing_retrieval_payload(
                query=request.query,
                contexts=ordered_contexts,
                blueprint=None,
            )
            return AgentRetrievalResult(
                payload=payload,
                runtime_metadata=dict(request.metadata),
            )

        if mode == "discorag":
            request = self.discorag_service.build_answer_request(query, top_k)
            if request.blueprint is None:
                raise ProcessingError("DiscoRAG retrieval requires a blueprint")
            ordered_contexts = order_discorag_contexts_for_model(request.contexts)
            payload = model_facing_retrieval_payload(
                query=request.query,
                contexts=ordered_contexts,
                blueprint=request.blueprint,
            )
            return AgentRetrievalResult(
                payload=payload,
                runtime_metadata=dict(request.metadata),
            )

        raise ProcessingError(f"Unknown retrieval mode: {mode}")
