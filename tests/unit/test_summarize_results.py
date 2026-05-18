from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from evals.summarize_results import (
    apply_query_mode_to_run_id,
    build_comparison_report,
    build_failed_results_report,
    build_metric_averages_report,
    build_results_summary,
    default_output_path,
    find_previous_summary_path,
    main,
    resolve_results_path,
)


def test_resolve_results_path_selects_latest_timestamped_export(tmp_path: Path) -> None:
    older = tmp_path / "20260421_224937"
    newer = tmp_path / "20260421_225500"
    ignored = tmp_path / "uploads"
    ignored.mkdir()
    (ignored / "doc.txt").write_text("not a deepeval export", encoding="utf-8")
    older.write_text('{"testCases": []}', encoding="utf-8")
    newer.write_text('{"testCases": []}', encoding="utf-8")

    resolved = resolve_results_path(tmp_path)

    assert resolved == newer


def test_apply_query_mode_to_run_id_appends_mode_once() -> None:
    assert apply_query_mode_to_run_id("20260518_170000", "standard") == (
        "20260518_170000.standard"
    )
    assert apply_query_mode_to_run_id("20260518_170000.standard", "standard") == (
        "20260518_170000.standard"
    )


def test_apply_query_mode_to_run_id_rejects_conflicting_mode() -> None:
    with pytest.raises(RuntimeError):
        apply_query_mode_to_run_id("20260518_170000.discorag", "standard")


def test_default_output_path_uses_mode_aware_latest_files() -> None:
    assert default_output_path(
        "summary", run_id="latest", query_mode="standard"
    ).name == ("latest.standard.summary.json")
    assert default_output_path(
        "failed", run_id="latest", query_mode="discorag"
    ).name == ("latest.discorag.failed.json")


def test_default_output_path_uses_run_id_without_double_mode_suffix() -> None:
    path = default_output_path(
        "summary",
        run_id="20260518_170000.discorag",
        query_mode="discorag",
    )

    assert path.name == "20260518_170000.discorag.summary.json"


def test_build_results_summary_preserves_case_metrics_and_reasons() -> None:
    payload = {
        "testFile": "tests/evals/test_rag_deepeval.py",
        "runDuration": 21.83,
        "evaluationCost": 0.0169725,
        "metricsScores": [
            {"metric": "Answer Relevancy", "score": 1.0},
            {"metric": "Faithfulness", "score": 1.0},
        ],
        "testCases": [
            {
                "name": "best-practices-overview",
                "input": "What is the simple mental model?",
                "actualOutput": "Treat Codex like a teammate.",
                "expectedOutput": "Start with task context.",
                "success": True,
                "runDuration": 7.25,
                "retrievalContext": ["ctx-1", "ctx-2", "ctx-3", "ctx-4"],
                "metricsData": [
                    {
                        "name": "Answer Relevancy",
                        "score": 1.0,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Directly answers the question.",
                        "error": None,
                    },
                    {
                        "name": "Contextual Relevancy",
                        "score": 0.94,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Mostly aligned, with one small mismatch.",
                        "error": None,
                    },
                ],
            }
        ],
        "conversationalTestCases": [],
    }

    summary = build_results_summary(payload)

    assert summary == {
        "test_file": "tests/evals/test_rag_deepeval.py",
        "run_duration": 21.83,
        "evaluation_cost": 0.0169725,
        "total_cases": 1,
        "passed_cases": 1,
        "failed_cases": 0,
        "cases": [
            {
                "name": "best-practices-overview",
                "success": True,
                "input": "What is the simple mental model?",
                "actual_output": "Treat Codex like a teammate.",
                "expected_output": "Start with task context.",
                "retrieval_context_count": 4,
                "metric_map": {
                    "answer_relevancy": {
                        "score": 1.0,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Directly answers the question.",
                        "error": None,
                    },
                    "contextual_relevancy": {
                        "score": 0.94,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Mostly aligned, with one small mismatch.",
                        "error": None,
                    },
                },
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 1.0,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Directly answers the question.",
                        "error": None,
                    },
                    {
                        "name": "Contextual Relevancy",
                        "score": 0.94,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "Mostly aligned, with one small mismatch.",
                        "error": None,
                    },
                ],
            }
        ],
    }


