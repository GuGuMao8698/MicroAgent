from __future__ import annotations

from math import ceil
from typing import Any, Literal

from ragflow_lite.domain.models import (
    GroundingGateDecision,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
)

RewriteStatus = Literal["not_triggered", "succeeded", "failed", "degraded"]


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
