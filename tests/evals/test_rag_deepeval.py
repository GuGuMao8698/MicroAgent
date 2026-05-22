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

try:
    from private_bootstrap_goldens import load_manifest  # noqa: E402
except ModuleNotFoundError:
    from evals.private_bootstrap_goldens import load_manifest  # noqa: E402
from eval_support import (  # noqa: E402
    RAG_EVAL_CASES,
    EvalCaseRunResult,
    EvalQueryMode,
    RagEvalCase,
    attach_eval_case_failure_snapshot,
    bounded_deepeval_case_workers,
    build_deepeval_judge_model,
    build_eval_query_payload,
    build_metrics_for_case,
    build_rag_test_case,
    resolve_deepeval_case_concurrency,
    resolve_eval_query_mode,
    run_deepeval_cases_concurrently,
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
    fixture_path = fixture_documents_dir / fixture_name
    upload_name = fixture_name.replace("/", "__")
    return client.post(
        "/api/v0/documents",
        files={
            "file": (
                upload_name,
                fixture_path.read_bytes(),
                _CONTENT_TYPES[suffix],
            )
        },
        headers={"Idempotency-Key": _unique_key()},
    )


def _fixture_documents_for_case(
    *,
    fixture_documents_dir: Path,
    case: RagEvalCase,
) -> list[str]:
    if case.corpus_fixture is None:
        return [case.document_fixture]

    manifest_root = fixture_documents_dir / case.corpus_fixture
    return [
        f"{case.corpus_fixture}/{entry.snapshot_path}"
        for entry in load_manifest(manifest_root)
    ]


def _fixture_documents_for_cases(
    *,
    fixture_documents_dir: Path,
    cases: list[RagEvalCase],
) -> list[str]:
    fixture_names: list[str] = []
    seen: set[str] = set()
    for case in cases:
        for fixture_name in _fixture_documents_for_case(
            fixture_documents_dir=fixture_documents_dir,
            case=case,
        ):
            if fixture_name in seen:
                continue
            seen.add(fixture_name)
            fixture_names.append(fixture_name)
    return fixture_names


def _upload_fixture_documents(
    client: Any,
    fixture_documents_dir: Path,
    fixture_names: list[str],
) -> list[dict[str, Any]]:
    document_statuses = []
    for fixture_name in fixture_names:
        upload_response = _upload_fixture_document(
            client,
            fixture_documents_dir,
            fixture_name,
        )
        assert upload_response.status_code == 202
        final_payload = _wait_for_document_terminal_state(
            client, upload_response.json()["document_id"]
        )
        assert final_payload["status"] == "indexed"
        document_statuses.append(final_payload)
    return document_statuses


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


def _evaluate_rag_case(
    *,
    client: Any,
    case: RagEvalCase,
    query_mode: EvalQueryMode,
    judge_model: Any,
) -> dict[str, Any]:
    query_response = client.post(
        "/api/v0/queries",
        json=build_eval_query_payload(case, query_mode=query_mode),
    )
    assert query_response.status_code == 200, (
        f"{case.name} query returned HTTP {query_response.status_code}: "
        f"{query_response.text}"
    )
    payload = query_response.json()
    assert payload["answer"], f"{case.name} query returned an empty answer."
    assert payload["contexts"], f"{case.name} query returned no contexts."

    test_case = build_rag_test_case(
        case=case,
        actual_output=payload["answer"],
        retrieval_context=[
            _retrieval_context_for_deepeval(context) for context in payload["contexts"]
        ],
    )

    metrics = build_metrics_for_case(
        case,
        model=judge_model,
        query_mode=query_mode,
    )

    def build_snapshot() -> dict[str, Any]:
        return {
            "case": case.name,
            "has_reference": case.has_reference,
            "answerability": case.answerability,
            "required_authoritative_sources": list(case.required_authoritative_sources),
            "distractor_sources": list(case.distractor_sources),
            "context_count": len(payload["contexts"]),
            "retrieved_sources": sorted(
                {
                    context.get("metadata", {}).get("filename")
                    for context in payload["contexts"]
                    if context.get("metadata", {}).get("filename")
                }
            ),
            "answer_length": len(payload["answer"]),
            "metrics": {
                m.__class__.__name__: {"score": m.score, "reason": m.reason}
                for m in metrics
            },
        }

    try:
        assert_test(test_case, metrics=metrics)
    except AssertionError as exc:
        attach_eval_case_failure_snapshot(exc, build_snapshot())
        raise

    return build_snapshot()


def _case_snapshot_from_result(result: EvalCaseRunResult) -> dict[str, Any] | None:
    if result.snapshot is None:
        return None
    if not result.failed:
        return result.snapshot
    return {
        **result.snapshot,
        "failure": {
            "type": result.failure_type or "UnknownFailure",
            "message": result.failure_message or "",
        },
    }


def _failure_snapshots(results: list[EvalCaseRunResult]) -> list[dict[str, str]]:
    return [
        {
            "case": result.case_name,
            "failure_type": result.failure_type or "UnknownFailure",
            "message": result.failure_message or "",
        }
        for result in results
        if result.failed
    ]


def _raise_for_case_failures(failures: list[dict[str, str]]) -> None:
    if not failures:
        return

    lines = [
        f"- {failure['case']}: {failure['failure_type']}: {failure['message']}"
        for failure in failures
    ]
    raise AssertionError(
        f"RAG eval failed for {len(failures)} case(s):\n" + "\n".join(lines)
    )


def test_single_turn_rag_eval_produces_quality_snapshot(
    client: Any,
    fixture_documents_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    vector_index = client.app.state.services.ingestion_pipeline.vector_index
    assert vector_index._client.__class__.__name__ != "FakeInfinityClient"

    fixture_names = _fixture_documents_for_cases(
        fixture_documents_dir=fixture_documents_dir,
        cases=RAG_EVAL_CASES,
    )
    document_statuses = _upload_fixture_documents(
        client,
        fixture_documents_dir,
        fixture_names,
    )

    query_mode = resolve_eval_query_mode(
        request.config.getoption("--query-mode"),
        os.environ,
    )
    judge_model = build_deepeval_judge_model(os.environ)
    case_concurrency = resolve_deepeval_case_concurrency(
        request.config.getoption("--deepeval-case-concurrency"),
        os.environ,
    )
    effective_case_workers = bounded_deepeval_case_workers(
        case_concurrency,
        case_count=len(RAG_EVAL_CASES),
    )

    def evaluate_case(case: RagEvalCase) -> dict[str, Any]:
        return _evaluate_rag_case(
            client=client,
            case=case,
            query_mode=query_mode,
            judge_model=judge_model,
        )

    case_results = run_deepeval_cases_concurrently(
        RAG_EVAL_CASES,
        configured_concurrency=case_concurrency,
        evaluate_case=evaluate_case,
    )
    case_snapshots = [
        snapshot
        for result in case_results
        if (snapshot := _case_snapshot_from_result(result)) is not None
    ]
    case_failures = _failure_snapshots(case_results)

    snapshot = {
        "corpus": {
            "fixture_count": len(fixture_names),
            "fixture_root": RAG_EVAL_CASES[0].corpus_fixture,
            "document_count": len(document_statuses),
            "document_statuses": [
                {
                    "document_id": document["document_id"],
                    "filename": document["filename"],
                    "status": document["status"],
                }
                for document in document_statuses
            ],
        },
        "e2e": {
            "query_mode": query_mode,
            "case_concurrency": {
                "configured": case_concurrency,
                "effective_workers": effective_case_workers,
            },
            "case_count": len(RAG_EVAL_CASES),
            "completed_case_count": len(case_snapshots),
            "failed_case_count": len(case_failures),
            "cases": case_snapshots,
            "failures": case_failures,
        },
    }

    print(
        "\n=== RAG Quality Snapshot ===\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2)
    )
    _raise_for_case_failures(case_failures)


def _retrieval_context_for_deepeval(context: dict[str, Any]) -> str:
    metadata = context.get("metadata", {})
    filename = metadata.get("filename") if isinstance(metadata, dict) else None
    document_id = context.get("document_id")
    source = filename or "unknown"
    return f"Source: {source}\nDocument-ID: {document_id}\n\n{context['text']}"
