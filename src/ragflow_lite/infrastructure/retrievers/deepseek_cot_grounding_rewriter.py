from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class DeepSeekCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self.client.complete_json(
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input_text=normalized_query,
                )
                return parse_cot_grounding_result(
                    text,
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

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "DeepSeek CoT grounding rewriter requires api_key and base_url "
                "when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )
