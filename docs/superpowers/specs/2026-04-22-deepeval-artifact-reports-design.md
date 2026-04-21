# Deepeval Artifact Reports Design

**Goal:** Make repeated `deepeval` runs easier to store, inspect, and compare by giving artifacts a dedicated directory layout and extending the existing post-processing script with failed-only, metric-average, and baseline-comparison outputs.

## Scope

This design only changes local eval artifact organization and the existing `tests/evals/summarize_results.py` post-processor. It does not change the `deepeval` test harness, metric selection, or runtime query path.

## Approved Direction

Keep one post-processing entrypoint and extend it, instead of creating a second analysis pipeline.

- Raw official exports should live under `data/deepeval/raw/`.
- Normalized summary outputs should live under `data/deepeval/summary/`.
- Failed-only reports should live under `data/deepeval/failed/`.
- Metric aggregate reports should live under `data/deepeval/metrics/`.
- Optional comparison outputs should live under `data/deepeval/compare/`.

`latest.*` files remain rolling views. Timestamped files remain the readable history.

## Script Contract

`tests/evals/summarize_results.py` stays the single entrypoint and gains optional outputs:

- `--failed-output`: write only failed cases for the selected run.
- `--metrics-output`: write metric averages and run-level aggregates.
- `--baseline`: load a previous summary or raw export for comparison.
- `--compare-output`: write comparison data between the current run and the baseline.

The script should still accept an explicit raw export file or a directory of timestamped raw exports. For backwards compatibility, legacy `data/` raw exports should keep working when explicitly passed in.

## Data Shape

The normalized summary should continue to preserve per-case metrics. New report files should be derived from that summary:

- Failed report: current run id, failure counts, and failed case payloads.
- Metrics report: pass rate, run duration, evaluation cost, per-metric averages, per-metric counts, and per-metric pass rates.
- Comparison report: current run id, baseline run id, absolute deltas, and percentage deltas for pass rate and each metric average.

Percentage deltas must handle zero baselines safely by returning `null`.

## Validation

Validation should stay narrow:

- Unit tests for the new post-processing helpers and CLI-facing behavior.
- One focused manual smoke on the script using existing eval artifacts.

## Non-Goals

- No new runtime database schema.
- No new dedicated CLI wrapper script.
- No TDD loop for this small change; follow the user's requested lightweight implementation path.
