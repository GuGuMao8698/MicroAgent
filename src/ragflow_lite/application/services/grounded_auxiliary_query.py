from __future__ import annotations

from typing import Literal, cast

from ragflow_lite.domain.models import GroundedAuxiliaryQuery, GroundedQuery

_MAX_GROUNDING_TERMS_PER_KIND = 16
_MAX_LEGACY_QUERY_CHARACTERS = 2048
_GROUNDING_STATES = frozenset({"complete", "partial", "missing", "failed"})


def build_grounded_auxiliary_query(
    *,
    query_text: str,
    grounded_query: GroundedQuery,
    retrieval_pass_id: str,
    rewrite_source: Literal["original", "enriched"],
) -> GroundedAuxiliaryQuery:
    normalized_query = " ".join(query_text.split())
    if not normalized_query:
        raise ValueError("grounded auxiliary query_text must be non-empty")
    if not retrieval_pass_id:
        raise ValueError("grounded auxiliary retrieval_pass_id must be non-empty")

    all_entities = _dedupe(grounded_query.entities_from_query)
    all_keywords = _dedupe(grounded_query.answer_type_keywords)
    entities = all_entities[:_MAX_GROUNDING_TERMS_PER_KIND]
    keywords = all_keywords[:_MAX_GROUNDING_TERMS_PER_KIND]
    raw_state = grounded_query.metadata.get("grounding_state", "complete")
    grounding_state = str(raw_state)
    if grounding_state not in _GROUNDING_STATES:
        raise ValueError(f"unsupported grounding_state: {grounding_state}")
    fallback = "raw_query_only" if grounding_state != "complete" else "none"
    failure_code = grounded_query.metadata.get("grounding_failure_code")
    metadata = dict(grounded_query.metadata)
    metadata["grounding_terms_truncated"] = len(entities) != len(all_entities) or len(
        keywords
    ) != len(all_keywords)
    return GroundedAuxiliaryQuery(
        query_text=normalized_query,
        entities_from_query=entities,
        answer_type_keywords=keywords,
        retrieval_pass_id=retrieval_pass_id,
        rewrite_source=rewrite_source,
        grounding_state=cast(
            Literal["complete", "partial", "missing", "failed"], grounding_state
        ),
        grounding_fallback=fallback,
        grounding_failure_code=None if failure_code is None else str(failure_code),
        metadata=metadata,
    )


def render_legacy_auxiliary_query(request: GroundedAuxiliaryQuery) -> str:
    values = [
        request.query_text,
        *request.entities_from_query,
        *request.answer_type_keywords,
    ]
    rendered = " ".join(_dedupe(values))
    return rendered[:_MAX_LEGACY_QUERY_CHARACTERS].rstrip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
