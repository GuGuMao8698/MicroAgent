"""Provider-neutral retry helpers for structurer validation-repair and timeout retry."""

from __future__ import annotations

from dataclasses import dataclass, field

from ragflow_lite.domain.errors.exceptions import ProcessingError


class StructurerAttemptsExhaustedError(ProcessingError):
    """Raised when a structurer stage exhausts its retry budget."""

    def __init__(
        self,
        *,
        stage: str,
        failure_type: str,
        attempts: int,
        max_attempts: int,
        message: str,
    ) -> None:
        self.stage = stage
        self.failure_type = failure_type
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.message = message
        super().__init__(
            f"{stage} structurer failed after {attempts} attempts: {message}"
        )

    def safe_metadata(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "error_type": type(self).__name__,
            "failure_type": self.failure_type,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "message": self.message,
            "user_visible": True,
        }


@dataclass
class StructurerAttemptState:
    """Tracks attempt counts and failure summaries for a single structurer stage."""

    stage: str
    max_attempts: int
    attempts: int = 0
    repair_count: int = 0
    timeout_count: int = 0
    last_failure_type: str | None = None
    failure_summaries: list[str] = field(default_factory=list)

    def record_failure(self, failure_type: str, message: str) -> None:
        self.attempts += 1
        self.last_failure_type = failure_type
        self.failure_summaries.append(f"{failure_type}: {message}")
        if failure_type == "validation_error":
            self.repair_count += 1
        elif failure_type == "timeout":
            self.timeout_count += 1

    def record_success_attempt(self) -> None:
        self.attempts += 1

    def exhausted_error(self) -> StructurerAttemptsExhaustedError:
        failure_type = self.last_failure_type or "validation_error"
        message = self.failure_summaries[-1] if self.failure_summaries else "unknown"
        return StructurerAttemptsExhaustedError(
            stage=self.stage,
            failure_type=failure_type,
            attempts=self.attempts,
            max_attempts=self.max_attempts,
            message=message,
        )


def build_validation_repair_messages(
    *,
    instructions: str,
    input_text: str,
    invalid_output: str,
    validation_error: str,
) -> list[dict[str, str]]:
    """Build a 4-turn repair conversation: system, user, assistant, user-feedback.

    The feedback turn omits the full input to avoid inflating token cost;
    it only contains the validation error and a regeneration instruction.
    """
    feedback = (
        "Your previous JSON is invalid.\n\n"
        f"Validation error:\n- {validation_error}\n\n"
        "Regenerate one complete JSON object. Do not output a patch. "
        "Do not include markdown or prose outside the JSON object."
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
        {"role": "assistant", "content": invalid_output},
        {"role": "user", "content": feedback},
    ]


def is_timeout_error(exc: Exception) -> bool:
    """Return True if *exc* looks like a timeout-related error."""
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return (
        isinstance(exc, TimeoutError)
        or "timeout" in name
        or "timedout" in name
        or "timed out" in message
        or "timeout" in message
    )
