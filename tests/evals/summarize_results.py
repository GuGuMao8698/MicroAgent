from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TypeGuard

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_PATH = PROJECT_ROOT / "tests"
if str(TESTS_PATH) not in sys.path:
    sys.path.insert(0, str(TESTS_PATH))
DEFAULT_DEEPEVAL_PATH = PROJECT_ROOT / "data" / "deepeval"
DEFAULT_RESULTS_PATH = DEFAULT_DEEPEVAL_PATH / "raw"
LEGACY_RESULTS_PATH = PROJECT_ROOT / "data"
DEFAULT_SUMMARY_DIR = DEFAULT_DEEPEVAL_PATH / "summary"
DEFAULT_FAILED_DIR = DEFAULT_DEEPEVAL_PATH / "failed"
DEFAULT_METRICS_DIR = DEFAULT_DEEPEVAL_PATH / "metrics"
DEFAULT_COMPARE_DIR = DEFAULT_DEEPEVAL_PATH / "compare"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_DEEPEVAL_PATH / "summary" / "latest.summary.json"
DEFAULT_FAILED_OUTPUT = DEFAULT_DEEPEVAL_PATH / "failed" / "latest.failed.json"
DEFAULT_METRICS_OUTPUT = DEFAULT_DEEPEVAL_PATH / "metrics" / "latest.metrics.json"
DEFAULT_COMPARE_OUTPUT = DEFAULT_DEEPEVAL_PATH / "compare" / "latest.compare.json"
_TIMESTAMPED_EXPORT_RE = re.compile(r"^\d{8}_\d{6}$")
QUERY_MODES = ("standard", "discorag")
QueryMode = str
_RUN_ID_RE = re.compile(r"^\d{8}_\d{6}(?:\.(standard|discorag))?$")
_REPORT_SUFFIXES = {
    "summary": ".summary.json",
    "failed": ".failed.json",
    "metrics": ".metrics.json",
    "compare": ".compare.json",
}