def test_build_results_summary_falls_back_to_case_run_durations() -> None:
    payload = {
        "testFile": "tests/evals/test_rag_deepeval.py",
        "runDuration": 0.0,
        "evaluationCost": 0.25,
        "testCases": [
            {
                "name": "case-a",
                "success": True,
                "runDuration": 2.5,
                "metricsData": [],
            },
            {
                "name": "case-b",
                "success": False,
                "runDuration": 1.5,
                "metricsData": [],
            },
        ],
    }

    summary = build_results_summary(payload)
    metrics = build_metric_averages_report(summary)

    assert summary["run_duration"] == 4.0
    assert metrics["run_duration"] == 4.0


def test_build_failed_results_report_keeps_only_failed_cases() -> None:
    summary = {
        "run_id": "20260421_234301",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "cases": [
            {
                "name": "passed-case",
                "success": True,
                "metrics": [],
            },
            {
                "name": "failed-case",
                "success": False,
                "input": "why failed",
                "metrics": [
                    {
                        "name": "Faithfulness",
                        "score": 0.2,
                        "success": False,
                    }
                ],
            },
        ],
    }

    report = build_failed_results_report(summary)

    assert report == {
        "run_id": "20260421_234301",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "total_cases": 2,
        "failed_cases": 1,
        "cases": [
            {
                "name": "failed-case",
                "success": False,
                "input": "why failed",
                "metrics": [
                    {
                        "name": "Faithfulness",
                        "score": 0.2,
                        "success": False,
                    }
                ],
            }
        ],
    }


def test_build_metric_averages_report_aggregates_scores_and_pass_rates() -> None:
    summary = {
        "run_id": "20260421_234301",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "run_duration": 12.5,
        "evaluation_cost": 0.42,
        "cases": [
            {
                "name": "case-a",
                "success": True,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 1.0,
                        "success": True,
                    },
                    {
                        "name": "Faithfulness",
                        "score": 0.8,
                        "success": True,
                    },
                ],
            },
            {
                "name": "case-b",
                "success": False,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.4,
                        "success": False,
                    },
                    {
                        "name": "Faithfulness",
                        "score": 0.6,
                        "success": True,
                    },
                ],
            },
        ],
    }

    report = build_metric_averages_report(summary)

    assert report == {
        "run_id": "20260421_234301",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "total_cases": 2,
        "passed_cases": 1,
        "failed_cases": 1,
        "pass_rate": 0.5,
        "run_duration": 12.5,
        "evaluation_cost": 0.42,
        "metrics": {
            "answer_relevancy": {
                "name": "Answer Relevancy",
                "average_score": 0.7,
                "count": 2,
                "passed_count": 1,
                "pass_rate": 0.5,
            },
            "faithfulness": {
                "name": "Faithfulness",
                "average_score": 0.7,
                "count": 2,
                "passed_count": 2,
                "pass_rate": 1.0,
            },
        },
    }


def test_build_comparison_report_handles_zero_or_missing_baseline_percent_delta() -> (
    None
):
    summary = {
        "run_id": "current-run",
        "cases": [
            {
                "name": "case-a",
                "success": True,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.75,
                        "success": True,
                    },
                    {
                        "name": "Contextual Relevancy",
                        "score": 0.9,
                        "success": True,
                    },
                    {
                        "name": "Faithfulness",
                        "score": 0.8,
                        "success": True,
                    },
                ],
            }
        ],
    }
    baseline = {
        "run_id": "baseline-run",
        "cases": [
            {
                "name": "case-a",
                "success": False,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.5,
                        "success": False,
                    },
                    {
                        "name": "Contextual Relevancy",
                        "score": 0.0,
                        "success": False,
                    },
                ],
            }
        ],
    }

    report = build_comparison_report(summary, baseline)

    assert report["run_id"] == "current-run"
    assert report["baseline_run_id"] == "baseline-run"
    assert report["pass_rate"] == {
        "current": 1.0,
        "baseline": 0.0,
        "absolute_delta": 1.0,
        "percent_delta": None,
    }
    assert report["metrics"]["answer_relevancy"] == {
        "name": "Answer Relevancy",
        "current": 0.75,
        "baseline": 0.5,
        "absolute_delta": 0.25,
        "percent_delta": 50.0,
    }
    assert report["metrics"]["contextual_relevancy"] == {
        "name": "Contextual Relevancy",
        "current": 0.9,
        "baseline": 0.0,
        "absolute_delta": 0.9,
        "percent_delta": None,
    }
    assert report["metrics"]["faithfulness"] == {
        "name": "Faithfulness",
        "current": 0.8,
        "baseline": None,
        "absolute_delta": None,
        "percent_delta": None,
    }


