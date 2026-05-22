from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("deepeval")

from deepeval.test_case import LLMTestCase  # noqa: E402
from eval_support import (  # noqa: E402
    DEEPEVAL_CASE_CONCURRENCY_ENV_VAR,
    RAG_EVAL_CASES,
    RagEvalCase,
    _case_from_golden_payload,
    attach_eval_case_failure_snapshot,
    bounded_deepeval_case_workers,
    build_deepeval_judge_model,
    build_metrics_for_case,
    build_rag_test_case,
    build_reference_based_metrics,
    build_triad_metrics,
    ensure_rag_eval_cases_use_markdown_fixtures,
    eval_case_failure_snapshot,
    resolve_deepeval_case_concurrency,
    run_deepeval_cases_concurrently,
)

_JUDGE_MODEL_ENV = {
    "DEEPSEEK_API_KEY": "judge-real",
    "DEEPEVAL_MODEL": "deepseek-v4-flash",
    "DEEPEVAL_BASE_URL": "https://api.deepseek.com",
}

_EXPECTED_EVAL_SOURCE_FILES = {
    "microrag-private-bootstrap-snapshot": 20,
}


def _build_judge_model():
    return build_deepeval_judge_model(_JUDGE_MODEL_ENV)


def _metric_names(metrics: list[object]) -> list[str]:
    return [metric.__class__.__name__ for metric in metrics]


def _runner_case(name: str) -> RagEvalCase:
    return RagEvalCase(
        name=name,
        document_fixture="sample.md",
        question=f"{name} question",
    )


def test_resolve_deepeval_case_concurrency_defaults_to_twenty() -> None:
    assert resolve_deepeval_case_concurrency(None, {}) == 20


def test_resolve_deepeval_case_concurrency_prefers_cli_value() -> None:
    assert (
        resolve_deepeval_case_concurrency(
            7,
            {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: "11"},
        )
        == 7
    )


def test_resolve_deepeval_case_concurrency_uses_env_fallback() -> None:
    assert (
        resolve_deepeval_case_concurrency(
            None,
            {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: "13"},
        )
        == 13
    )


