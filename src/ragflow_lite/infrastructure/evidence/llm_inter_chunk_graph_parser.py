"""Parse and validate LLM-produced inter-chunk discourse graph JSON.

This module defines the output contract for the LLM inter-chunk discourse
graph builder (Task 3). It handles parsing raw JSON from the LLM, filtering
out UNRELATED relations, and strictly validating every entry.

Contract reviewed 2026-05-10T12:00:00+08:00. LLM may infer discourse
structure; code must strictly validate. Invalid non-unrelated entries raise
ProcessingError immediately. No deterministic fallback.

Confidence clamping is intentionally retained: numeric out-of-range confidence
is clamped to [0.0, 1.0] per existing spec. Non-numeric optional confidence
is treated as absent (None).
"""

from __future__ import annotations

import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    InterChunkDiscourseGraph,
    InterChunkDiscourseRelation,
)

# ── Paper relation labels (21 including UNRELATED) ──────────────────────────

PAPER_INTER_CHUNK_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "supports",
        "contradicts",
        "elaborates",
        "exemplifies",
        "causes",
        "results_from",
        "enables",
        "prevents",
        "precedes",
        "follows",
        "simultaneous",
        "background_for",
        "generalizes",
        "specifies",
        "compares_with",
        "contrasts_with",
        "supplements",
        "replaces",
        "motivates",
        "justifies",
        "unrelated",
    }
)

# Materialized graph edges — all paper labels except UNRELATED.
MATERIALIZED_RELATION_TYPES: frozenset[str] = PAPER_INTER_CHUNK_RELATION_TYPES - {
    "unrelated"
}


# ── JSON schema expected from the LLM ───────────────────────────────────────
#
# {
#   "relations": [
#     {
#       "source_chunk_id": str,
#       "target_chunk_id": str,
#       "relation_type": str,
#       "rationale": str | null,
#       "confidence": float | null
#     },
#     ...
#   ]
# }


def parse_llm_inter_chunk_graph(
    raw_json: str,
    *,
    chunk_ids: list[str],
    query: str,
    llm_metadata: dict[str, Any] | None = None,
) -> InterChunkDiscourseGraph:
    """Parse and validate raw LLM JSON output into an InterChunkDiscourseGraph.

    Args:
        raw_json: JSON string produced by the LLM.
        chunk_ids: Discourse-visible chunk IDs to validate source/target against.
        query: The originating query.
        llm_metadata: Optional model/provider metadata to attach to the graph.

    Returns:
        InterChunkDiscourseGraph with valid relations and metadata including
        unrelated drop count.

    Raises:
        ProcessingError: If the JSON is unparseable, has wrong structure, or
            contains any structurally invalid entry (non-object, missing fields,
            unknown relation label, unknown chunk id, or self-reference).
            The only silent drop is ``unrelated``.
    """
    # ── Parse JSON ───────────────────────────────────────────────────────
    try:
        payload = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProcessingError(
            f"LLM inter-chunk graph output is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ProcessingError("LLM inter-chunk graph output must be a JSON object.")

    raw_relations = payload.get("relations")
    if raw_relations is None:
        raise ProcessingError("LLM inter-chunk graph output missing 'relations' key.")
    if not isinstance(raw_relations, list):
        raise ProcessingError(
            "LLM inter-chunk graph output 'relations' must be a list."
        )

    # ── Strict validation of individual relations ────────────────────────
    valid_chunk_ids = set(chunk_ids)
    valid_relations: list[InterChunkDiscourseRelation] = []
    dropped_unrelated = 0
    clamped_confidence_count = 0

    for idx, raw in enumerate(raw_relations):
        # 非 dict 条目直接失败
        if not isinstance(raw, dict):
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] must be a JSON object, "
                f"got {type(raw).__name__}."
            )

        # Required string fields
        source = raw.get("source_chunk_id")
        target = raw.get("target_chunk_id")
        relation_type = raw.get("relation_type")

        if not isinstance(source, str) or not source.strip():
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] missing or empty "
                f"'source_chunk_id'."
            )
        if not isinstance(target, str) or not target.strip():
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] missing or empty "
                f"'target_chunk_id'."
            )
        if not isinstance(relation_type, str) or not relation_type.strip():
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] missing or empty "
                f"'relation_type'."
            )

        relation_type = relation_type.strip()
        source = source.strip()
        target = target.strip()

        # 未知 relation label 直接失败
        if relation_type not in PAPER_INTER_CHUNK_RELATION_TYPES:
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] has unknown "
                f"relation type '{relation_type}'."
            )

        # 未知 chunk id 直接失败
        if source not in valid_chunk_ids:
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] references unknown "
                f"source chunk '{source}'."
            )
        if target not in valid_chunk_ids:
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] references unknown "
                f"target chunk '{target}'."
            )

        # 自引用直接失败
        if source == target:
            raise ProcessingError(
                f"LLM inter-chunk graph relations[{idx}] has self-referential "
                f"edge (source == target == '{source}')."
            )

        # unrelated 是唯一允许静默丢弃的标签，但必须先通过结构校验
        if relation_type == "unrelated":
            dropped_unrelated += 1
            continue

        # Optional fields — confidence clamping per spec
        rationale = raw.get("rationale")
        if rationale is not None and not isinstance(rationale, str):
            rationale = None

        confidence = raw.get("confidence")
        if confidence is not None:
            if not isinstance(confidence, (int, float)):
                confidence = None
            else:
                confidence = float(confidence)
                if confidence < 0.0 or confidence > 1.0:
                    confidence = max(0.0, min(1.0, confidence))
                    clamped_confidence_count += 1

        valid_relations.append(
            InterChunkDiscourseRelation(
                source_chunk_id=source,
                target_chunk_id=target,
                relation_type=relation_type,
                rationale=rationale,
                confidence=confidence,
                metadata={"source": "llm_inter_chunk_graph"},
            )
        )

    # ── Build metadata ───────────────────────────────────────────────────
    metadata: dict[str, Any] = {
        "builder": "llm_inter_chunk_graph",
        "llm_raw_relation_count": len(raw_relations),
        "valid_relation_count": len(valid_relations),
        "dropped_unrelated": dropped_unrelated,
        "clamped_confidence_count": clamped_confidence_count,
    }
    if llm_metadata:
        metadata["llm"] = llm_metadata

    return InterChunkDiscourseGraph(
        query=query,
        chunk_ids=chunk_ids,
        relations=valid_relations,
        metadata=metadata,
    )
