# DeepEval Query Mode Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add run-level `standard` / `discorag` query-mode selection to the DeepEval RAG harness and make local DeepEval artifacts mode-aware.

**Architecture:** Keep query mode as evaluation run metadata, not golden-case metadata. Reuse the existing `/api/v0/queries` production `mode` field, and add a small test-support helper for mode resolution and payload construction. Update the summary script so `query_mode` is carried in normalized summaries, `run_id` includes mode exactly once, rolling latest files are mode-specific, and automatic baseline discovery is same-mode only.

**Tech Stack:** Python, pytest, DeepEval CLI exports, FastAPI test client, local JSON artifact scripts.

---

## File Structure

- Modify `tests/eval_support.py`: define the eval query-mode contract and helper functions used by `tests/conftest.py`, `tests/evals/test_rag_deepeval.py`, and unit tests.
- Modify `tests/conftest.py`: add `--query-mode` as an optional pytest argument with valid choices; leave `--run-deepeval` gating unchanged.
- Modify `tests/evals/test_rag_deepeval.py`: resolve selected mode and include `"mode"` in the `/api/v0/queries` request payload.
- Modify `tests/evals/summarize_results.py`: add `--query-mode`, mode-aware metadata, mode-aware latest/history paths, same-mode automatic baseline discovery, and explicit cross-mode baseline reporting.
- Modify `tests/unit/test_summarize_results.py`: cover summary/artifact/compare mode semantics.
- Create `tests/unit/test_eval_query_mode.py`: cover query-mode resolution and eval request payload construction without running live DeepEval.
- Modify `tests/evals/AGENTS.md`: update local eval commands to show mode-specific raw export and summary commands.
- Modify `tests/evals/CONTRACTS.md`: record the run-level query-mode and artifact contracts after implementation.
- Modify `tests/AGENTS.md`: update the top-level eval command pointers if they still mention mode-agnostic `data/deepeval/raw`.

Do not modify production API schema, production routes, golden fixtures, metric thresholds, CI configuration, secrets, or runtime dependencies.

### Task 1: Add Shared Query-Mode Helpers

**Files:**
- Modify: `tests/eval_support.py`
- Create: `tests/unit/test_eval_query_mode.py`

- [ ] **Step 1: Write failing unit tests for query-mode resolution and payload construction**

Create `tests/unit/test_eval_query_mode.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from eval_support import build_eval_query_payload, resolve_eval_query_mode


@dataclass(frozen=True, slots=True)
class _Case:
    question: str
    top_k: int


def test_resolve_eval_query_mode_defaults_to_standard() -> None:
    assert resolve_eval_query_mode(None, {}) == "standard"


def test_resolve_eval_query_mode_uses_env_fallback() -> None:
    assert (
        resolve_eval_query_mode(
            None,
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "discorag"
    )


def test_resolve_eval_query_mode_cli_value_wins_over_env() -> None:
    assert (
        resolve_eval_query_mode(
            "standard",
            {"RAGFLOW_LITE_EVAL_QUERY_MODE": "discorag"},
        )
        == "standard"
    )


@pytest.mark.parametrize("value", ["rerank", "", " standard "])
def test_resolve_eval_query_mode_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match="Unsupported eval query mode"):
        resolve_eval_query_mode(None, {"RAGFLOW_LITE_EVAL_QUERY_MODE": value})


def test_build_eval_query_payload_includes_run_level_mode() -> None:
    payload = build_eval_query_payload(
        _Case(question="What matters?", top_k=6),
        query_mode="discorag",
    )

    assert payload == {
        "query": "What matters?",
        "top_k": 6,
        "mode": "discorag",
    }
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py -q
```

Expected: FAIL because `resolve_eval_query_mode` and `build_eval_query_payload` do not exist in `eval_support.py`. If the local environment is missing the existing `deepeval` dependency needed by `eval_support.py`, report that dependency guard separately and continue with the implementation steps in a configured `.venv`.

