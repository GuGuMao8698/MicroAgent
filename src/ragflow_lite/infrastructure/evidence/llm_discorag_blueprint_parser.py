"""Parse and validate LLM-produced DiscoRAG answer blueprint JSON.

This module defines the output contract for the LLM DiscoRAG answer blueprint
builder.  It handles parsing raw JSON from the LLM, validating chunk IDs,
roles, constraint types, promotions, and referenced relation/RST unit IDs,
then produces a validated AnswerBlueprint.

Structural failures (bad types, unknown IDs, invalid vocab, broken promotions)
raise ProcessingError. No deterministic fallback.
"""

from __future__ import annotations

import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerBlueprint

# ── Compact vocabularies ─────────────────────────────────────────────────────

_BLUEPRINT_CHUNK_ROLES: frozenset[str] = frozenset(
    {
        "lead",
        "support",
        "background",
        "caveat",
        "comparison",
        "definition",
        "condition",
        "context",
    }
)

_BLUEPRINT_CONSTRAINT_TYPES: frozenset[str] = frozenset(
    {
        "caveat",
        "condition",
        "conflict",
        "comparison",
        "support",
        "background",
        "definition",
        "ordering",
    }
)


def parse_llm_discorag_blueprint(
    raw_json: str | dict[str, Any],
    *,
    answer_chunk_ids: list[str],
    supplemental_chunk_ids: list[str],
    known_relation_ids: list[str],
    known_rst_unit_ids: list[str],
    top_k: int,
    llm_metadata: dict[str, Any] | None = None,
) -> AnswerBlueprint:
    """Parse and validate raw LLM JSON output into an AnswerBlueprint.

    Args:
        raw_json: JSON string or parsed dict produced by the LLM structurer.
        answer_chunk_ids: Chunk IDs selected for direct answer use.
        supplemental_chunk_ids: Chunk IDs visible via discourse but not selected
            for direct answer (promotion candidates).
        known_relation_ids: Inter-chunk relation IDs from the discourse graph.
        known_rst_unit_ids: RST unit IDs from intra-chunk structures.
        top_k: Maximum number of chunks allowed in final output.
        llm_metadata: Optional model/provider metadata to attach.

    Returns:
        Validated AnswerBlueprint with metadata including drop counters and
        builder provenance.

    Raises:
        ProcessingError: If the output is unparseable, structurally invalid,
            or fails any validation rule.
    """
    # ── Parse JSON ───────────────────────────────────────────────────────
    payload = _parse_json(raw_json)

    if not isinstance(payload, dict):
        raise ProcessingError("LLM blueprint output must be a JSON object.")

    answer_set = set(answer_chunk_ids)
    supplemental_set = set(supplemental_chunk_ids)
    all_known_ids = answer_set | supplemental_set

    # ── Required field: final_answer_chunk_ids ───────────────────────────
    raw_chunk_ids = _require_list_field(payload, "final_answer_chunk_ids")

    # 不允许空列表：answer candidates 存在时 final list 必须非空
    if not raw_chunk_ids and answer_chunk_ids:
        raise ProcessingError(
            "LLM blueprint 'final_answer_chunk_ids' must not be empty "
            "when answer candidates exist."
        )

    # 禁止重复 chunk id，所有 id 必须是 string
    seen_ids: set[str] = set()
    for cid in raw_chunk_ids:
        if not isinstance(cid, str):
            raise ProcessingError(
                f"Chunk ID in 'final_answer_chunk_ids' must be a string, "
                f"got {type(cid).__name__}: {cid!r}"
            )
        if cid in seen_ids:
            raise ProcessingError(
                f"Duplicate chunk ID in 'final_answer_chunk_ids': {cid!r}"
            )
        seen_ids.add(cid)

    # budget overflow
    if len(raw_chunk_ids) > top_k:
        raise ProcessingError(
            f"LLM blueprint 'final_answer_chunk_ids' count ({len(raw_chunk_ids)}) "
            f"exceeds top_k budget ({top_k})."
        )

    # 所有 chunk id 必须是已知 answer 或 supplemental id
    for cid in raw_chunk_ids:
        if cid not in all_known_ids:
            raise ProcessingError(
                f"Unknown chunk ID in 'final_answer_chunk_ids': {cid!r}"
            )

    # ── Validate promotions (replacement semantics) ─────────────────────
    promotions = _validate_promotions(
        payload,
        answer_set=answer_set,
        supplemental_set=supplemental_set,
        final_chunk_ids=raw_chunk_ids,
    )

    # promoted_chunk_ids 供下游可观测
    promoted_chunk_ids = [p["with_chunk_id"] for p in promotions]

    # ── Validate chunk_roles (strict) ───────────────────────────────────
    chunk_roles = _validate_chunk_roles(payload, all_known_ids, raw_chunk_ids)

    # ── Validate answer_constraints (strict) ────────────────────────────
    known_relation_id_set = set(known_relation_ids)
    known_rst_unit_id_set = set(known_rst_unit_ids)

    valid_constraints, valid_constraint_dicts = _validate_constraints(
        payload,
        all_known_ids=all_known_ids,
        known_relation_ids=known_relation_id_set,
        known_rst_unit_ids=known_rst_unit_id_set,
    )

    # ── Validate plan_steps (strict) ────────────────────────────────────
    valid_plan_steps, valid_plan_step_dicts = _validate_plan_steps(
        payload,
        all_known_ids=all_known_ids,
        known_relation_ids=known_relation_id_set,
        known_rst_unit_ids=known_rst_unit_id_set,
    )

    # ── Validate promotion provenance refs ──────────────────────────────
    for promo in promotions:
        _validate_id_refs(
            promo, known_relation_id_set, known_rst_unit_id_set, "promotion"
        )

    # ── Build metadata ──────────────────────────────────────────────────
    metadata: dict[str, Any] = {
        "builder": "llm_discorag_blueprint_parser",
        "final_chunk_count": len(raw_chunk_ids),
        "promotion_count": len(promotions),
        "promoted_chunk_ids": promoted_chunk_ids,
    }
    # 保留 LLM 输出 metadata
    llm_meta = payload.get("metadata")
    if isinstance(llm_meta, dict):
        metadata["llm_output_metadata"] = llm_meta
    if llm_metadata:
        metadata["llm"] = llm_metadata
    # 存储 promotions 供下游 applicator 使用
    metadata["promotions"] = promotions
    # 聚合所有结构化对象引用的 provenance ids
    metadata["source_relation_ids"] = _collect_ids(
        valid_constraint_dicts + valid_plan_step_dicts + promotions,
        "source_relation_ids",
    )
    metadata["source_rst_unit_ids"] = _collect_ids(
        valid_constraint_dicts + valid_plan_step_dicts + promotions,
        "source_rst_unit_ids",
    )

    return AnswerBlueprint(
        ordered_chunk_ids=raw_chunk_ids,
        chunk_roles=chunk_roles,
        answer_constraints=valid_constraints,
        plan_steps=valid_plan_steps,
        metadata=metadata,
    )