def test_find_previous_summary_path_ignores_latest_and_current_run(
    tmp_path: Path,
) -> None:
    (tmp_path / "latest.summary.json").write_text("{}", encoding="utf-8")
    older = tmp_path / "20260421_224937.summary.json"
    newer = tmp_path / "20260421_234301.summary.json"
    current = tmp_path / "20260422_010203.summary.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    current.write_text("{}", encoding="utf-8")

    resolved = find_previous_summary_path(
        run_id="20260422_010203",
        summary_dir=tmp_path,
    )

    assert resolved == newer


def test_find_previous_summary_path_accepts_mode_suffixed_history(
    tmp_path: Path,
) -> None:
    older = tmp_path / "20260421_224937.standard.summary.json"
    newer = tmp_path / "20260421_234301.standard.summary.json"
    current = tmp_path / "20260422_010203.standard.summary.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    current.write_text("{}", encoding="utf-8")

    resolved = find_previous_summary_path(
        run_id="20260422_010203.standard",
        summary_dir=tmp_path,
    )

    assert resolved == newer


def test_main_writes_summary_failed_metrics_and_compare_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    results_path = tmp_path / "current.json"
    baseline_path = tmp_path / "baseline.json"
    summary_output = tmp_path / "summary.json"
    failed_output = tmp_path / "failed.json"
    metrics_output = tmp_path / "metrics.json"
    compare_output = tmp_path / "compare.json"

    results_payload = {
        "testFile": "tests/evals/test_rag_deepeval.py",
        "runDuration": 0.0,
        "evaluationCost": 0.3,
        "testCases": [
            {
                "name": "case-pass",
                "input": "pass?",
                "actualOutput": "yes",
                "expectedOutput": "yes",
                "success": True,
                "runDuration": 2.0,
                "retrievalContext": ["ctx-1"],
                "metricsData": [
                    {
                        "name": "Answer Relevancy",
                        "score": 1.0,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "good",
                        "error": None,
                    }
                ],
            },
            {
                "name": "case-fail",
                "input": "fail?",
                "actualOutput": "no",
                "expectedOutput": "yes",
                "success": False,
                "runDuration": 3.0,
                "retrievalContext": [],
                "metricsData": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.0,
                        "threshold": 0.5,
                        "success": False,
                        "reason": "bad",
                        "error": None,
                    }
                ],
            },
        ],
    }
    baseline_payload = {
        "testFile": "tests/evals/test_rag_deepeval.py",
        "runDuration": 4.0,
        "evaluationCost": 0.2,
        "testCases": [
            {
                "name": "case-pass",
                "success": False,
                "runDuration": 4.0,
                "metricsData": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.5,
                        "threshold": 0.5,
                        "success": False,
                        "reason": "older",
                        "error": None,
                    }
                ],
            }
        ],
    }
    results_path.write_text(json.dumps(results_payload), encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline_payload), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_results.py",
            "--results",
            str(results_path),
            "--summary-output",
            str(summary_output),
            "--failed-output",
            str(failed_output),
            "--metrics-output",
            str(metrics_output),
            "--baseline",
            str(baseline_path),
            "--compare-output",
            str(compare_output),
        ],
    )

    main()

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    failed = json.loads(failed_output.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_output.read_text(encoding="utf-8"))
    compare = json.loads(compare_output.read_text(encoding="utf-8"))

    assert summary["run_id"] == "current.standard"
    assert summary["query_mode"] == "standard"
    assert summary["source_results_path"] == str(results_path)
    assert summary["run_duration"] == 5.0
    assert failed["failed_cases"] == 1
    assert failed["cases"][0]["name"] == "case-fail"
    assert metrics["run_duration"] == 5.0
    assert metrics["pass_rate"] == 0.5
    assert metrics["metrics"]["answer_relevancy"]["average_score"] == 0.5
    assert compare["baseline_run_id"] == "baseline"
    assert compare["pass_rate"]["absolute_delta"] == 0.5
    assert compare["metrics"]["answer_relevancy"]["absolute_delta"] == 0.0


