from __future__ import annotations

from copy import deepcopy

from ragflow_lite.domain.models import AnswerBlueprint, RetrievedChunk


def order_standard_contexts_for_model(
    contexts: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    ordered = sorted(contexts, key=lambda chunk: chunk.score, reverse=True)
    if len(ordered) < 3:
        return ordered
    return [ordered[0], *ordered[2:], ordered[1]]


def order_discorag_contexts_for_model(
    contexts: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    return sorted(contexts, key=lambda chunk: chunk.score, reverse=True)


def context_payload(context: RetrievedChunk) -> dict[str, object]:
    return {
        "chunk_id": context.chunk_id,
        "document_id": context.document_id,
        "text": context.text,
        "score": context.score,
        "metadata": deepcopy(context.metadata),
    }


def blueprint_payload(blueprint: AnswerBlueprint) -> dict[str, object]:
    # 这里只暴露模型需要遵循的回答编排信息，避免把 planner/debug 状态泄漏进 evidence。
    return {
        "chunk_roles": deepcopy(blueprint.chunk_roles),
        "answer_constraints": deepcopy(blueprint.answer_constraints),
        "plan_steps": deepcopy(blueprint.plan_steps),
        "ordered_chunk_ids": deepcopy(blueprint.ordered_chunk_ids),
    }


def model_facing_retrieval_payload(
    *,
    query: str,
    contexts: list[RetrievedChunk],
    blueprint: AnswerBlueprint | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": query,
        "contexts": [context_payload(context) for context in contexts],
    }
    if blueprint is not None:
        payload["blueprint"] = blueprint_payload(blueprint)
    return payload
