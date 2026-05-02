from __future__ import annotations

import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import GroundedQuery

QUERY_GROUNDING_INSTRUCTIONS = """Ground the user query for MiniRAG graph retrieval.

Return exactly one JSON object with this shape:
{
  "answer_type_keywords": ["concept", "mechanism"],
  "entities_from_query": ["MiniRAG", "chunk recovery"]
}

Rules:
- Use short strings only.
- Do not invent facts beyond the query.
- Do not return markdown or prose outside the JSON object.
"""


class DeepSeekChatQueryGrounder:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = client or self._build_client(api_key, base_url)

    def ground(self, query: str) -> GroundedQuery:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("Query grounding requires a query.")

        response_text = self.client.complete_json(
            instructions=QUERY_GROUNDING_INSTRUCTIONS,
            input_text=normalized_query,
        )
        payload = self._load_payload(response_text)
        return GroundedQuery(
            query=normalized_query,
            answer_type_keywords=_string_list(payload, "answer_type_keywords"),
            entities_from_query=_string_list(payload, "entities_from_query"),
            metadata={"grounder": "deepseek_chat", "model": self.model},
        )

    def _load_payload(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProcessingError("Query grounder returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise ProcessingError("Query grounder must return a JSON object.")
        if not isinstance(payload.get("answer_type_keywords"), list):
            raise ProcessingError("Query grounder output missing answer_type_keywords.")
        if not isinstance(payload.get("entities_from_query"), list):
            raise ProcessingError("Query grounder output missing entities_from_query.")
        return payload

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "DeepSeek query grounder requires api_key and base_url "
                "when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in payload[key]:
        if not isinstance(item, str) or not item.strip():
            raise ProcessingError(f"Query grounder field '{key}' must contain strings.")
        value = item.strip()
        identity = value.casefold()
        if identity in seen:
            continue
        values.append(value)
        seen.add(identity)
    return values
