from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class OpenAIResponsesCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        store: bool,
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input=normalized_query,
                    reasoning={"effort": self.reasoning_effort},
                    store=self.store,
                )
                return parse_cot_grounding_result(
                    response.output_text,
                    expected_query=normalized_query,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
        return failed_cot_grounding_result(
            original_query=normalized_query,
            attempts=self.max_attempts,
            failure_reason=last_error,
        )

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)
