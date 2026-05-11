from __future__ import annotations

from math import ceil
from typing import Any, Literal

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    CoTGroundingResult,
    EnrichedGroundingInput,
    GroundingGateDecision,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
    RetrievedChunk,
    TopologyRetrievalResult,
)
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    render_enriched_grounding_input,
)

RewriteStatus = Literal["not_triggered", "succeeded", "failed", "degraded"]


def snapshot_initial_candidates(
    result: TopologyRetrievalResult,
) -> InitialCandidateSnapshot:
    return InitialCandidateSnapshot(
        query=result.query,
        grounded_query=result.grounded_query,
        candidates=list(result.chunks),
        source_selection=result.source_selection,
        metadata=dict(result.metadata),
    )


def _selected_answer_candidate_count(snapshot: InitialCandidateSnapshot) -> int:
    if snapshot.source_selection is None:
        return len(snapshot.candidates)
    return sum(
        1 for source in snapshot.source_selection.sources if source.selected_for_answer
    )


def _threshold(requested_top_n: int) -> int:
    return ceil(requested_top_n / 2)


def decide_grounding_gate(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> GroundingGateDecision:
    selected_count = _selected_answer_candidate_count(snapshot)
    threshold = _threshold(requested_top_n)
    signals: dict[str, Any] = {
        "selected_answer_candidate_count": selected_count,
        "selected_answer_candidate_threshold": threshold,
        "requested_top_n": requested_top_n,
    }
    if selected_count < threshold:
        return GroundingGateDecision(
            should_rewrite=True,
            route="rewrite",
            reason="selected_answer_candidate_count_below_threshold",
            signals=signals,
        )
    return GroundingGateDecision(
        should_rewrite=False,
        route="accept",
        reason="selected_answer_candidate_count_meets_threshold",
        signals=signals,
    )


def assess_post_rewrite(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> PostRewriteAssessment:
    decision = decide_grounding_gate(snapshot, requested_top_n=requested_top_n)
    return PostRewriteAssessment(
        gate_passed=not decision.should_rewrite,
        reason=decision.reason,
        signals=decision.signals,
    )


def build_retrieval_rewrite_metadata(
    *,
    enabled: bool,
    triggered: bool,
    strategy: str | None,
    status: RewriteStatus,
    gate_reason: str | None,
    attempts: int,
    failure_reason: str | None,
    fallback_source: str | None,
    initial_candidate_count: int,
    enriched_candidate_count: int,
    post_rewrite_gate_passed: bool | None,
    post_rewrite_gate_reason: str | None,
    answer_notice_required: bool,
) -> dict[str, Any]:
    return {
        "retrieval_rewrite": {
            "enabled": enabled,
            "triggered": triggered,
            "strategy": strategy,
            "status": status,
            "gate_reason": gate_reason,
            "attempts": attempts,
            "failure_reason": failure_reason,
            "fallback_source": fallback_source,
            "initial_candidate_count": initial_candidate_count,
            "enriched_candidate_count": enriched_candidate_count,
            "post_rewrite_gate_passed": post_rewrite_gate_passed,
            "post_rewrite_gate_reason": post_rewrite_gate_reason,
            "answer_notice_required": answer_notice_required,
        }
    }


def build_enriched_grounding_input(
    *,
    snapshot: InitialCandidateSnapshot,
    rewrite: CoTGroundingResult,
) -> EnrichedGroundingInput:
    if rewrite.status != "succeeded":
        raise ProcessingError("CoT grounding rewrite did not succeed.")
    if rewrite.original_query.strip() != snapshot.query.strip():
        raise ProcessingError("CoT grounding original_query does not match snapshot.")
    steps = [step.strip() for step in rewrite.solution_steps if step.strip()]
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return EnrichedGroundingInput(original_query=snapshot.query, solution_steps=steps)


def render_enriched_query(input_value: EnrichedGroundingInput) -> str:
    return render_enriched_grounding_input(
        original_query=input_value.original_query,
        solution_steps=input_value.solution_steps,
    )


def merge_retrieval_results(
    *,
    initial: TopologyRetrievalResult,
    enriched: TopologyRetrievalResult,
    top_k: int,
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for source_name, chunks in (
        ("initial", initial.chunks),
        ("enriched", enriched.chunks),
    ):
        for chunk in chunks:
            existing = merged.get(chunk.chunk_id)
            source_set: set[str] = set()
            if existing is not None:
                source_set.update(
                    existing.metadata.get("retrieval_rewrite_sources", [])
                )
                if existing.score >= chunk.score:
                    target = existing
                else:
                    target = chunk
            else:
                target = chunk
            source_set.add(source_name)
            target = RetrievedChunk(
                chunk_id=target.chunk_id,
                document_id=target.document_id,
                text=target.text,
                score=target.score,
                metadata={
                    **target.metadata,
                    "retrieval_rewrite_sources": sorted(source_set),
                },
            )
            merged[chunk.chunk_id] = target
    return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:top_k]