# ── Internal helpers ─────────────────────────────────────────────────────────


def _parse_json(raw_json: str | dict[str, Any]) -> Any:
    """Parse raw input to a Python object.

    Accepts either a JSON string or an already-parsed dict.
    """
    if isinstance(raw_json, dict):
        return raw_json
    try:
        return json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProcessingError(f"LLM blueprint output is not valid JSON: {exc}") from exc


def _require_list_field(payload: dict[str, Any], field: str) -> list[Any]:
    """Require *field* to be a list, raising ProcessingError otherwise."""
    value = payload.get(field)
    if value is None:
        raise ProcessingError(f"LLM blueprint output missing '{field}'.")
    if not isinstance(value, list):
        raise ProcessingError(f"LLM blueprint output '{field}' must be a list.")
    return value


def _require_string_list(values: Any, field_context: str) -> None:
    """Validate that *values* is a list of strings.

    Raises ProcessingError if any element is not a string.
    """
    if not isinstance(values, list):
        raise ProcessingError(f"'{field_context}' must be a list of strings.")
    for v in values:
        if not isinstance(v, str):
            raise ProcessingError(
                f"'{field_context}' must contain only strings, "
                f"got {type(v).__name__}: {v!r}"
            )


# ── Promotion validation ─────────────────────────────────────────────────────