- [ ] **Step 3: Implement the helper functions**

In `tests/eval_support.py`, add imports and helpers near the existing constants:

```python
from typing import TYPE_CHECKING, Any, Literal, Mapping, Protocol
```

Replace the current import line if needed so it includes `Literal` and `Protocol`.

Add the mode contract below `_DEFAULT_DEEPEVAL_REASONING_EFFORT`:

```python
EvalQueryMode = Literal["standard", "discorag"]
EVAL_QUERY_MODES: tuple[EvalQueryMode, ...] = ("standard", "discorag")
EVAL_QUERY_MODE_ENV_VAR = "RAGFLOW_LITE_EVAL_QUERY_MODE"
_DEFAULT_EVAL_QUERY_MODE: EvalQueryMode = "standard"
```

Add the small protocol and helpers after `RAG_EVAL_CASES = _load_rag_eval_cases()`:

```python
class _EvalQueryCase(Protocol):
    question: str
    top_k: int


def resolve_eval_query_mode(
    cli_value: str | None,
    env: Mapping[str, str | None],
) -> EvalQueryMode:
    raw_mode = cli_value if cli_value is not None else env.get(EVAL_QUERY_MODE_ENV_VAR)
    if raw_mode is None:
        return _DEFAULT_EVAL_QUERY_MODE
    if raw_mode in EVAL_QUERY_MODES:
        return raw_mode
    allowed = ", ".join(EVAL_QUERY_MODES)
    raise ValueError(f"Unsupported eval query mode: {raw_mode!r}. Expected one of: {allowed}.")


def build_eval_query_payload(
    case: _EvalQueryCase,
    *,
    query_mode: EvalQueryMode,
) -> dict[str, Any]:
    return {
        "query": case.question,
        "top_k": case.top_k,
        "mode": query_mode,
    }
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py -q
```

Expected: PASS.

### Task 2: Wire Query Mode Through Pytest and the DeepEval Request

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/evals/test_rag_deepeval.py`
- Test: `tests/unit/test_eval_query_mode.py`

- [ ] **Step 1: Add pytest option wiring**

In `tests/conftest.py`, update the import from `eval_support`:

```python
from eval_support import EVAL_QUERY_MODES, validate_deepeval_env
```

In `pytest_addoption`, after `--run-deepeval`, add:

```python
    parser.addoption(
        "--query-mode",
        choices=EVAL_QUERY_MODES,
        default=None,
        help=(
            "query mode for deepeval RAG evaluation runs "
            "(standard or discorag); defaults to standard, or "
            "RAGFLOW_LITE_EVAL_QUERY_MODE when the option is omitted"
        ),
    )
```

- [ ] **Step 2: Update DeepEval test request payload**

In `tests/evals/test_rag_deepeval.py`, update the import from `eval_support`:

```python
from eval_support import (  # noqa: E402
    RAG_EVAL_CASES,
    build_deepeval_judge_model,
    build_eval_query_payload,
    build_metrics_for_case,
    build_rag_test_case,
    resolve_eval_query_mode,
)
```

Add the pytest request fixture to the test signature:

```python
def test_single_turn_rag_eval_produces_quality_snapshot(
    client: Any,
    fixture_documents_dir: Path,
    case: Any,
    request: pytest.FixtureRequest,
) -> None:
```

Replace the query request block:

```python
    query_response = client.post(
        "/api/v0/queries",
        json={"query": case.question, "top_k": case.top_k},
    )
```

with:

```python
    query_mode = resolve_eval_query_mode(
        request.config.getoption("--query-mode"),
        os.environ,
    )
    query_response = client.post(
        "/api/v0/queries",
        json=build_eval_query_payload(case, query_mode=query_mode),
    )
```

Add `query_mode` to the printed snapshot so the run output is inspectable:

```python
        "e2e": {
            "case": case.name,
            "query_mode": query_mode,
            "has_reference": case.has_reference,
            "document_status": final_payload["status"],
            "context_count": len(payload["contexts"]),
            "answer_length": len(payload["answer"]),
        },
