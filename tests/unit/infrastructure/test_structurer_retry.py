from __future__ import annotations

from ragflow_lite.domain.errors.exceptions import ProcessingError
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptsExhaustedError,
    StructurerAttemptState,
    build_validation_repair_messages,
    is_timeout_error,
)


def test_build_validation_repair_messages_appends_short_feedback_only() -> None:
    messages = build_validation_repair_messages(
        instructions="Return graph JSON.",
        input_text="query: q\n\nCHUNK[1] id=chunk_a\ntext: Alpha",
        invalid_output='{"relations": [{"target_chunk_id": "missing"}]}',
        validation_error='target_chunk_id "missing" is unknown',
    )
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"].startswith("query: q")
    assert messages[2]["content"].startswith('{"relations"')
    assert "target_chunk_id" in messages[3]["content"]
    assert "query: q" not in messages[3]["content"]
    assert "Regenerate one complete JSON object" in messages[3]["content"]
    assert "Do not output a patch" in messages[3]["content"]


def test_structurer_attempt_state_records_validation_failure() -> None:
    state = StructurerAttemptState(stage="blueprint", max_attempts=2)
    state.record_failure("validation_error", "missing chunk role")
    assert state.attempts == 1
    assert state.repair_count == 1
    assert state.timeout_count == 0
    assert state.last_failure_type == "validation_error"


def test_structurer_attempt_state_records_timeout_failure() -> None:
    state = StructurerAttemptState(stage="graph", max_attempts=2)
    state.record_failure("timeout", "request timed out")
    assert state.attempts == 1
    assert state.repair_count == 0
    assert state.timeout_count == 1
    assert state.last_failure_type == "timeout"


def test_structurer_attempt_state_records_success() -> None:
    state = StructurerAttemptState(stage="rst_extraction", max_attempts=2)
    state.record_failure("validation_error", "bad")
    state.record_success_attempt()
    assert state.attempts == 2
    assert state.repair_count == 1


def test_is_timeout_error_recognizes_timeout() -> None:
    assert is_timeout_error(TimeoutError("timed out")) is True
    assert is_timeout_error(Exception("request timed out")) is True
    assert is_timeout_error(Exception("ConnectionTimeoutError")) is True


def test_is_timeout_error_rejects_non_timeout() -> None:
    assert is_timeout_error(ProcessingError("validation failed")) is False
    assert is_timeout_error(ValueError("bad input")) is False


def test_structurer_attempt_state_builds_exhausted_error() -> None:
    state = StructurerAttemptState(stage="blueprint", max_attempts=2)
    state.record_failure("validation_error", "missing role")
    state.record_failure("validation_error", "still missing role")

    error = state.exhausted_error()

    assert isinstance(error, StructurerAttemptsExhaustedError)
    assert error.stage == "blueprint"
    assert error.failure_type == "validation_error"
    assert error.attempts == 2
    assert error.max_attempts == 2
    assert "still missing role" in error.message
    assert "failed after 2 attempts" in str(error)


def test_structurer_exhausted_error_safe_metadata() -> None:
    error = StructurerAttemptsExhaustedError(
        stage="inter_chunk_graph",
        failure_type="timeout",
        attempts=2,
        max_attempts=2,
        message="timeout",
    )

    assert error.safe_metadata() == {
        "stage": "inter_chunk_graph",
        "error_type": "StructurerAttemptsExhaustedError",
        "failure_type": "timeout",
        "attempts": 2,
        "max_attempts": 2,
        "message": "timeout",
        "user_visible": True,
    }
