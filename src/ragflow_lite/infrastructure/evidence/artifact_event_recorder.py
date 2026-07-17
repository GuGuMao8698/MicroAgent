from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

REQUIRED_EVENT_NAMES = frozenset(
    {
        "artifact_build_started",
        "artifact_build_failed",
        "artifact_projection_started",
        "artifact_projection_failed",
        "artifact_projection_repair_required",
        "artifact_projection_repair_finished",
        "artifact_delete_started",
        "artifact_delete_failed",
        "artifact_delete_finished",
        "active_artifact_switched",
        "psi_auxiliary_started",
        "psi_auxiliary_degraded",
        "psi_auxiliary_fallback",
        "psi_auxiliary_failed",
        "psi_auxiliary_finished",
    }
)

_ARTIFACT_EVENT_PREFIXES = ("artifact_", "active_artifact_", "psi_auxiliary_")
_ARTIFACT_LIFECYCLE_PREFIXES = ("artifact_", "active_artifact_")
_PSI_AUXILIARY_PREFIX = "psi_auxiliary_"


@dataclass(frozen=True, slots=True)
class ArtifactEvent:
    name: str
    payload: dict[str, Any]


class ArtifactEventRecorder(Protocol):
    def record(self, event: ArtifactEvent) -> None: ...


def validate_artifact_event(event: ArtifactEvent) -> None:
    if event.name not in REQUIRED_EVENT_NAMES:
        msg = f"unsupported artifact event: {event.name}"
        raise ValueError(msg)
    if event.name.startswith(_PSI_AUXILIARY_PREFIX) and not event.payload.get(
        "retrieval_pass_id"
    ):
        msg = "psi auxiliary event requires retrieval_pass_id"
        raise ValueError(msg)
    if event.name.startswith(_ARTIFACT_EVENT_PREFIXES):
        if not event.payload.get("document_id") and not event.payload.get(
            "retrieval_pass_id"
        ):
            msg = "artifact event requires stable owner identifiers: document_id or retrieval_pass_id"
            raise ValueError(msg)
    if event.name.startswith(_ARTIFACT_LIFECYCLE_PREFIXES) and not event.payload.get(
        "artifact_type"
    ):
        msg = "artifact lifecycle event requires artifact_type"
        raise ValueError(msg)


@dataclass(slots=True)
class InMemoryArtifactEventRecorder:
    events: list[ArtifactEvent] = field(default_factory=list)

    def record(self, event: ArtifactEvent) -> None:
        validate_artifact_event(event)
        self.events.append(event)
