"""DeepSeek Chat Completions answerer."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    RetrievedChunk,
)
from ragflow_lite.infrastructure.answerers.constants import FALLBACK_ANSWER
from ragflow_lite.infrastructure.llms.deepseek_chat import DeepSeekChatCompletionsClient

_CITATION_TOKEN_RE = re.compile(r"<cite:(\d+)>")
_BARE_DIGIT_BRACKET_RE = re.compile(r"\[(\d+)\]")

_PACKAGED_TEMPLATES_DIR = Path(__file__).parent
_DEFAULT_VARIANT = "citations"
_VARIANT_ENV_VAR = "RAGFLOW_LITE_DEEPSEEK_ANSWER_PROMPT_VARIANT"
_TEMPLATE_CACHE: dict[str, str] = {}


def _format_page(metadata: dict[str, Any]) -> str:
    """根据 ``page_start`` / ``page_end`` 生成页信息行，无页信息时返回空串。"""
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end")
    if page_start is None or page_end is None:
        return ""
    if page_start == page_end:
        return f"page: {page_start}"
    return f"pages: {page_start}-{page_end}"


def _load_packaged_template(variant: str) -> str:
    cached = _TEMPLATE_CACHE.get(variant)
    if cached is not None:
        return cached
    filename = (
        "answer_with_citations.txt" if variant == "citations" else "answer_plain.txt"
    )
    text = (_PACKAGED_TEMPLATES_DIR / filename).read_text(encoding="utf-8").strip()
    _TEMPLATE_CACHE[variant] = text
    return text


def _load_answerer_instructions(
    instructions: str | None = None,
    instructions_path: str | None = None,
    variant: str | None = None,
) -> str:
    if instructions is not None and instructions_path is not None:
        raise RuntimeError("Use either instructions or instructions_path, not both.")

    if instructions_path is not None:
        loaded = Path(instructions_path).read_text(encoding="utf-8").strip()
        if not loaded:
            raise RuntimeError("Custom answerer prompt file must not be empty.")
        return loaded

    if instructions is not None:
        loaded = instructions.strip()
        if not loaded:
            raise RuntimeError("Custom answerer instructions must not be empty.")
        return loaded

    effective_variant = variant or os.environ.get(_VARIANT_ENV_VAR) or _DEFAULT_VARIANT
    return _load_packaged_template(effective_variant)


class DeepSeekChatAnswerer:
    """Use DeepSeek Chat Completions API to synthesize grounded answers."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
        instructions: str | None = None,
        instructions_path: str | None = None,
        render_citations: bool = True,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.render_citations = render_citations
        effective_variant = "citations" if render_citations else "plain"
        self.instructions = _load_answerer_instructions(
            instructions=instructions,
            instructions_path=instructions_path,
            variant=effective_variant,
        )
        self.client = client or self._build_client(
            api_key=api_key or "",
            base_url=base_url or "https://api.deepseek.com",
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def answer(self, request: AnswerRequest) -> AnswerResult:
        if not request.contexts:
            return AnswerResult(
                answer=FALLBACK_ANSWER,
                contexts=[],
                metadata={
                    "strategy": "fallback",
                    "answer_mode": request.mode,
                    "blueprint_applied": False,
                },
            )

        ordered_contexts, blueprint_applied, fallback_reason = self._order_contexts(
            request
        )
        input_text = self._build_input(request, ordered_contexts)
        raw_answer = self.client.complete(self.instructions, input_text).strip()

        if self.render_citations:
            answer_text = self._clean_citations(raw_answer, len(ordered_contexts))
        else:
            answer_text = self._strip_citation_residuals(raw_answer)
        return AnswerResult(
            answer=answer_text,
            contexts=ordered_contexts,
            metadata={
                "strategy": "deepseek_chat",
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
                "answer_mode": request.mode,
                "blueprint_applied": blueprint_applied,
                **(
                    {"blueprint_fallback_reason": fallback_reason}
                    if fallback_reason is not None
                    else {}
                ),
            },
        )

    @staticmethod
    def _clean_citations(text: str, max_index: int) -> str:
        def _replace(match: re.Match[str]) -> str:
            n = int(match.group(1))
            return f"[{n}]" if 1 <= n <= max_index else ""

        return _CITATION_TOKEN_RE.sub(_replace, text)

    @staticmethod
    def _strip_citation_residuals(text: str) -> str:
        """Remove <cite:N> tokens and bare [N] digit brackets from text."""
        text = _CITATION_TOKEN_RE.sub("", text)
        return _BARE_DIGIT_BRACKET_RE.sub("", text)

    @staticmethod
    def _build_client(
        api_key: str, base_url: str, model: str, reasoning_effort: str
    ) -> DeepSeekChatCompletionsClient:
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    @staticmethod
    def _build_input(
        request: AnswerRequest,
        contexts: list[RetrievedChunk],
    ) -> str:
        lines = [
            "Question:",
            request.query.strip(),
            "",
        ]

        blueprint_lines = _format_blueprint_lines(request.blueprint)
        if blueprint_lines:
            lines.extend(
                [
                    "Blueprint:",
                    *blueprint_lines,
                    "",
                ]
            )

        lines.extend(
            [
                "Contexts:",
            ]
        )

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

    @staticmethod
    def _order_contexts(
        request: AnswerRequest,
    ) -> tuple[list[RetrievedChunk], bool, str | None]:
        score_ordered = sorted(
            request.contexts, key=lambda context: context.score, reverse=True
        )

        if request.mode != "discorag":
            return score_ordered, False, None

        if request.blueprint is None:
            return score_ordered, False, "missing_blueprint"

        ordered_contexts = _order_contexts_by_blueprint(
            score_ordered,
            request.blueprint,
        )
        if ordered_contexts is None:
            return score_ordered, False, "invalid_blueprint"
        return ordered_contexts, True, None


def _order_contexts_by_blueprint(
    contexts: list[RetrievedChunk],
    blueprint: AnswerBlueprint,
) -> list[RetrievedChunk] | None:
    contexts_by_id = {context.chunk_id: context for context in contexts}
    context_ids = set(contexts_by_id)

    # Blueprint references unknown chunks — treat as invalid.
    unknown_ids = set(blueprint.ordered_chunk_ids) - context_ids
    if unknown_ids:
        return None

    selected: list[RetrievedChunk] = []
    seen_ids: set[str] = set()

    for chunk_id in blueprint.ordered_chunk_ids:
        if chunk_id in seen_ids:
            return None
        selected.append(contexts_by_id[chunk_id])
        seen_ids.add(chunk_id)

    if seen_ids != context_ids:
        return None

    return selected


def _format_blueprint_lines(blueprint: AnswerBlueprint | None) -> list[str]:
    if blueprint is None:
        return []

    lines: list[str] = []
    if blueprint.ordered_chunk_ids:
        lines.append("ordered_chunk_ids: " + ", ".join(blueprint.ordered_chunk_ids))
    if blueprint.chunk_roles:
        role_text = "; ".join(
            f"{chunk_id}={role}" for chunk_id, role in blueprint.chunk_roles.items()
        )
        lines.append(f"chunk_roles: {role_text}")
    if blueprint.answer_constraints:
        lines.append("answer_constraints: " + " | ".join(blueprint.answer_constraints))
    if blueprint.plan_steps:
        lines.append("plan_steps: " + " | ".join(blueprint.plan_steps))
    return lines
