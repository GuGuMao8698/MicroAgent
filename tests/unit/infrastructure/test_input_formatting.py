from __future__ import annotations

from ragflow_lite.infrastructure.answerers._input_formatting import (
    format_retrieval_rewrite_notice,
)


def test_format_retrieval_rewrite_notice_returns_exact_notice_lines() -> None:
    assert format_retrieval_rewrite_notice(
        {
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": (
                    "selected_answer_candidate_count_below_threshold"
                ),
            }
        }
    ) == [
        "Retrieval rewrite notice:",
        "- Retrieval rewrite already ran, but the available evidence still appears insufficient.",
        "- Likely causes include missing relevant documents in the knowledge base or a query that is still too ambiguous.",
        "- Tell the user that they may need to rephrase the query or add the needed documents.",
        "",
    ]


def test_format_retrieval_rewrite_notice_returns_empty_when_notice_not_required() -> (
    None
):
    assert format_retrieval_rewrite_notice(
        {
            "retrieval_rewrite": {
                "answer_notice_required": False,
            }
        }
    ) == []