@pytest.mark.parametrize(
    ("cli_value", "env"),
    [
        (0, {}),
        (-1, {}),
        ("", {}),
        ("not-an-int", {}),
        (None, {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: ""}),
        (None, {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: "0"}),
        (None, {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: "-3"}),
        (None, {DEEPEVAL_CASE_CONCURRENCY_ENV_VAR: "not-an-int"}),
    ],
)
def test_resolve_deepeval_case_concurrency_rejects_invalid_values(
    cli_value: int | str | None,
    env: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        resolve_deepeval_case_concurrency(cli_value, env)


def test_bounded_deepeval_case_workers_caps_configured_concurrency() -> None:
    assert bounded_deepeval_case_workers(20, case_count=3) == 3
    assert bounded_deepeval_case_workers(5, case_count=20) == 5
    assert bounded_deepeval_case_workers(20, case_count=0) == 0


def test_run_deepeval_cases_concurrently_preserves_input_order() -> None:
    cases = [
        _runner_case("slow"),
        _runner_case("fast"),
        _runner_case("middle"),
    ]

    def evaluate_case(case: RagEvalCase) -> dict[str, object]:
        delays = {"slow": 0.03, "fast": 0.0, "middle": 0.01}
        time.sleep(delays[case.name])
        return {"case": case.name}

    results = run_deepeval_cases_concurrently(
        cases,
        configured_concurrency=3,
        evaluate_case=evaluate_case,
    )

    assert [result.case_name for result in results] == ["slow", "fast", "middle"]
    assert [result.snapshot for result in results] == [
        {"case": "slow"},
        {"case": "fast"},
        {"case": "middle"},
    ]
    assert [result.failed for result in results] == [False, False, False]


def test_run_deepeval_cases_concurrently_records_multiple_failures() -> None:
    cases = [
        _runner_case("first"),
        _runner_case("second"),
        _runner_case("third"),
    ]

    def evaluate_case(case: RagEvalCase) -> dict[str, object]:
        if case.name in {"first", "third"}:
            raise AssertionError(f"{case.name} failed")
        return {"case": case.name}

    results = run_deepeval_cases_concurrently(
        cases,
        configured_concurrency=3,
        evaluate_case=evaluate_case,
    )

    failures = [result for result in results if result.failed]

    assert [result.case_name for result in results] == ["first", "second", "third"]
    assert [(failure.case_name, failure.failure_type) for failure in failures] == [
        ("first", "AssertionError"),
        ("third", "AssertionError"),
    ]
    assert [failure.failure_message for failure in failures] == [
        "first failed",
        "third failed",
    ]
    assert results[1].snapshot == {"case": "second"}


def test_run_deepeval_cases_concurrently_preserves_failure_snapshot() -> None:
    cases = [_runner_case("scored-failure")]
    snapshot = {
        "case": "scored-failure",
        "metrics": {
            "AnswerRelevancyMetric": {
                "score": 0.4,
                "reason": "below threshold",
            }
        },
    }

    def evaluate_case(case: RagEvalCase) -> dict[str, object]:
        exc = AssertionError(f"{case.name} failed")
        attach_eval_case_failure_snapshot(exc, snapshot)
        raise exc

    results = run_deepeval_cases_concurrently(
        cases,
        configured_concurrency=1,
        evaluate_case=evaluate_case,
    )

    assert len(results) == 1
    assert results[0].case_name == "scored-failure"
    assert results[0].failed is True
    assert results[0].snapshot == snapshot
    assert results[0].failure_type == "AssertionError"
    assert results[0].failure_message == "scored-failure failed"


def test_evaluate_rag_case_preserves_metrics_after_assertion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_rag_deepeval

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self) -> dict[str, object]:
            return {
                "answer": "A populated answer.",
                "contexts": [
                    {
                        "document_id": "doc-1",
                        "text": "Source context",
                        "metadata": {"filename": "source.md"},
                    }
                ],
            }

    class FakeClient:
        def post(self, path: str, *, json: dict[str, object]) -> FakeResponse:
            assert path == "/api/v0/queries"
            assert json["mode"] == "discorag"
            return FakeResponse()

    class PopulatedMetric:
        score: float | None = None
        reason: str | None = None

    metric = PopulatedMetric()

    def fake_build_metrics_for_case(*args: object, **kwargs: object) -> list[object]:
        return [metric]

    def fake_assert_test(*args: object, **kwargs: object) -> None:
        metric.score = 0.42
        metric.reason = "judge populated before failure"
        raise AssertionError("metric threshold failed")

    monkeypatch.setattr(
        test_rag_deepeval,
        "build_metrics_for_case",
        fake_build_metrics_for_case,
    )
    monkeypatch.setattr(test_rag_deepeval, "assert_test", fake_assert_test)

    with pytest.raises(AssertionError, match="metric threshold failed") as exc_info:
        test_rag_deepeval._evaluate_rag_case(
            client=FakeClient(),
            case=_runner_case("scored-failure"),
            query_mode="discorag",
            judge_model=object(),
        )

    snapshot = eval_case_failure_snapshot(exc_info.value)

    assert snapshot is not None
    assert snapshot["case"] == "scored-failure"
    assert snapshot["metrics"] == {
        "PopulatedMetric": {
            "score": 0.42,
            "reason": "judge populated before failure",
        }
    }


def test_build_rag_test_case_with_expected_output() -> None:
    case = RagEvalCase(
        name="sample-txt",
        document_fixture="sample.txt",
        question="这个项目支持什么文件类型",
        expected_output="项目支持 txt 和 md 文件类型的导入。",
    )
    assert case.has_reference is True

    test_case = build_rag_test_case(
        case=case,
        actual_output="项目支持 txt 和 md 文件类型的导入。",
        retrieval_context=[
            "ragflow-lite V0 当前支持 txt 和 md 文件类型的导入。",
        ],
    )

    assert isinstance(test_case, LLMTestCase)
    assert test_case.input == case.question
    assert test_case.actual_output == "项目支持 txt 和 md 文件类型的导入。"
    assert test_case.expected_output == case.expected_output
    assert test_case.retrieval_context == [
        "ragflow-lite V0 当前支持 txt 和 md 文件类型的导入。",
    ]


