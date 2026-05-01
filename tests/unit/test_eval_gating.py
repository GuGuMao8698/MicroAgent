from __future__ import annotations

import pytest
from eval_support import is_live_infinity_enabled, validate_deepeval_env


def test_live_infinity_enabled_for_live_or_deepeval_markers() -> None:
    assert is_live_infinity_enabled({"live_infinity"}, run_live_infinity=False) is True
    assert is_live_infinity_enabled({"deepeval"}, run_live_infinity=False) is True


def test_live_infinity_disabled_without_marker_or_option() -> None:
    assert is_live_infinity_enabled(set(), run_live_infinity=False) is False


def test_validate_deepeval_env_rejects_placeholder_values() -> None:
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        validate_deepeval_env(
            {
                "DEEPSEEK_API_KEY": "test-deepseek-api-key",
                "ARK_API_KEY": "ark-real",
                "ARK_EMBEDDING_MODEL": "ep-real",
            }
        )