```

- [ ] **Step 3: Verify pytest accepts both modes without running live eval**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode standard -q
```

Expected: collection succeeds. If the environment lacks `deepeval`, expected failure is a pytest usage error from the existing `--run-deepeval requires the 'deepeval' package` guard; do not treat that as a query-mode implementation failure.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode discorag -q
```

Expected: collection succeeds under the same dependency condition.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode rerank -q
```

Expected: pytest exits with an invalid choice error for `--query-mode`.

### Task 3: Add Mode Metadata and Run-ID Handling to Summary Script

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Write failing tests for mode metadata and run id**

In `tests/unit/test_summarize_results.py`, update the import list:

```python
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
```

Add these tests after `test_resolve_results_path_selects_latest_timestamped_export`:

```python
def test_apply_query_mode_to_run_id_appends_mode_once() -> None:
    assert apply_query_mode_to_run_id("20260518_170000", "standard") == (
        "20260518_170000.standard"
    )
    assert apply_query_mode_to_run_id("20260518_170000.standard", "standard") == (
        "20260518_170000.standard"
    )


def test_default_output_path_uses_mode_aware_latest_files() -> None:
    assert default_output_path("summary", run_id="latest", query_mode="standard").name == (
        "latest.standard.summary.json"
    )
    assert default_output_path("failed", run_id="latest", query_mode="discorag").name == (
        "latest.discorag.failed.json"
    )


def test_default_output_path_uses_run_id_without_double_mode_suffix() -> None:
    path = default_output_path(
        "summary",
        run_id="20260518_170000.discorag",
        query_mode="discorag",
    )

    assert path.name == "20260518_170000.discorag.summary.json"
```

Add a metadata assertion to `test_build_results_summary_preserves_case_metrics_and_reasons` after `summary = build_results_summary(payload)` by wrapping metadata in the script later through `load_summary_document`; keep this test focused on raw conversion. Add a new main-level test instead:

```python
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
```

- [ ] **Step 2: Run the targeted summary tests and verify they fail**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: FAIL because `apply_query_mode_to_run_id`, `query_mode` support on `default_output_path`, and `--query-mode` are not implemented.

- [ ] **Step 3: Implement mode constants and output path helpers**

In `tests/evals/summarize_results.py`, add near the current constants:

```python
QUERY_MODES = ("standard", "discorag")
QueryMode = str
_RUN_ID_RE = re.compile(r"^\d{8}_\d{6}(?:\.(standard|discorag))?$")
```

Replace `default_output_path` with:

```python
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
```

Add run-id helper functions below `infer_run_id`:

```python
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
```

- [ ] **Step 4: Add query-mode metadata during summary loading**

Change `load_summary_document` signature:

```python
def load_summary_document(
    path: Path,
    *,
    query_mode: QueryMode | None = None,
    source_results_path: Path | None = None,
) -> dict[str, Any]:
```

Replace the tail of `load_summary_document`:

```python
    summary.setdefault("run_id", infer_run_id(path))
    return summary
```

with:

```python
    summary.setdefault("run_id", infer_run_id(path))
    existing_mode = summary.get("query_mode")
    if query_mode is not None:
        if existing_mode is not None and existing_mode != query_mode:
            raise RuntimeError(
                f"Summary query_mode {existing_mode!r} does not match requested "
                f"query_mode {query_mode!r}."
            )
        summary["query_mode"] = query_mode
        summary["run_id"] = apply_query_mode_to_run_id(str(summary["run_id"]), query_mode)
    elif existing_mode is None:
        inferred_mode = query_mode_from_run_id(str(summary["run_id"]))
        if inferred_mode is not None:
            summary["query_mode"] = inferred_mode

    if source_results_path is not None:
        summary["source_results_path"] = str(source_results_path)
    return summary
```