def default_output_path(
    report_kind: str,
    *,
    run_id: str = "latest",
    query_mode: QueryMode | None = None,
) -> Path:
    dirs = {
        "summary": DEFAULT_SUMMARY_DIR,
        "failed": DEFAULT_FAILED_DIR,
        "metrics": DEFAULT_METRICS_DIR,
        "compare": DEFAULT_COMPARE_DIR,
    }
    try:
        output_dir = dirs[report_kind]
        suffix = _REPORT_SUFFIXES[report_kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported report kind: {report_kind}") from exc

    if run_id == "latest":
        if query_mode not in QUERY_MODES:
            raise ValueError("query_mode is required for latest deepeval outputs.")
        return output_dir / f"latest.{query_mode}{suffix}"
    return output_dir / f"{run_id}{suffix}"


def resolve_results_path(path: Path) -> Path:
    if path.is_file():
        return path

    if not path.exists():
        raise RuntimeError(f"Results path does not exist: {path}")
    if not path.is_dir():
        raise RuntimeError(f"Results path must be a file or directory: {path}")

    candidates = sorted(
        child
        for child in path.iterdir()
        if child.is_file() and _TIMESTAMPED_EXPORT_RE.fullmatch(child.name)
    )
    if not candidates:
        raise RuntimeError(
            f"No deepeval exports found in {path}. Expected files like YYYYMMDD_HHMMSS."
        )
    return candidates[-1]


def load_results_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("deepeval export must be a JSON object.")
    if "testCases" not in payload:
        raise RuntimeError("deepeval export does not contain testCases.")
    return payload


def load_summary_document(
    path: Path,
    *,
    query_mode: QueryMode | None = None,
    source_results_path: Path | None = None,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("deepeval artifact must be a JSON object.")

    if "testCases" in payload:
        summary = build_results_summary(payload)
    elif "cases" in payload:
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise RuntimeError("normalized summary field 'cases' must be a list.")
        summary = dict(payload)
    else:
        raise RuntimeError(
            "deepeval artifact must be a raw export or normalized summary."
        )

    summary.setdefault("run_id", infer_run_id(path))
    existing_mode = summary.get("query_mode")
    if query_mode is not None:
        if existing_mode is not None and existing_mode != query_mode:
            raise RuntimeError(
                f"Summary query_mode {existing_mode!r} does not match requested "
                f"query_mode {query_mode!r}."
            )
        summary["query_mode"] = query_mode
        summary["run_id"] = apply_query_mode_to_run_id(
            str(summary["run_id"]),
            query_mode,
        )
    elif existing_mode is None:
        inferred_mode = query_mode_from_run_id(str(summary["run_id"]))
        if inferred_mode is not None:
            summary["query_mode"] = inferred_mode

    if source_results_path is not None:
        summary["source_results_path"] = str(source_results_path)
    return summary


def build_results_summary(payload: dict[str, Any]) -> dict[str, Any]:
    test_cases = payload.get("testCases")
    if not isinstance(test_cases, list):
        raise RuntimeError("deepeval export field 'testCases' must be a list.")

    cases: list[dict[str, Any]] = []
    case_run_durations: list[float] = []
    for item in test_cases:
        if not isinstance(item, dict):
            raise RuntimeError("Each deepeval test case must be a JSON object.")
        metrics_data = item.get("metricsData", [])
        if not isinstance(metrics_data, list):
            raise RuntimeError("deepeval test case field 'metricsData' must be a list.")

        metrics: list[dict[str, Any]] = []
        for metric in metrics_data:
            if not isinstance(metric, dict):
                raise RuntimeError("Each deepeval metric entry must be a JSON object.")
            metrics.append(
                {
                    "name": metric.get("name"),
                    "score": metric.get("score"),
                    "threshold": metric.get("threshold"),
                    "success": metric.get("success"),
                    "reason": metric.get("reason"),
                    "error": metric.get("error"),
                }
            )
        metric_map = {
            _normalize_metric_key(metric["name"]): {
                "score": metric["score"],
                "threshold": metric["threshold"],
                "success": metric["success"],
                "reason": metric["reason"],
                "error": metric["error"],
            }
            for metric in metrics
            if isinstance(metric.get("name"), str) and metric["name"]
        }

        retrieval_context = item.get("retrievalContext", [])
        if not isinstance(retrieval_context, list):
            retrieval_context = []

        case_run_duration = item.get("runDuration")
        if _is_number(case_run_duration):
            case_run_durations.append(float(case_run_duration))

        cases.append(
            {
                "name": item.get("name"),
                "success": bool(item.get("success")),
                "input": item.get("input"),
                "actual_output": item.get("actualOutput"),
                "expected_output": item.get("expectedOutput"),
                "retrieval_context_count": len(retrieval_context),
                "metric_map": metric_map,
                "metrics": metrics,
            }
        )

    passed_cases = sum(1 for case in cases if case["success"])
    return {
        "test_file": payload.get("testFile"),
        # Official exports sometimes leave top-level runDuration at 0.0 even when
        # each case has a measured duration; use the summed case time as a simple
        # fallback so summary/metrics artifacts stay informative.
        "run_duration": _resolve_run_duration(
            payload.get("runDuration"),
            case_run_durations,
        ),
        "evaluation_cost": payload.get("evaluationCost"),
        "total_cases": len(cases),
        "passed_cases": passed_cases,
        "failed_cases": len(cases) - passed_cases,
        "cases": cases,
    }


def build_failed_results_report(summary: dict[str, Any]) -> dict[str, Any]:
    cases = _summary_cases(summary)
    failed_cases = [case for case in cases if not case.get("success")]
    return {
        "run_id": summary.get("run_id"),
        "query_mode": summary.get("query_mode"),
        "test_file": summary.get("test_file"),
        "total_cases": len(cases),
        "failed_cases": len(failed_cases),
        "cases": failed_cases,
    }


def build_metric_averages_report(summary: dict[str, Any]) -> dict[str, Any]:
    cases = _summary_cases(summary)
    passed_cases = sum(1 for case in cases if case.get("success"))
    metrics: dict[str, dict[str, Any]] = {}

    for case in cases:
        raw_metrics = case.get("metrics", [])
        if not isinstance(raw_metrics, list):
            continue
        for metric in raw_metrics:
            if not isinstance(metric, dict):
                continue
            name = metric.get("name")
            if not isinstance(name, str) or not name:
                continue
            key = _normalize_metric_key(name)
            aggregate = metrics.setdefault(
                key,
                {
                    "name": name,
                    "count": 0,
                    "passed_count": 0,
                    "score_count": 0,
                    "score_total": 0.0,
                },
            )
            aggregate["count"] += 1

            score = metric.get("score")
            if _is_number(score):
                aggregate["score_total"] += float(score)
                aggregate["score_count"] += 1

            success = metric.get("success")
            if isinstance(success, bool):
                aggregate["passed_count"] += int(success)

    rendered_metrics: dict[str, dict[str, Any]] = {}
    for key, aggregate in sorted(metrics.items()):
        average_score = None
        if aggregate["score_count"]:
            average_score = aggregate["score_total"] / aggregate["score_count"]
        pass_rate = None
        if aggregate["count"]:
            pass_rate = aggregate["passed_count"] / aggregate["count"]
        rendered_metrics[key] = {
            "name": aggregate["name"],
            "average_score": average_score,
            "count": aggregate["count"],
            "passed_count": aggregate["passed_count"],
            "pass_rate": pass_rate,
        }

    total_cases = len(cases)
    pass_rate = None
    if total_cases:
        pass_rate = passed_cases / total_cases
    return {
        "run_id": summary.get("run_id"),
        "query_mode": summary.get("query_mode"),
        "test_file": summary.get("test_file"),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "pass_rate": pass_rate,
        "run_duration": summary.get("run_duration"),
        "evaluation_cost": summary.get("evaluation_cost"),
        "metrics": rendered_metrics,
    }


def build_comparison_report(
    summary: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    current_metrics = build_metric_averages_report(summary)
    baseline_metrics = build_metric_averages_report(baseline_summary)
    metric_keys = sorted(
        set(current_metrics["metrics"]) | set(baseline_metrics["metrics"])
    )

    metrics: dict[str, dict[str, Any]] = {}
    for key in metric_keys:
        current_metric = current_metrics["metrics"].get(key, {})
        baseline_metric = baseline_metrics["metrics"].get(key, {})
        metrics[key] = {
            "name": current_metric.get("name") or baseline_metric.get("name"),
            **_build_delta_payload(
                current_metric.get("average_score"),
                baseline_metric.get("average_score"),
            ),
        }

    return {
        "run_id": current_metrics.get("run_id"),
        "query_mode": summary.get("query_mode", "unknown"),
        "baseline_run_id": baseline_metrics.get("run_id"),
        "baseline_query_mode": baseline_summary.get("query_mode", "unknown"),
        "pass_rate": _build_delta_payload(
            current_metrics.get("pass_rate"),
            baseline_metrics.get("pass_rate"),
        ),
        "metrics": metrics,
    }


def merge_result_summaries(
    summaries: list[dict[str, Any]],
    *,
    query_mode: QueryMode,
    active_case_order: list[str],
    raw_inputs: list[str],
    run_id: str | None = None,
) -> dict[str, Any]:
    if not summaries:
        raise RuntimeError("At least one deepeval summary is required.")

    active_case_names = set(active_case_order)
    cases_by_name: dict[str, dict[str, Any]] = {}
    duplicate_names: set[str] = set()
    unknown_names: set[str] = set()
    selected_case_ranges: list[Any] = []
    total_run_duration = 0.0
    has_run_duration = False
    total_evaluation_cost = 0.0
    has_evaluation_cost = False
    test_file = summaries[0].get("test_file")

    for summary in summaries:
        existing_mode = summary.get("query_mode")
        if existing_mode is not None and existing_mode != query_mode:
            raise RuntimeError(
                f"Summary query_mode {existing_mode!r} does not match requested "
                f"query_mode {query_mode!r}."
            )

        selected_range = summary.get("selected_case_range")
        if selected_range is not None:
            selected_case_ranges.append(selected_range)
        selected_ranges = summary.get("selected_case_ranges")
        if isinstance(selected_ranges, list):
            selected_case_ranges.extend(selected_ranges)

        duration = summary.get("run_duration")
        if _is_number(duration):
            total_run_duration += float(duration)
            has_run_duration = True
        cost = summary.get("evaluation_cost")
        if _is_number(cost):
            total_evaluation_cost += float(cost)
            has_evaluation_cost = True

        for case in _summary_cases(summary):
            name = case.get("name")
            if not isinstance(name, str) or not name:
                raise RuntimeError("Merged deepeval case is missing a case name.")
            if name not in active_case_names:
                unknown_names.add(name)
                continue
            if name in cases_by_name:
                duplicate_names.add(name)
                continue
            cases_by_name[name] = case

    if duplicate_names:
        names = ", ".join(sorted(duplicate_names))
        raise RuntimeError(f"duplicate deepeval case names in merged inputs: {names}")
    if unknown_names:
        names = ", ".join(sorted(unknown_names))
        raise RuntimeError(
            "merged deepeval inputs contain cases outside active goldens: " + names
        )

    ordered_cases = [
        cases_by_name[name] for name in active_case_order if name in cases_by_name
    ]
    missing_cases = [name for name in active_case_order if name not in cases_by_name]
    passed_cases = sum(1 for case in ordered_cases if case.get("success"))
    full_report_valid = not missing_cases and len(ordered_cases) == len(
        active_case_order
    )

    return {
        "run_id": run_id or apply_query_mode_to_run_id("merged", query_mode),
        "query_mode": query_mode,
        "test_file": test_file,
        "run_duration": total_run_duration if has_run_duration else None,
        "evaluation_cost": total_evaluation_cost if has_evaluation_cost else None,
        "total_cases": len(ordered_cases),
        "passed_cases": passed_cases,
        "failed_cases": len(ordered_cases) - passed_cases,
        "cases": ordered_cases,
        "selected_case_ranges": selected_case_ranges,
        "merged_raw_inputs": raw_inputs,
        "case_count": len(active_case_order),
        "completed_case_count": len(ordered_cases),
        "missing_case_count": len(missing_cases),
        "duplicate_case_count": 0,
        "missing_cases": missing_cases,
        "full_report_valid": full_report_valid,
    }


def summarize_with_active_case_metadata(
    summary: dict[str, Any],
    *,
    query_mode: QueryMode,
    active_case_order: list[str],
    raw_input: str,
    run_id: str,
) -> dict[str, Any]:
    return merge_result_summaries(
        [summary],
        query_mode=query_mode,
        active_case_order=active_case_order,
        raw_inputs=[raw_input],
        run_id=run_id,
    )


def _normalize_metric_key(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return normalized.strip("_")


def infer_run_id(path: Path) -> str:
    for suffix in _REPORT_SUFFIXES.values():
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.name if _TIMESTAMPED_EXPORT_RE.fullmatch(path.name) else path.stem


def _run_id_timestamp(run_id: str, query_mode: QueryMode) -> str | None:
    if not _RUN_ID_RE.fullmatch(run_id):
        return None
    mode = query_mode_from_run_id(run_id)
    if mode is not None and mode != query_mode:
        raise RuntimeError(
            f"Run id {run_id!r} already carries query mode {mode!r}, "
            f"not {query_mode!r}."
        )
    timestamp = run_id.rsplit(".", maxsplit=1)[0] if mode is not None else run_id
    return timestamp if _TIMESTAMPED_EXPORT_RE.fullmatch(timestamp) else None


def merged_run_id_from_inputs(
    summary_paths: list[Path],
    query_mode: QueryMode,
) -> str:
    latest_timestamp = None
    for path in summary_paths:
        timestamp = _run_id_timestamp(infer_run_id(path.resolve()), query_mode)
        if timestamp is not None and (
            latest_timestamp is None or timestamp > latest_timestamp
        ):
            latest_timestamp = timestamp

    if latest_timestamp is None:
        latest_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return apply_query_mode_to_run_id(latest_timestamp, query_mode)


def apply_query_mode_to_run_id(run_id: str, query_mode: QueryMode) -> str:
    if query_mode not in QUERY_MODES:
        raise ValueError(f"Unsupported query mode: {query_mode!r}")
    mode_suffix = f".{query_mode}"
    if run_id.endswith(mode_suffix):
        return run_id
    for mode in QUERY_MODES:
        if run_id.endswith(f".{mode}"):
            raise RuntimeError(
                f"Run id {run_id!r} already carries query mode {mode!r}, "
                f"not {query_mode!r}."
            )
    return f"{run_id}.{query_mode}"


def query_mode_from_run_id(run_id: str) -> str | None:
    for mode in QUERY_MODES:
        if run_id.endswith(f".{mode}"):
            return mode
    return None


def find_previous_summary_path(
    *,
    run_id: str,
    query_mode: QueryMode,
    summary_dir: Path | None = None,
) -> Path | None:
    if summary_dir is None:
        summary_dir = DEFAULT_SUMMARY_DIR
    if not summary_dir.exists() or not summary_dir.is_dir():
        return None

    candidates = sorted(
        child
        for child in summary_dir.iterdir()
        if child.is_file()
        and child.name.endswith(_REPORT_SUFFIXES["summary"])
        and _RUN_ID_RE.fullmatch(infer_run_id(child))
        and infer_run_id(child) != run_id
        and query_mode_from_run_id(infer_run_id(child)) == query_mode
    )
    if not candidates:
        return None
    return candidates[-1]


def _summary_cases(summary: dict[str, Any]) -> list[dict[str, Any]]:
    cases = summary.get("cases")
    if not isinstance(cases, list):
        raise RuntimeError("normalized summary field 'cases' must be a list.")
    return cases


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _resolve_run_duration(
    top_level_run_duration: Any,
    case_run_durations: list[float],
) -> float | int | None:
    if _is_number(top_level_run_duration) and float(top_level_run_duration) != 0.0:
        return top_level_run_duration
    if case_run_durations:
        return sum(case_run_durations)
    if _is_number(top_level_run_duration):
        return top_level_run_duration
    return None


def _build_delta_payload(current: Any, baseline: Any) -> dict[str, Any]:
    absolute_delta = None
    percent_delta = None
    if _is_number(current) and _is_number(baseline):
        absolute_delta = float(current) - float(baseline)
        if baseline != 0:
            percent_delta = (absolute_delta / float(baseline)) * 100
    return {
        "current": current,
        "baseline": baseline,
        "absolute_delta": absolute_delta,
        "percent_delta": percent_delta,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _unique_paths(paths: list[Path]) -> list[Path]:
    rendered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        rendered.append(path)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize an official deepeval export for local analysis."
    )
    parser.add_argument(
        "--results",
        type=Path,
        action="append",
        default=None,
        help=(
            "Path to a deepeval export file or a directory containing timestamped "
            "exports. May be provided multiple times for batch merge. Defaults "
            f"to {DEFAULT_RESULTS_PATH}."
        ),
    )
    parser.add_argument(
        "--summary-output",
        "--output",
        dest="summary_output",
        type=Path,
        default=None,
        help="Optional path to write the normalized JSON summary.",
    )
    parser.add_argument(
        "--failed-output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the failed-only report. Recommended rolling path: "
            f"{DEFAULT_FAILED_OUTPUT}."
        ),
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the metric averages report. Recommended rolling "
            f"path: {DEFAULT_METRICS_OUTPUT}."
        ),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Optional baseline raw export or normalized summary path for comparison."
        ),
    )
    parser.add_argument(
        "--compare-output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the baseline comparison report. Recommended "
            f"rolling path: {DEFAULT_COMPARE_OUTPUT}."
        ),
    )
    parser.add_argument(
        "--export-all",
        action="store_true",
        default=False,
        help=(
            "Write the full deepeval report set into data/deepeval/, including "
            "rolling latest files and timestamped history files. If a previous "
            "timestamped summary exists, compare will be generated automatically."
        ),
    )
    parser.add_argument(
        "--query-mode",
        choices=QUERY_MODES,
        default="standard",
        help="Query mode represented by this DeepEval run: standard or discorag.",
    )
    args = parser.parse_args()

    result_inputs = args.results or [DEFAULT_RESULTS_PATH]
    summary_paths = [resolve_results_path(path) for path in result_inputs]
    summaries = [
        load_summary_document(
            path,
            query_mode=args.query_mode,
            source_results_path=path,
        )
        for path in summary_paths
    ]
    from eval_support import RAG_EVAL_CASES

    active_case_order = [case.name for case in RAG_EVAL_CASES]
    if len(summaries) == 1:
        default_run_id = apply_query_mode_to_run_id(
            infer_run_id(summary_paths[0]),
            args.query_mode,
        )
        summary = summarize_with_active_case_metadata(
            summaries[0],
            query_mode=args.query_mode,
            active_case_order=active_case_order,
            raw_input=str(summary_paths[0]),
            run_id=default_run_id,
        )
    else:
        merged_run_id = merged_run_id_from_inputs(summary_paths, args.query_mode)
        summary = merge_result_summaries(
            summaries,
            query_mode=args.query_mode,
            active_case_order=active_case_order,
            raw_inputs=[str(path) for path in summary_paths],
            run_id=merged_run_id,
        )
        default_run_id = merged_run_id
    run_id = str(summary.get("run_id") or default_run_id)
    failed_report = build_failed_results_report(summary)
    metrics_report = build_metric_averages_report(summary)

    summary_targets: list[Path] = []
    failed_targets: list[Path] = []
    metrics_targets: list[Path] = []
    compare_targets: list[Path] = []

    if args.summary_output is not None:
        summary_targets.append(args.summary_output)
    if args.failed_output is not None:
        failed_targets.append(args.failed_output)
    if args.metrics_output is not None:
        metrics_targets.append(args.metrics_output)
    if args.compare_output is not None:
        compare_targets.append(args.compare_output)

    if args.export_all:
        summary_targets.extend(
            [
                default_output_path(
                    "summary", run_id="latest", query_mode=args.query_mode
                ),
                default_output_path(
                    "summary", run_id=run_id, query_mode=args.query_mode
                ),
            ]
        )
        failed_targets.extend(
            [
                default_output_path(
                    "failed", run_id="latest", query_mode=args.query_mode
                ),
                default_output_path(
                    "failed", run_id=run_id, query_mode=args.query_mode
                ),
            ]
        )
        metrics_targets.extend(
            [
                default_output_path(
                    "metrics", run_id="latest", query_mode=args.query_mode
                ),
                default_output_path(
                    "metrics", run_id=run_id, query_mode=args.query_mode
                ),
            ]
        )

    baseline_ref = args.baseline
    if baseline_ref is None and args.export_all:
        baseline_ref = find_previous_summary_path(
            run_id=run_id,
            query_mode=args.query_mode,
        )

    if compare_targets and baseline_ref is None:
        raise RuntimeError(
            "--compare-output requires --baseline, or use --export-all with an "
            "existing previous timestamped summary."
        )

    comparison_report = None
    if baseline_ref is not None:
        baseline_path = resolve_results_path(baseline_ref)
        baseline_summary = load_summary_document(baseline_path)
        comparison_report = build_comparison_report(summary, baseline_summary)
        if args.export_all:
            compare_targets.extend(
                [
                    default_output_path(
                        "compare", run_id="latest", query_mode=args.query_mode
                    ),
                    default_output_path(
                        "compare", run_id=run_id, query_mode=args.query_mode
                    ),
                ]
            )

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    for target in _unique_paths(summary_targets):
        _write_json(target, summary)
    for target in _unique_paths(failed_targets):
        _write_json(target, failed_report)
    for target in _unique_paths(metrics_targets):
        _write_json(target, metrics_report)
    if comparison_report is not None:
        for target in _unique_paths(compare_targets):
            _write_json(target, comparison_report)

    print(rendered)


if __name__ == "__main__":
    main()
