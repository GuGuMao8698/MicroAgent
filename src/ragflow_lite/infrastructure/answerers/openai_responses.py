"""OpenAI Responses API answerer."""

from __future__ import annotations

import re
from typing import Any

from ragflow_lite.domain.models import AnswerResult, RetrievedChunk
from ragflow_lite.infrastructure.answerers.constants import FALLBACK_ANSWER

_CITATION_TOKEN_RE = re.compile(r"<cite:(\d+)>")


def _format_page(metadata: dict[str, Any]) -> str:
    """根据 ``page_start`` / ``page_end`` 生成页信息行，无页信息时返回空串。"""
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end")
    if page_start is None or page_end is None:
        return ""
    if page_start == page_end:
        return f"page: {page_start}"
    return f"pages: {page_start}-{page_end}"


ANSWERER_INSTRUCTIONS = """You answer questions only with the provided contexts.

Citation rules:
- Each context is numbered [1], [2], etc. in the order provided.
- When making a key claim or factual assertion, use <cite:n> to cite the source context.
  Example: "The project supports txt files <cite:1>." → will render as "The project supports txt files [1]."
  Wrong: "The project supports txt files [1]." ← never use bare bracket citations.
- Only cite numbers that exist in the provided contexts.
- Use separate tags for multiple sources: <cite:1><cite:2> or <cite:1> <cite:2>, never <cite:1,2>.
- Do not use <cite:0> or any number beyond the last context.

Grounding rules:
- Answer only from the provided contexts. Do not use outside knowledge.
- If the contexts do not contain enough information, reply exactly with:
当前已索引内容中没有足够信息回答这个问题。
- Do not invent sources, citations, or document metadata.
- Do not mention any documents that are not included in the contexts."""


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

        ordered_contexts = sorted(
            contexts, key=lambda context: context.score, reverse=True
        )
        response = self.client.responses.create(
            model=self.model,
            instructions=ANSWERER_INSTRUCTIONS,
            input=self._build_input(query, ordered_contexts),
            reasoning={"effort": self.reasoning_effort},
            store=self.store,
            text={"verbosity": self.verbosity},
        )

        raw_answer = response.output_text.strip()
        return AnswerResult(
            answer=self._clean_citations(raw_answer, len(ordered_contexts)),
            contexts=ordered_contexts,
            metadata={
                "strategy": "openai_responses",
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "store": self.store,
            },
        )

    @staticmethod
    def _clean_citations(text: str, max_index: int) -> str:
        def _replace(match: re.Match[str]) -> str:
            n = int(match.group(1))
            return f"[{n}]" if 1 <= n <= max_index else ""

        return _CITATION_TOKEN_RE.sub(_replace, text)

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
            page_line = _format_page(metadata)

            lines.extend(
                [
                    f"[{index}]",
                    f"document_id: {context.document_id}",
                    f"chunk_id: {context.chunk_id}",
                    f"score: {context.score:.6f}",
                    f"filename: {metadata.get('filename', '')}",
                    f"file_type: {metadata.get('file_type', '')}",
                ]
            )
            if page_line:
                lines.append(page_line)
            lines.extend(
                [
                    "text:",
                    context.text.strip(),
                    "",
                ]
            )

        return "\n".join(lines).strip()