- [ ] **Step 5: Add `--query-mode` to the CLI**

In `main()`, add:

```python
    parser.add_argument(
        "--query-mode",
        choices=QUERY_MODES,
        default="standard",
        help="Query mode represented by this DeepEval run: standard or discorag.",
    )
```

Replace:

```python
    summary_path = resolve_results_path(args.results)
    summary = load_summary_document(summary_path)
    run_id = str(summary.get("run_id") or infer_run_id(summary_path))
```

with:

```python
    summary_path = resolve_results_path(args.results)
    summary = load_summary_document(
        summary_path,
        query_mode=args.query_mode,
        source_results_path=summary_path,
    )
    run_id = str(summary.get("run_id") or apply_query_mode_to_run_id(infer_run_id(summary_path), args.query_mode))
```

- [ ] **Step 6: Run the targeted summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: existing tests may still fail where they expect old mode-agnostic latest names; those failures are addressed in the next task.

### Task 4: Make Export-All Outputs Mode-Aware and Disable New Mode-Agnostic Latest Files

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Replace old export-all latest expectations**

Rename `test_main_export_all_writes_latest_and_timestamped_outputs_with_auto_baseline` to:

```python
def test_main_export_all_writes_mode_aware_latest_and_timestamped_outputs_with_auto_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
```

In that test, make the previous summary mode-aware:

```python
    previous_summary = {
        "run_id": "20260421_224937.standard",
        "query_mode": "standard",
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
    (summary_dir / "20260421_224937.standard.summary.json").write_text(
        json.dumps(previous_summary),
        encoding="utf-8",
    )
```

Change the argv in that test to include mode:

```python
            "--query-mode",
            "standard",
```

Change output reads to mode-aware files:

```python
    latest_summary = json.loads(
        (summary_dir / "latest.standard.summary.json").read_text(encoding="utf-8")
    )
    timestamped_summary = json.loads(
        (summary_dir / "20260421_234301.standard.summary.json").read_text(encoding="utf-8")
    )
    latest_failed = json.loads(
        (failed_dir / "latest.standard.failed.json").read_text(encoding="utf-8")
    )
    latest_metrics = json.loads(
        (metrics_dir / "latest.standard.metrics.json").read_text(encoding="utf-8")
    )
    latest_compare = json.loads(
        (compare_dir / "latest.standard.compare.json").read_text(encoding="utf-8")
    )
```

Update assertions:

```python
    assert latest_summary["run_id"] == "20260421_234301.standard"
    assert latest_summary["query_mode"] == "standard"
    assert latest_summary["source_results_path"] == str(raw_path)
    assert timestamped_summary["run_id"] == "20260421_234301.standard"
    assert latest_failed["run_id"] == "20260421_234301.standard"
    assert latest_failed["query_mode"] == "standard"
    assert latest_failed["failed_cases"] == 0
    assert latest_metrics["query_mode"] == "standard"
    assert latest_metrics["metrics"]["answer_relevancy"]["average_score"] == 1.0
    assert latest_compare["run_id"] == "20260421_234301.standard"
    assert latest_compare["query_mode"] == "standard"
    assert latest_compare["baseline_run_id"] == "20260421_224937.standard"
    assert latest_compare["baseline_query_mode"] == "standard"
    assert not (summary_dir / "latest.summary.json").exists()
    assert not (failed_dir / "latest.failed.json").exists()
    assert not (metrics_dir / "latest.metrics.json").exists()
    assert not (compare_dir / "latest.compare.json").exists()
```

- [ ] **Step 2: Update report builders to carry query mode**

In `tests/evals/summarize_results.py`, update `build_failed_results_report` return value:

```python
    return {
        "run_id": summary.get("run_id"),
        "query_mode": summary.get("query_mode"),
        "test_file": summary.get("test_file"),
        "total_cases": len(cases),
        "failed_cases": len(failed_cases),
        "cases": failed_cases,
    }
```

