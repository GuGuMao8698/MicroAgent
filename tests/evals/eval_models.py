from __future__ import annotations

import os
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

_LLM_CALL_TIMEOUT = float(os.environ.get("RAGFLOW_LITE_DEEPEVAL_LLM_TIMEOUT", "300"))


class ArkResponsesDeepEvalModel(DeepEvalBaseLLM):
    """Use OpenAI SDK Responses API against Ark for deepeval-compatible calls."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        reasoning_effort: str,
        timeout: float = _LLM_CALL_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.generation_kwargs = {"reasoning_effort": reasoning_effort}
        self._async_client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
        super().__init__(model=model)

    def load_model(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        request = self._build_request(prompt)
        if schema is not None:
            response = self.model.responses.parse(
                **request,
                text_format=schema,
            )
            return self._parsed_output(response)

        response = self.model.responses.create(**request)
        return self._text_output(response)

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        request = self._build_request(prompt)
        if schema is not None:
            response = await self._async_client.responses.parse(
                **request,
                text_format=schema,
            )
            return self._parsed_output(response)

        response = await self._async_client.responses.create(**request)
        return self._text_output(response)

    def get_model_name(self, *args, **kwargs) -> str:
        return self.name

    def supports_structured_outputs(self) -> bool:
        return True

    def supports_json_mode(self) -> bool:
        return True

    def supports_temperature(self):
        return None

    def supports_multimodal(self) -> bool:
        return False

    def supports_log_probs(self):
        return None

    def _build_request(self, prompt: str) -> dict[str, Any]:
        thinking_type = "disabled" if self.reasoning_effort == "minimal" else "enabled"
        return {
            "model": self.name,
            "input": prompt,
            "reasoning": {"effort": self.reasoning_effort},
            "extra_body": {"thinking": {"type": thinking_type}},
            "timeout": self.timeout,
        }

    @staticmethod
    def _parsed_output(response: Any) -> BaseModel:
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise RuntimeError("Responses.parse did not return output_parsed.")
        return parsed

    @staticmethod
    def _text_output(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text
        raise RuntimeError("Responses.create did not return output_text.")
