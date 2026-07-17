from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.evidence.artifact_event_recorder import (
    REQUIRED_EVENT_NAMES,
    ArtifactEvent,
    InMemoryArtifactEventRecorder,
)


def test_required_event_names_match_spec_contract() -> None:
    assert {
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
    }.issubset(REQUIRED_EVENT_NAMES)


def test_recorder_requires_stable_owner_identifiers() -> None:
    recorder = InMemoryArtifactEventRecorder()

    with pytest.raises(ValueError, match="document_id"):
        recorder.record(
            ArtifactEvent(
                name="artifact_build_started",
                payload={"artifact_type": "graph_evidence", "build_id": "build-1"},
            )
        )

    recorder.record(
        ArtifactEvent(
            name="artifact_build_started",
            payload={
                "document_id": "doc-1",
                "artifact_type": "graph_evidence",
                "build_id": "build-1",
            },
        )
    )

    assert recorder.events[0].name == "artifact_build_started"
    assert recorder.events[0].payload["document_id"] == "doc-1"


def test_artifact_lifecycle_events_require_artifact_type_but_psi_auxiliary_does_not() -> (
    None
):
    recorder = InMemoryArtifactEventRecorder()

    with pytest.raises(ValueError, match="artifact_type"):
        recorder.record(
            ArtifactEvent(
                name="artifact_projection_failed",
                payload={
                    "document_id": "doc-1",
                    "build_id": "build-1",
                    "projection_id": "projection-1",
                    "failure_code": "boom",
                    "failure_stage": "project",
                },
            )
        )

    recorder.record(
        ArtifactEvent(
            name="psi_auxiliary_started",
            payload={"retrieval_pass_id": "pass-1"},
        )
    )

    assert recorder.events[0].name == "psi_auxiliary_started"
    assert recorder.events[0].payload["retrieval_pass_id"] == "pass-1"


def test_psi_auxiliary_events_require_retrieval_pass_id() -> None:
    recorder = InMemoryArtifactEventRecorder()

    with pytest.raises(ValueError, match="retrieval_pass_id"):
        recorder.record(
            ArtifactEvent(
                name="psi_auxiliary_started",
                payload={"document_id": "doc-1"},
            )
        )