Update `build_metric_averages_report` return value:

```python
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
```

Update existing tests `test_build_failed_results_report_keeps_only_failed_cases` and `test_build_metric_averages_report_aggregates_scores_and_pass_rates` by adding `"query_mode": None` to expected report dictionaries unless the input summary includes an explicit mode.

- [ ] **Step 3: Update export-all targets**

In `main()`, replace export-all target construction:

```python
        summary_targets.extend(
            [DEFAULT_SUMMARY_OUTPUT, default_output_path("summary", run_id=run_id)]
        )
```

with:

```python
        summary_targets.extend(
            [
                default_output_path("summary", run_id="latest", query_mode=args.query_mode),
                default_output_path("summary", run_id=run_id, query_mode=args.query_mode),
            ]
        )
```

Replace failed and metrics target construction similarly:

```python
        failed_targets.extend(
            [
                default_output_path("failed", run_id="latest", query_mode=args.query_mode),
                default_output_path("failed", run_id=run_id, query_mode=args.query_mode),
            ]
        )
        metrics_targets.extend(
            [
                default_output_path("metrics", run_id="latest", query_mode=args.query_mode),
                default_output_path("metrics", run_id=run_id, query_mode=args.query_mode),
            ]
        )
```

Replace compare export-all targets:

```python
            compare_targets.extend(
                [
                    default_output_path("compare", run_id="latest", query_mode=args.query_mode),
                    default_output_path("compare", run_id=run_id, query_mode=args.query_mode),
                ]
            )
```

- [ ] **Step 4: Run the summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: remaining failures should be limited to baseline discovery and compare metadata, handled in Task 5.

### Task 5: Restrict Automatic Compare to Same-Mode History and Report Cross-Mode Baselines Explicitly

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_summarize_results.py`

- [ ] **Step 1: Add failing tests for same-mode automatic baseline discovery**

In `tests/unit/test_summarize_results.py`, replace `test_find_previous_summary_path_ignores_latest_and_current_run` with:

```python
def test_find_previous_summary_path_uses_same_mode_history_only(
    tmp_path: Path,
) -> None:
    (tmp_path / "latest.standard.summary.json").write_text("{}", encoding="utf-8")
    older_standard = tmp_path / "20260421_224937.standard.summary.json"
    newer_discorag = tmp_path / "20260421_234301.discorag.summary.json"
    current_standard = tmp_path / "20260422_010203.standard.summary.json"
    older_standard.write_text("{}", encoding="utf-8")
    newer_discorag.write_text("{}", encoding="utf-8")
    current_standard.write_text("{}", encoding="utf-8")

    resolved = find_previous_summary_path(
        run_id="20260422_010203.standard",
        query_mode="standard",
        summary_dir=tmp_path,
    )

    assert resolved == older_standard
```

Add explicit cross-mode and legacy compare tests after `test_build_comparison_report_handles_zero_or_missing_baseline_percent_delta`:

```python
def test_build_comparison_report_records_cross_mode_baseline() -> None:
    summary = {
        "run_id": "20260518_173000.discorag",
        "query_mode": "discorag",
        "cases": [{"name": "case-a", "success": True, "metrics": []}],
    }
    baseline = {
        "run_id": "20260518_170000.standard",
        "query_mode": "standard",
        "cases": [{"name": "case-a", "success": False, "metrics": []}],
    }

    report = build_comparison_report(summary, baseline)

    assert report["query_mode"] == "discorag"
    assert report["baseline_query_mode"] == "standard"


def test_build_comparison_report_marks_legacy_baseline_mode_unknown() -> None:
    summary = {
        "run_id": "20260518_173000.discorag",
        "query_mode": "discorag",
        "cases": [{"name": "case-a", "success": True, "metrics": []}],
    }
    baseline = {
        "run_id": "20260421_170000",
        "cases": [{"name": "case-a", "success": False, "metrics": []}],
    }

    report = build_comparison_report(summary, baseline)

    assert report["query_mode"] == "discorag"
    assert report["baseline_query_mode"] == "unknown"
