from __future__ import annotations

import json

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult

COT_GROUNDING_INSTRUCTIONS = """Create retrieval-facing solution steps for MiniRAG grounding.

Return exactly one JSON object with this shape:
{
  "original_query": "the exact user query",
  "solution_steps": ["short retrieval-facing step"]
}

Rules:
- Return solution_steps only; do not return any retrieval-level fields such as entity lists, relation lists, keywords, or answer-type tags.
- Keep each step short and useful for retrieval grounding.
- Do not output markdown or prose outside the JSON object.
"""

_FORBIDDEN_FIELDS = {
    "entities",
    "relations",
    "keywords",
    "answer_type_keywords",
    "entities_from_query",
}


def parse_cot_grounding_result(
    text: str,
    *,
    expected_query: str,
    attempts: int,
) -> CoTGroundingResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProcessingError("CoT grounding returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProcessingError("CoT grounding must return a JSON object.")
    if _FORBIDDEN_FIELDS.intersection(payload):
        raise ProcessingError("CoT grounding output must not include retrieval fields.")
    original_query = payload.get("original_query")
    if not isinstance(original_query, str) or original_query.strip() != expected_query:
        raise ProcessingError("CoT grounding original_query does not match.")
    raw_steps = payload.get("solution_steps")
    if not isinstance(raw_steps, list):
        raise ProcessingError("CoT grounding output missing solution_steps.")
    steps: list[str] = []
    for step in raw_steps:
        if not isinstance(step, str) or not step.strip():
            raise ProcessingError("CoT grounding solution_steps must contain strings.")
        steps.append(step.strip())
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query=expected_query,
        solution_steps=steps,
        attempts=attempts,
        failure_reason=None,
    )


def failed_cot_grounding_result(
    *,
    original_query: str,
    attempts: int,
    failure_reason: str,
) -> CoTGroundingResult:
    return CoTGroundingResult(
        status="failed",
        strategy="cot_grounding",
        original_query=original_query,
        solution_steps=[],
        attempts=attempts,
        failure_reason=failure_reason,
    )


def render_enriched_grounding_input(
    *,
    original_query: str,
    solution_steps: list[str],
) -> str:
    lines = ["Original query:", original_query.strip(), "", "Solution steps:"]
    lines.extend(
        f"{index}. {step.strip()}" for index, step in enumerate(solution_steps, start=1)
    )
    return "\n".join(lines).strip()
