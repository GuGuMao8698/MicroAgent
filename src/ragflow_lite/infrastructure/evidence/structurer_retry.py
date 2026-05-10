"""Provider-neutral retry helpers for structurer validation-repair and timeout retry."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StructurerAttemptState:
    """Tracks attempt counts and failure summaries for a single structurer stage."""

    stage: str
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

    def safe_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "structurer_attempts": self.attempts,
            "structurer_repair_count": self.repair_count,
            "structurer_timeout_count": self.timeout_count,
        }
        if self.last_failure_type is not None:
            metadata["structurer_last_failure_type"] = self.last_failure_type
        return metadata


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