def test_main_adds_mode_metadata_and_source_results_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_dir = tmp_path / "raw" / "standard"
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "20260518_170000"
    raw_path.write_text(
        json.dumps(
            {
                "testFile": "tests/evals/test_rag_deepeval.py",
                "runDuration": 1.0,
                "evaluationCost": 0.0,
                "testCases": [],
            }
        ),
        encoding="utf-8",
    )
    summary_output = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_results.py",
            "--results",
            str(raw_dir),
            "--query-mode",
            "standard",
            "--summary-output",
            str(summary_output),
        ],
    )

    main()

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["run_id"] == "20260518_170000.standard"
    assert summary["query_mode"] == "standard"
    assert summary["source_results_path"] == str(raw_path)


def test_main_export_all_writes_latest_and_timestamped_outputs_with_auto_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    deepeval_dir = tmp_path / "data" / "deepeval"
    raw_dir = deepeval_dir / "raw"
    summary_dir = deepeval_dir / "summary"
    failed_dir = deepeval_dir / "failed"
    metrics_dir = deepeval_dir / "metrics"
    compare_dir = deepeval_dir / "compare"
    raw_dir.mkdir(parents=True)
    summary_dir.mkdir(parents=True)

    previous_summary = {
        "run_id": "20260421_224937",
        "test_file": "tests/evals/test_rag_deepeval.py",
        "cases": [
            {
                "name": "case-a",
                "success": False,
                "metrics": [
                    {
                        "name": "Answer Relevancy",
                        "score": 0.5,
                        "success": False,
                    }
                ],
            }
        ],
    }
    (summary_dir / "20260421_224937.summary.json").write_text(
        json.dumps(previous_summary),
        encoding="utf-8",
    )

    raw_payload = {
        "testFile": "tests/evals/test_rag_deepeval.py",
        "runDuration": 0.0,
        "evaluationCost": 0.3,
        "testCases": [
            {
                "name": "case-a",
                "success": True,
                "runDuration": 2.0,
                "metricsData": [
                    {
                        "name": "Answer Relevancy",
                        "score": 1.0,
                        "threshold": 0.5,
                        "success": True,
                        "reason": "good",
                        "error": None,
                    }
                ],
            }
        ],
    }
    raw_path = raw_dir / "20260421_234301"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")

    monkeypatch.setattr("evals.summarize_results.DEFAULT_DEEPEVAL_PATH", deepeval_dir)
    monkeypatch.setattr("evals.summarize_results.DEFAULT_RESULTS_PATH", raw_dir)
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_SUMMARY_DIR",
        summary_dir,
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_FAILED_DIR",
        failed_dir,
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_METRICS_DIR",
        metrics_dir,
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_COMPARE_DIR",
        compare_dir,
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_SUMMARY_OUTPUT",
        summary_dir / "latest.summary.json",
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_FAILED_OUTPUT",
        failed_dir / "latest.failed.json",
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_METRICS_OUTPUT",
        metrics_dir / "latest.metrics.json",
    )
    monkeypatch.setattr(
        "evals.summarize_results.DEFAULT_COMPARE_OUTPUT",
        compare_dir / "latest.compare.json",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_results.py",
            "--results",
            str(raw_dir),
            "--export-all",
        ],
    )

    main()

    latest_summary = json.loads(
        (summary_dir / "latest.summary.json").read_text(encoding="utf-8")
    )
    timestamped_summary = json.loads(
        (summary_dir / "20260421_234301.standard.summary.json").read_text(
            encoding="utf-8"
        )
    )
    latest_failed = json.loads(
        (failed_dir / "latest.failed.json").read_text(encoding="utf-8")
    )
    latest_metrics = json.loads(
        (metrics_dir / "latest.metrics.json").read_text(encoding="utf-8")
    )
    latest_compare = json.loads(
        (compare_dir / "latest.compare.json").read_text(encoding="utf-8")
    )

    assert latest_summary["run_id"] == "20260421_234301.standard"
    assert timestamped_summary["run_id"] == "20260421_234301.standard"
    assert latest_failed["failed_cases"] == 0
    assert latest_metrics["metrics"]["answer_relevancy"]["average_score"] == 1.0
    assert latest_compare["baseline_run_id"] == "20260421_224937"
