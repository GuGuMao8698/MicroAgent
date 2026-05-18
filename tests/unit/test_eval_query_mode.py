from __future__ import annotations

from dataclasses import dataclass

import pytest
from eval_support import build_eval_query_payload, resolve_eval_query_mode


@dataclass(frozen=True, slots=True)
class _Case:
    question: str
    top_k: int


def test_resolve_eval_query_mode_defaults_to_standard() -> None:
    assert resolve_eval_query_mode(None, {}) == "standard"


def test_resolve_eval_query_mode_uses_env_fallback() -> None:
    assert (
        resolve_eval_query_mode(
            None,
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "discorag"
    )


def test_resolve_eval_query_mode_cli_value_wins_over_env() -> None:
    assert (
        resolve_eval_query_mode(
            "standard",
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "standard"
    )


@pytest.mark.parametrize("value", ["rerank", "", " standard "])
def test_resolve_eval_query_mode_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match="Unsupported eval query mode"):
        resolve_eval_query_mode(None, {"RAGFLOW_LITE_EVAL_QUERY_MODE": value})


def test_resolve_eval_query_mode_rejects_unknown_cli_value() -> None:
    with pytest.raises(ValueError, match="Unsupported eval query mode"):
        resolve_eval_query_mode("rerank", {})


def test_build_eval_query_payload_includes_run_level_mode() -> None:
    payload = build_eval_query_payload(
        _Case(question="What matters?", top_k=6),
        query_mode="discorag",
    )

    assert payload == {
        "query": "What matters?",
        "top_k": 6,
        "mode": "discorag",
    }