def test_build_rag_test_case_without_expected_output() -> None:
    case = RagEvalCase(
        name="sample-md",
        document_fixture="sample.md",
        question="how to run this minimal RAG",
    )
    assert case.has_reference is False

    test_case = build_rag_test_case(
        case=case,
        actual_output="Run uvicorn.",
        retrieval_context=["Run the server with uvicorn."],
    )

    assert isinstance(test_case, LLMTestCase)
    assert test_case.input == case.question
    assert test_case.retrieval_context == ["Run the server with uvicorn."]


def test_build_rag_test_case_normalizes_citation_noise_and_json_prefix() -> None:
    case = RagEvalCase(
        name="sample-pdf",
        document_fixture="sample.pdf",
        question="PDF test",
    )

    test_case = build_rag_test_case(
        case=case,
        actual_output=(
            'JSON: "The PDF page<cite:1> contains the text Hello from PDF test '
            'page [1]."'
        ),
        retrieval_context=["Hello from PDF test page"],
    )

    assert isinstance(test_case, LLMTestCase)
    assert (
        test_case.actual_output
        == "The PDF page contains the text Hello from PDF test page."
    )


def test_triad_metrics_are_referenceless() -> None:
    judge_model = _build_judge_model()
    triad = build_triad_metrics(model=judge_model)

    assert _metric_names(triad) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualRelevancyMetric",
    ]
    assert all(m.model is judge_model for m in triad)


def test_reference_based_metrics_are_two() -> None:
    judge_model = _build_judge_model()
    ref_based = build_reference_based_metrics(model=judge_model)

    assert _metric_names(ref_based) == [
        "ContextualPrecisionMetric",
        "ContextualRecallMetric",
    ]
    assert all(m.model is judge_model for m in ref_based)


def test_build_metrics_for_case_returns_triad_only_when_no_reference() -> None:
    judge_model = _build_judge_model()
    case = RagEvalCase(
        name="no-ref",
        document_fixture="sample.md",
        question="test",
    )

    metrics = build_metrics_for_case(case, model=judge_model)
    assert _metric_names(metrics) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualRelevancyMetric",
    ]


def test_build_metrics_for_case_returns_all_five_for_standard_reference_case() -> None:
    judge_model = _build_judge_model()
    case = RagEvalCase(
        name="with-ref",
        document_fixture="sample.txt",
        question="test",
        expected_output="reference answer",
    )

    metrics = build_metrics_for_case(
        case,
        model=judge_model,
        query_mode="standard",
    )
    assert _metric_names(metrics) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualRelevancyMetric",
        "ContextualPrecisionMetric",
        "ContextualRecallMetric",
    ]


def test_build_metrics_for_case_omits_contextual_relevancy_for_discorag_reference_case() -> (
    None
):
    judge_model = _build_judge_model()
    case = RagEvalCase(
        name="with-ref",
        document_fixture="sample.txt",
        question="test",
        expected_output="reference answer",
    )

    metrics = build_metrics_for_case(
        case,
        model=judge_model,
        query_mode="discorag",
    )

    assert _metric_names(metrics) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualPrecisionMetric",
        "ContextualRecallMetric",
    ]


def test_build_metrics_for_case_omits_contextual_relevancy_for_discorag_no_reference_case() -> (
    None
):
    judge_model = _build_judge_model()
    case = RagEvalCase(
        name="no-ref",
        document_fixture="sample.md",
        question="test",
    )

    metrics = build_metrics_for_case(
        case,
        model=judge_model,
        query_mode="discorag",
    )

    assert _metric_names(metrics) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
    ]


def test_seed_dataset_tracks_generated_eval_docs_with_references() -> None:
    fixture_counts: dict[str, int] = {}
    for case in RAG_EVAL_CASES:
        fixture = case.corpus_fixture or case.document_fixture
        fixture_counts[fixture] = fixture_counts.get(fixture, 0) + 1

    assert len(RAG_EVAL_CASES) == 20
    assert fixture_counts == _EXPECTED_EVAL_SOURCE_FILES
    assert all(case.has_reference for case in RAG_EVAL_CASES)