```

- [ ] **Step 2: Run summary tests and verify failures**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: FAIL because `find_previous_summary_path` does not accept `query_mode`, and compare reports lack mode fields.

- [ ] **Step 3: Update same-mode baseline discovery**

Change `find_previous_summary_path` signature:

```python
def find_previous_summary_path(
    *,
    run_id: str,
    query_mode: QueryMode,
    summary_dir: Path | None = None,
) -> Path | None:
```

Replace candidate filtering with:

```python
    candidates = sorted(
        child
        for child in summary_dir.iterdir()
        if child.is_file()
        and child.name.endswith(_REPORT_SUFFIXES["summary"])
        and _RUN_ID_RE.fullmatch(infer_run_id(child))
        and infer_run_id(child) != run_id
        and query_mode_from_run_id(infer_run_id(child)) == query_mode
    )
```

Update the automatic baseline call in `main()`:

```python
        baseline_ref = find_previous_summary_path(
            run_id=run_id,
            query_mode=args.query_mode,
        )
```

- [ ] **Step 4: Update compare metadata**

In `build_comparison_report`, update the return object:

```python
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
```

- [ ] **Step 5: Preserve explicit baseline behavior**

Keep this existing flow:

```python
    if baseline_ref is not None:
        baseline_path = resolve_results_path(baseline_ref)
        baseline_summary = load_summary_document(baseline_path)
        comparison_report = build_comparison_report(summary, baseline_summary)
```

Do not pass `query_mode=args.query_mode` when loading `baseline_summary`; explicit cross-mode and legacy baselines must preserve their own `query_mode` or remain `unknown`.

- [ ] **Step 6: Run summary tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_summarize_results.py -q
```

Expected: PASS after expected dictionaries are updated for new `query_mode` and `baseline_query_mode` fields.

### Task 6: Update Eval Documentation and Contracts

**Files:**
- Modify: `tests/evals/AGENTS.md`
- Modify: `tests/evals/CONTRACTS.md`
- Modify: `tests/AGENTS.md`

- [ ] **Step 1: Update eval quick commands**

In `tests/evals/AGENTS.md`, replace the Quick commands block with:

```markdown
## Quick commands
```bash
./.venv-goldens/bin/python tests/evals/generate_goldens.py
./.venv/bin/python tests/evals/optimize_prompt.py
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode discorag
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/discorag --query-mode discorag --export-all
```
```

If Markdown fencing becomes nested incorrectly during editing, keep the outer file valid by closing the code fence exactly once after the last command.

- [ ] **Step 2: Add fallback command note**

In `tests/evals/AGENTS.md`, add this paragraph after Quick commands:

```markdown
If the DeepEval CLI does not pass custom pytest options through in a local version, use `RAGFLOW_LITE_EVAL_QUERY_MODE=standard` or `RAGFLOW_LITE_EVAL_QUERY_MODE=discorag` with the same `DEEPEVAL_RESULTS_FOLDER` value and omit `--query-mode` from the `deepeval test run` command.
```

- [ ] **Step 3: Update eval contracts**

In `tests/evals/CONTRACTS.md`, add after Gate requirements:

```markdown
## Query mode

- DeepEval RAG evaluation runs target exactly one query mode: `standard` or `discorag`.
- Preferred selector: `--query-mode standard` or `--query-mode discorag`.
- Fallback selector when a DeepEval CLI version does not forward custom pytest options: `RAGFLOW_LITE_EVAL_QUERY_MODE`.
- If both are available, the explicit pytest option wins.
- Query mode is run-level metadata. It must not be added to `RagEvalCase` or the golden fixture schema.
- The eval request body sent to `/api/v0/queries` includes `mode`.
```

Replace Summary artifacts section with:

```markdown
## Summary artifacts

- `summarize_results.py --export-all --query-mode <mode>` writes mode-specific rolling latest files and timestamped history.
- Raw DeepEval exports should be separated by mode under `data/deepeval/raw/standard/` and `data/deepeval/raw/discorag/`.
- New rolling files use names such as `latest.standard.summary.json`, `latest.discorag.failed.json`, `latest.standard.metrics.json`, and `latest.discorag.compare.json`.
- Timestamped history files derive from `run_id = <timestamp>.<mode>` and do not append mode a second time.
- Mode-agnostic rolling files such as `latest.summary.json` are legacy inputs only and must not be written by the current export flow.
- Default compare discovers only previous summaries with the same `query_mode`.
- Explicit `--baseline` may compare across modes and reports both `query_mode` and `baseline_query_mode`; legacy baselines without mode metadata are reported as `baseline_query_mode: "unknown"`.
- Pytest eval runs do NOT automatically write summary artifacts. Run `summarize_results.py` after raw export.
```

- [ ] **Step 4: Update top-level test command pointers**

In `tests/AGENTS.md`, replace old mode-agnostic eval raw/summary commands with:

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
```

Keep the file concise and point details back to `tests/evals/AGENTS.md` if needed.

- [ ] **Step 5: Verify documentation mentions no new mode-agnostic latest outputs**

Run:

```bash
rtk rg -n "latest\\.summary\\.json|data/deepeval/raw(\\s|$)|summarize_results.py --results data/deepeval/raw --export-all" tests/AGENTS.md tests/evals/AGENTS.md tests/evals/CONTRACTS.md
```

Expected: no active command should write `latest.summary.json` or summarize from `data/deepeval/raw` without `/standard` or `/discorag`. Legacy references in contracts are acceptable only when explicitly described as legacy inputs.

### Task 7: Final Validation

**Files:**
- Verify only; no edits expected.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_query_mode.py tests/unit/test_summarize_results.py -q
```

Expected: PASS.

- [ ] **Step 2: Run eval collection checks for both modes**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode standard -q
```

Expected: collection succeeds if `deepeval` is installed. If `deepeval` is not installed in `.venv`, report the existing dependency guard as unverified live/eval collection, not as a code failure.

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode discorag -q
```

Expected: collection succeeds under the same dependency condition.

- [ ] **Step 3: Verify invalid mode rejection**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --collect-only --run-deepeval --query-mode rerank -q
```

Expected: pytest rejects `rerank` as an invalid choice.

- [ ] **Step 4: Run a broader impacted-unit sweep**

Run:

```bash
rtk ./.venv/bin/python -m pytest tests/unit/test_eval_artifact_scripts.py tests/unit/test_summarize_results.py tests/unit/test_eval_query_mode.py -q
```

Expected: PASS, unless the environment lacks `deepeval` and `test_eval_artifact_scripts.py` is skipped by its existing `pytest.importorskip("deepeval")`.

- [ ] **Step 5: Record unverified live execution**

Do not run live DeepEval by default. In the completion report, state that these formal live commands remain opt-in unless the user explicitly requests them:

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode standard
```

```bash
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval --query-mode discorag
```

## Self-Review Notes

- Spec coverage: The tasks cover run-level mode selection, request payload propagation, shared goldens, mode-aware raw/summary/failed/metrics/compare artifacts, source path metadata, same-mode automatic compare, explicit cross-mode baseline reporting, legacy baseline `unknown`, and unchanged `--run-deepeval` gating.
- Non-goals preserved: No task modifies production API schema, `/api/v0/queries` response schema, golden schema, metrics thresholds, tracing, dashboards, dependencies, CI, or secrets.
- Type consistency: The plan uses `EvalQueryMode` in `tests/eval_support.py` for pytest/runtime query payloads, and script-local `QueryMode = str` in `tests/evals/summarize_results.py` to avoid runtime dependency coupling from the standalone summary script back into pytest helpers.