def _validate_promotions(
    payload: dict[str, Any],
    *,
    answer_set: set[str],
    supplemental_set: set[str],
    final_chunk_ids: list[str],
) -> list[dict[str, Any]]:
    """Validate replacement-semantics promotions.

    Contract reviewed 2026-05-10T10:00:00+08:00.  Promotions are strictly
    replacement: answer chunk out, supplemental chunk in.  Do not silently
    drop invalid promotions; raise ProcessingError on any violation.
    """
    raw_promotions = payload.get("promotions", [])
    if not isinstance(raw_promotions, list):
        raise ProcessingError("LLM blueprint output 'promotions' must be a list.")

    final_set = set(final_chunk_ids)
    replace_seen: set[str] = set()
    with_seen: set[str] = set()

    validated: list[dict[str, Any]] = []
    for promo in raw_promotions:
        if not isinstance(promo, dict):
            raise ProcessingError("Each promotion must be a JSON object.")
        replace_id = promo.get("replace_chunk_id")
        with_id = promo.get("with_chunk_id")
        if not isinstance(replace_id, str):
            raise ProcessingError("Promotion 'replace_chunk_id' must be a string.")
        if not isinstance(with_id, str):
            raise ProcessingError("Promotion 'with_chunk_id' must be a string.")

        # replace_chunk_id 必须是原始 answer chunk
        if replace_id not in answer_set:
            raise ProcessingError(
                f"Promotion replaces non-answer chunk: {replace_id!r}"
            )
        # with_chunk_id 必须是 supplemental chunk
        if with_id not in supplemental_set:
            raise ProcessingError(
                f"Promotion inserts non-supplemental chunk: {with_id!r}"
            )
        # with_chunk_id 必须出现在 final_answer_chunk_ids 中
        if with_id not in final_set:
            raise ProcessingError(
                f"Promotion 'with_chunk_id' {with_id!r} "
                f"must appear in 'final_answer_chunk_ids'."
            )
        # replace_chunk_id 不能出现在 final_answer_chunk_ids 中
        if replace_id in final_set:
            raise ProcessingError(
                f"Promotion 'replace_chunk_id' {replace_id!r} "
                f"must not appear in 'final_answer_chunk_ids' "
                f"(replaced by {with_id!r})."
            )

        # 禁止同一个 replace_chunk_id 被多次替换
        if replace_id in replace_seen:
            raise ProcessingError(
                f"Duplicate promotion for 'replace_chunk_id': {replace_id!r}"
            )
        # 禁止同一个 with_chunk_id 被多次使用
        if with_id in with_seen:
            raise ProcessingError(
                f"Duplicate promotion for 'with_chunk_id': {with_id!r}"
            )

        replace_seen.add(replace_id)
        with_seen.add(with_id)
        validated.append(promo)

    # final list 中每个 supplemental chunk 都必须有匹配的有效 promotion
    for cid in final_chunk_ids:
        if cid in supplemental_set and cid not in with_seen:
            raise ProcessingError(
                f"Supplemental chunk {cid!r} in 'final_answer_chunk_ids' "
                f"without a valid promotion."
            )

    return validated


# ── chunk_roles validation (strict) ──────────────────────────────────────────


def _validate_chunk_roles(
    payload: dict[str, Any],
    all_known_ids: set[str],
    final_chunk_ids: list[str],
) -> dict[str, str]:
    """Validate chunk_roles: exact coverage of final chunks, keys known, roles valid."""
    raw = payload.get("chunk_roles")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ProcessingError("LLM blueprint output 'chunk_roles' must be an object.")

    result: dict[str, str] = {}
    for cid, role in raw.items():
        if cid not in all_known_ids:
            raise ProcessingError(f"chunk_roles references unknown chunk id: {cid!r}")
        if not isinstance(role, str) or role not in _BLUEPRINT_CHUNK_ROLES:
            raise ProcessingError(
                f"Invalid chunk role {role!r} for chunk {cid!r}. "
                f"Must be one of: {', '.join(sorted(_BLUEPRINT_CHUNK_ROLES))}."
            )
        result[cid] = role

    final_chunk_id_set = set(final_chunk_ids)
    role_chunk_id_set = set(result)
    missing_ids = sorted(final_chunk_id_set - role_chunk_id_set)
    extra_ids = sorted(role_chunk_id_set - final_chunk_id_set)
    if missing_ids or extra_ids:
        problems: list[str] = []
        if missing_ids:
            problems.append(f"missing roles for final chunks {missing_ids!r}")
        if extra_ids:
            problems.append(f"non-final chunk roles {extra_ids!r}")
        raise ProcessingError(
            "LLM blueprint output 'chunk_roles' must cover "
            f"'final_answer_chunk_ids' exactly: {'; '.join(problems)}."
        )
    return result


# ── answer_constraints validation (strict) ───────────────────────────────────