def test_seed_dataset_uses_unique_names_and_non_empty_questions() -> None:
    names = [case.name for case in RAG_EVAL_CASES]

    assert len(names) == len(set(names))
    assert all(case.question.strip() for case in RAG_EVAL_CASES)
    assert all(
        case.expected_output and case.expected_output.strip() for case in RAG_EVAL_CASES
    )


def test_seed_dataset_uses_markdown_fixtures_only() -> None:
    assert {case.corpus_fixture for case in RAG_EVAL_CASES} == {
        "microrag-private-bootstrap-snapshot"
    }
    assert {Path(case.document_fixture).suffix for case in RAG_EVAL_CASES} == {".md"}


def test_private_bootstrap_cases_use_snapshot_corpus_fixture() -> None:
    multi_doc_cases = [
        case for case in RAG_EVAL_CASES if len(case.required_authoritative_sources) >= 2
    ]

    assert multi_doc_cases
    assert all(case.uses_corpus_fixture for case in RAG_EVAL_CASES)
    assert all(
        case.corpus_fixture == "microrag-private-bootstrap-snapshot"
        for case in RAG_EVAL_CASES
    )
    assert all(
        case.document_fixture == "microrag-private-bootstrap.md"
        for case in RAG_EVAL_CASES
    )
    assert {
        case.answerability
        for case in RAG_EVAL_CASES
        if case.name in {"private-bootstrap-017", "private-bootstrap-018"}
    } == {"unanswerable"}


def test_case_loader_preserves_private_bootstrap_metadata() -> None:
    case = _case_from_golden_payload(
        {
            "name": "multi-doc",
            "input": "How do eval contracts and API contracts interact?",
            "expected_output": "Use both active contracts.",
            "sourceFile": "microrag-private-bootstrap.md",
            "additionalMetadata": {
                "corpus_fixture": "microrag-private-bootstrap-snapshot",
                "document_fixture": "microrag-private-bootstrap.md",
                "top_k": 6,
                "required_authoritative_sources": [
                    "tests/evals/CONTRACTS.md",
                    "src/ragflow_lite/api/CONTRACTS.md",
                ],
                "distractor_sources": [
                    "docs/superpowers/plans/2026-05-19-plan.md",
                ],
                "answerability": "answerable",
            },
        },
        index=1,
    )

    assert case.uses_corpus_fixture is True
    assert case.corpus_fixture == "microrag-private-bootstrap-snapshot"
    assert case.document_fixture == "microrag-private-bootstrap.md"
    assert case.required_authoritative_sources == (
        "tests/evals/CONTRACTS.md",
        "src/ragflow_lite/api/CONTRACTS.md",
    )
    assert case.distractor_sources == ("docs/superpowers/plans/2026-05-19-plan.md",)


def test_private_bootstrap_snapshot_manifest_paths_are_readable() -> None:
    from test_rag_deepeval import _fixture_documents_for_case

    fixture_documents_dir = (
        Path(__file__).resolve().parents[1] / "fixtures" / "documents"
    )
    fixture_names = _fixture_documents_for_case(
        fixture_documents_dir=fixture_documents_dir,
        case=RAG_EVAL_CASES[0],
    )

    assert fixture_names
    assert fixture_names[0].startswith("microrag-private-bootstrap-snapshot/")
    assert all(
        (fixture_documents_dir / fixture_name).is_file()
        for fixture_name in fixture_names
    )


def test_markdown_fixture_validation_rejects_non_markdown_cases() -> None:
    with pytest.raises(RuntimeError, match="markdown fixtures only"):
        ensure_rag_eval_cases_use_markdown_fixtures(
            [
                RagEvalCase(
                    name="pdf-case",
                    document_fixture="sample.pdf",
                    question="PDF test",
                    expected_output="answer",
                )
            ]
        )


def test_build_deepeval_judge_model_uses_explicit_openai_compatible_endpoint() -> None:
    judge_model = _build_judge_model()

    assert judge_model.name == "deepseek-v4-flash"
    assert judge_model.base_url == "https://api.deepseek.com"
    assert judge_model.generation_kwargs == {"reasoning_effort": "high"}
