"""OpenAI Responses API answerer."""

from __future__ import annotations

from typing import Any

from ragflow_lite.domain.models import AnswerResult, RetrievedChunk
from ragflow_lite.infrastructure.answerers.constants import FALLBACK_ANSWER

ANSWERER_INSTRUCTIONS = """You answer questions only with the provided contexts.
If the contexts do not contain enough information, reply exactly with:
当前已索引内容中没有足够信息回答这个问题。
Do not use outside knowledge.
Do not invent sources, citations, or document metadata.
Do not mention any documents that are not included in the contexts."""


class OpenAIResponsesAnswerer:
    """Use OpenAI Responses API to synthesize grounded answers."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        store: bool,
        verbosity: str,
        client: Any | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.verbosity = verbosity
        self.client = client or self._build_client(api_key, base_url)

    def answer(self, query: str, contexts: list[RetrievedChunk]) -> AnswerResult:
        if not contexts:
            return AnswerResult(
                answer=FALLBACK_ANSWER,
                contexts=[],
                metadata={"strategy": "fallback"},
            )

        ordered_contexts = sorted(contexts, key=lambda context: context.score, reverse=True)
        response = self.client.responses.create(
            model=self.model,
            instructions=ANSWERER_INSTRUCTIONS,
            input=self._build_input(query, ordered_contexts),
            reasoning={"effort": self.reasoning_effort},
            store=self.store,
            text={"verbosity": self.verbosity},
        )

        return AnswerResult(
            answer=response.output_text.strip(),
            contexts=contexts,
            metadata={
                "strategy": "openai_responses",
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "store": self.store,
            },
        )

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _build_input(query: str, contexts: list[RetrievedChunk]) -> str:
        lines = [
            "Question:",
            query.strip(),
            "",
            "Contexts:",
        ]

        for index, context in enumerate(contexts, start=1):
            metadata = context.metadata or {}
            lines.extend(
                [
                    f"[{index}]",
                    f"document_id: {context.document_id}",
                    f"chunk_id: {context.chunk_id}",
                    f"score: {context.score:.6f}",
                    f"filename: {metadata.get('filename', '')}",
                    f"file_type: {metadata.get('file_type', '')}",
                    "text:",
                    context.text.strip(),
                    "",
                ]
            )

        return "\n".join(lines).strip()
