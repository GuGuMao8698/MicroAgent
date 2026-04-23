from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("deepeval")

from deepeval.test_case import LLMTestCase  # noqa: E402
from eval_support import (  # noqa: E402
    RAG_EVAL_CASES,
    RagEvalCase,
    build_deepeval_judge_model,
    build_metrics_for_case,
    build_rag_test_case,
    build_reference_based_metrics,
    build_triad_metrics,
    ensure_rag_eval_cases_use_markdown_fixtures,
)

_JUDGE_MODEL_ENV = {
    "ARK_API_KEY": "judge-real",
    "DEEPEVAL_MODEL": "ep-20260423004926-v99zw",
    "DEEPEVAL_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
}

_EXPECTED_EVAL_SOURCE_FILES = {
    "Best Practices for Claude Code.md": 10,
    "CodexBestpractices.md": 10,
    "Faithfulness.md": 10,
    "MinerU_markdown_603260_20260417_2LSZ.md": 10,
    "MinerU_markdown_中华人民共和国劳动法.md": 10,
    "MinerU_markdown_附件1：《期货公司监督管理办法（征求意见稿）》.md": 10,
}


def _build_judge_model():
    return build_deepeval_judge_model(_JUDGE_MODEL_ENV)


def _metric_names(metrics: list[object]) -> list[str]:
    return [metric.__class__.__name__ for metric in metrics]


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


def test_build_metrics_for_case_returns_all_five_when_has_reference() -> None:
    judge_model = _build_judge_model()
    case = RagEvalCase(
        name="with-ref",
        document_fixture="sample.txt",
        question="test",
        expected_output="reference answer",
    )

    metrics = build_metrics_for_case(case, model=judge_model)
    assert _metric_names(metrics) == [
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "ContextualRelevancyMetric",
        "ContextualPrecisionMetric",
        "ContextualRecallMetric",
    ]


def test_seed_dataset_tracks_generated_eval_docs_with_references() -> None:
    fixture_counts: dict[str, int] = {}
    for case in RAG_EVAL_CASES:
        fixture_counts[case.document_fixture] = (
            fixture_counts.get(case.document_fixture, 0) + 1
        )

    assert len(RAG_EVAL_CASES) == 60
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
    assert {Path(case.document_fixture).suffix for case in RAG_EVAL_CASES} == {".md"}


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

    assert judge_model.name == "ep-20260423004926-v99zw"
    assert judge_model.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert judge_model.generation_kwargs == {"reasoning_effort": "medium"}