def _validate_constraints(
    payload: dict[str, Any],
    *,
    all_known_ids: set[str],
    known_relation_ids: set[str],
    known_rst_unit_ids: set[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate answer_constraints: must be list, each element object with valid type and string text."""
    raw = payload.get("answer_constraints")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise ProcessingError(
            "LLM blueprint output 'answer_constraints' must be a list."
        )

    texts: list[str] = []
    dicts: list[dict[str, Any]] = []
    for raw_c in raw:
        if not isinstance(raw_c, dict):
            raise ProcessingError("Each answer constraint must be a JSON object.")
        ctype = raw_c.get("type")
        if not isinstance(ctype, str) or ctype not in _BLUEPRINT_CONSTRAINT_TYPES:
            raise ProcessingError(
                f"Invalid constraint type {ctype!r}. "
                f"Must be one of: {', '.join(sorted(_BLUEPRINT_CONSTRAINT_TYPES))}."
            )
        # 验证 text 是 string
        text = raw_c.get("text")
        if text is not None and not isinstance(text, str):
            raise ProcessingError(
                f"Constraint 'text' must be a string, "
                f"got {type(text).__name__}: {text!r}"
            )
        # 验证 source_chunk_ids 是已知 id 列表
        _validate_source_chunk_ids(raw_c, all_known_ids, "constraint")
        _validate_id_refs(raw_c, known_relation_ids, known_rst_unit_ids, "constraint")
        texts.append(text if isinstance(text, str) else "")
        dicts.append(raw_c)
    return texts, dicts


# ── plan_steps validation (strict) ───────────────────────────────────────────


def _validate_plan_steps(
    payload: dict[str, Any],
    *,
    all_known_ids: set[str],
    known_relation_ids: set[str],
    known_rst_unit_ids: set[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate plan_steps: must be list, each element object with string text."""
    raw = payload.get("plan_steps")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise ProcessingError("LLM blueprint output 'plan_steps' must be a list.")

    texts: list[str] = []
    dicts: list[dict[str, Any]] = []
    for raw_step in raw:
        if not isinstance(raw_step, dict):
            raise ProcessingError("Each plan step must be a JSON object.")
        # 验证 text 是 string
        text = raw_step.get("text")
        if text is not None and not isinstance(text, str):
            raise ProcessingError(
                f"Plan step 'text' must be a string, "
                f"got {type(text).__name__}: {text!r}"
            )
        # 验证 source_chunk_ids 是已知 id 列表
        _validate_source_chunk_ids(raw_step, all_known_ids, "plan_step")
        _validate_id_refs(raw_step, known_relation_ids, known_rst_unit_ids, "plan_step")
        texts.append(text if isinstance(text, str) else "")
        dicts.append(raw_step)
    return texts, dicts


# ── Provenance reference validation ──────────────────────────────────────────


def _validate_id_refs(
    obj: dict[str, Any],
    known_relation_ids: set[str],
    known_rst_unit_ids: set[str],
    context: str,
) -> None:
    """Validate that referenced relation IDs and RST unit IDs are known.

    Also validates source id fields are lists of strings.
    """
    # source_relation_ids 类型 + 内容验证
    src_rids = obj.get("source_relation_ids")
    if src_rids is not None:
        _require_string_list(src_rids, f"{context} source_relation_ids")
        for rid in src_rids:
            if rid not in known_relation_ids:
                raise ProcessingError(f"Unknown relation ID {rid!r} in {context}.")

    # source_rst_unit_ids 类型 + 内容验证
    src_uids = obj.get("source_rst_unit_ids")
    if src_uids is not None:
        _require_string_list(src_uids, f"{context} source_rst_unit_ids")
        for uid in src_uids:
            if uid not in known_rst_unit_ids:
                raise ProcessingError(f"Unknown RST unit ID {uid!r} in {context}.")


def _validate_source_chunk_ids(
    obj: dict[str, Any],
    all_known_ids: set[str],
    context: str,
) -> None:
    """Validate source_chunk_ids: must be list of strings, all known."""
    src_cids = obj.get("source_chunk_ids")
    if src_cids is None:
        return
    _require_string_list(src_cids, f"{context} source_chunk_ids")
    for cid in src_cids:
        if cid not in all_known_ids:
            raise ProcessingError(
                f"Unknown chunk ID {cid!r} in {context} source_chunk_ids."
            )


def _collect_ids(
    objects: list[Any],
    key: str,
) -> list[str]:
    """Collect unique IDs from a list of dicts under the given key."""
    seen: set[str] = set()
    result: list[str] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for value in obj.get(key, []):
            if isinstance(value, str) and value not in seen:
                seen.add(value)
                result.append(value)
    return result
