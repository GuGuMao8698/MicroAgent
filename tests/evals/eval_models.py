from __future__ import annotations

import json
import os
from typing import Any

from deepeval.models import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

_LLM_CALL_TIMEOUT = float(os.environ.get("RAGFLOW_LITE_DEEPEVAL_LLM_TIMEOUT", "300"))
_DEFAULT_JSON_MAX_TOKENS = 2048
_SCHEMA_JSON_INSTRUCTION = (
    "Return only one JSON object that conforms to this JSON schema. "
    "Do not include markdown or prose outside the JSON."
)


def _schema_prompt(prompt: str, schema: type[BaseModel]) -> str:
    schema_json = schema.model_json_schema()
    return "\n\n".join(
        [
            prompt.strip(),
            _SCHEMA_JSON_INSTRUCTION,
            "JSON schema:",
            json.dumps(schema_json, ensure_ascii=False, sort_keys=True),
        ]
    )


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


class DeepSeekChatDeepEvalModel(DeepEvalBaseLLM):
    """Use DeepSeek Chat Completions for deepeval-compatible calls."""

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
        super().__init__(model=model)

    def load_model(self) -> OpenAI:
        return OpenAI(
            api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
        )

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        client = self.load_model()
        prompt_text = _schema_prompt(prompt, schema) if schema is not None else prompt
        request: dict[str, Any] = {
            "model": self.name,
            "messages": [{"role": "user", "content": prompt_text}],
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if schema is not None:
            request["response_format"] = {"type": "json_object"}
            request["max_tokens"] = _DEFAULT_JSON_MAX_TOKENS
        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("DeepSeek returned no content.")
        if schema is None:
            return content.strip()
        return schema.model_validate_json(content.strip())

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        async_client = AsyncOpenAI(
            api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
        )
        prompt_text = _schema_prompt(prompt, schema) if schema is not None else prompt
        request: dict[str, Any] = {
            "model": self.name,
            "messages": [{"role": "user", "content": prompt_text}],
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        if schema is not None:
            request["response_format"] = {"type": "json_object"}
            request["max_tokens"] = _DEFAULT_JSON_MAX_TOKENS
        response = await async_client.chat.completions.create(**request)
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("DeepSeek returned no content.")
        if schema is None:
            return content.strip()
        return schema.model_validate_json(content.strip())

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
