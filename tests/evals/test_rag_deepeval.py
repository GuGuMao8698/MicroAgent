from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

pytest.importorskip("deepeval")

from deepeval import assert_test  # noqa: E402
from eval_support import (  # noqa: E402
    RAG_EVAL_CASES,
    build_deepeval_judge_model,
    build_metrics_for_case,
    build_rag_test_case,
)

_CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}

pytestmark = [pytest.mark.live_infinity, pytest.mark.deepeval]


def _unique_key() -> str:
    return f"key-{uuid4().hex}"


def _upload_fixture_document(
    client: Any,
    fixture_documents_dir: Path,
    fixture_name: str,
) -> Any:
    suffix = Path(fixture_name).suffix
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                fixture_name,
                (fixture_documents_dir / fixture_name).read_bytes(),
                _CONTENT_TYPES[suffix],
            )
        },
        headers={"Idempotency-Key": _unique_key()},
    )


def _wait_for_document_terminal_state(
    client: Any,
    document_id: str,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/v0/documents/{document_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in {"indexed", "failed"}:
            return payload
        time.sleep(0.1)

    raise AssertionError(
        f"Document {document_id} did not reach terminal status. Last payload: {last_payload}"
    )


@pytest.mark.parametrize("case", RAG_EVAL_CASES, ids=lambda c: c.name)
def test_single_turn_rag_eval_produces_quality_snapshot(
    client: Any,
    fixture_documents_dir: Path,
    case: Any,
) -> None:
    vector_index = client.app.state.services.ingestion_pipeline.vector_index
    assert vector_index._client.__class__.__name__ != "FakeInfinityClient"

    upload_response = _upload_fixture_document(
        client,
        fixture_documents_dir,
        case.document_fixture,
    )
    assert upload_response.status_code == 202

    final_payload = _wait_for_document_terminal_state(
        client, upload_response.json()["document_id"]
    )
    assert final_payload["status"] == "indexed"

    query_response = client.post(
        "/api/v0/queries",
        json={"query": case.question, "top_k": case.top_k},
    )
    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["answer"]
    assert payload["contexts"]

    test_case = build_rag_test_case(
        case=case,
        actual_output=payload["answer"],
        retrieval_context=[context["text"] for context in payload["contexts"]],
    )

    judge_model = build_deepeval_judge_model(os.environ)
    metrics = build_metrics_for_case(case, model=judge_model)

    assert_test(test_case, metrics=metrics)

    snapshot = {
        "metrics": {
            m.__class__.__name__: {"score": m.score, "reason": m.reason}
            for m in metrics
        },
        "e2e": {
            "case": case.name,
            "has_reference": case.has_reference,
            "document_status": final_payload["status"],
            "context_count": len(payload["contexts"]),
            "answer_length": len(payload["answer"]),
        },
    }

    print(
        "\n=== RAG Quality Snapshot ===\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2)
    )
