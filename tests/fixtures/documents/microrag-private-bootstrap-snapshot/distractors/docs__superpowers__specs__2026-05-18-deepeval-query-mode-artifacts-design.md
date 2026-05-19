# DeepEval Query Mode Artifacts

Date: 2026-05-18
Status: Draft design spec

This document specifies the next DeepEval adaptation slice: single-mode RAG
evaluation for the current `standard` and `discorag` query modes, with
mode-aware artifact storage. It is planning material, not an active runtime
contract. Active contracts remain in `tests/evals/CONTRACTS.md`,
`tests/CONTRACTS.md`, and `src/ragflow_lite/**/CONTRACTS.md` until the
implementation lands.

## Decision

Add a run-level query mode selector for DeepEval RAG evaluation.

Each evaluation run targets exactly one mode:

```text
standard
discorag
```

The selected mode is part of the run configuration, not part of the golden
dataset. The same goldens must be reusable for both modes unless a future
golden-generation design explicitly changes the dataset scope.

Mode must also become part of the run identity and local artifact naming so
`standard` and `discorag` runs do not overwrite each other's latest summary,
failed-case, metrics, or compare outputs.

Cross-mode comparison is not automated in this slice. Default compare behavior
compares only same-mode historical runs. Cross-mode comparison may be performed
only when the user explicitly supplies a baseline path.

Run identity must carry mode directly:

```text
run_id = <timestamp>.<mode>
```

History files then use:

```text
<run_id>.<kind>.json
```

They must not append mode a second time.

## Current Facts

- DeepEval docs do not define a native `standard` / `discorag` selector.
- DeepEval docs describe evaluation as test cases plus metrics. Scores are
  `0-1`, default metric threshold is generally `0.5`, and a test case passes
  only when all selected metrics pass.
- DeepEval docs document `DEEPEVAL_RESULTS_FOLDER` as an export directory for
  timestamped JSON run output, but do not define a per-mode folder or suffix
  convention.
- The repository currently gates live DeepEval runs with `--run-deepeval`;
  `--run-deepeval` implies live Infinity.
- The current test harness posts `query` and `top_k` to `/api/v0/queries`; it
  does not pass `mode`.
- The API already accepts `QueryRequest.mode` as `standard` or `discorag`, and
  the route already forwards it to `QueryModeRouter`.
- The current summary script already supports raw DeepEval exports, normalized
  summaries, rolling latest files, timestamped history files, and explicit
  baselines for compare.
- The current compare payload is mode-agnostic, so mode must be carried by
  run id, output path, and summary metadata before compare output is trusted.

## Goals

1. Let the user choose the evaluated query mode for a run.
2. Keep DeepEval default-off and live-Infinity-gated.
3. Reuse the same golden cases for both modes.
4. Pass the selected mode through the `/api/v0/queries` request body.
5. Add mode-aware run identity so artifacts remain readable and non-overwriting.
6. Preserve existing summary, failed-case, metrics, and compare workflows.
7. Make same-mode historical comparison the default.
8. Allow explicit cross-mode comparison only when the user provides a baseline.

## Non-Goals

- Do not generate or redesign goldens in this slice.
- Do not add `mode` to `RagEvalCase` or the golden fixture schema.
- Do not run both modes in one DeepEval invocation.
- Do not add a new production query API field.
- Do not change `/api/v0/queries` response schema.
- Do not add SuperMew-style `rag_trace`.
- Do not add OpenTelemetry, Tempo, Jaeger, or span-level tracing.
- Do not change metric thresholds in this slice.
- Do not automate cross-mode comparison.
- Do not build a Grafana dashboard or Loki query helper in this slice.

## Run Mode Contract

The eval harness should accept one selected query mode:

```text
standard | discorag
```

Recommended pytest option:

```text
--query-mode standard
--query-mode discorag
```

Debug-oriented pytest runs may default to `standard`, because it is the
baseline query path. Formal DeepEval export commands must specify mode
explicitly.

Preferred mode input:

```text
--query-mode standard
--query-mode discorag
```

Fallback mode input, only if `deepeval test run` does not pass custom pytest
options through:

```text
RAGFLOW_LITE_EVAL_QUERY_MODE=standard
RAGFLOW_LITE_EVAL_QUERY_MODE=discorag
```

If both are present, the explicit pytest option should win.

The test request payload must include the selected mode:

```json
{
  "query": "...",
  "top_k": 6,
  "mode": "standard"
}
```

or:

```json
{
  "query": "...",
  "top_k": 6,
  "mode": "discorag"
}
```

The route and application services already support this mode dispatch. The
implementation should not add another application service selector.

## Artifact Layout

Raw DeepEval exports should be separated by mode:

```text
data/deepeval/raw/standard/
data/deepeval/raw/discorag/
```

Summary-family artifacts should stay under the existing directories but use
mode-specific latest files:

```text
data/deepeval/summary/latest.standard.summary.json
data/deepeval/summary/latest.discorag.summary.json

data/deepeval/failed/latest.standard.failed.json
data/deepeval/failed/latest.discorag.failed.json

data/deepeval/metrics/latest.standard.metrics.json
data/deepeval/metrics/latest.discorag.metrics.json

data/deepeval/compare/latest.standard.compare.json
data/deepeval/compare/latest.discorag.compare.json
```

Timestamped history files should also include mode:

```text
data/deepeval/summary/20260518_170000.standard.summary.json
data/deepeval/summary/20260518_173000.discorag.summary.json
```

The exact timestamp part should continue to follow the existing summary
script's run-id behavior. The mode must be part of `run_id`, not an additional
suffix layered on top of `run_id`.

Mode-agnostic rolling files must not be written in this slice:

```text
data/deepeval/summary/latest.summary.json
data/deepeval/failed/latest.failed.json
data/deepeval/metrics/latest.metrics.json
data/deepeval/compare/latest.compare.json
```

The summary script may continue to read legacy mode-agnostic normalized
summaries as explicit baselines, but it should not create new ones.

When `--results` points to a raw export directory such as
`data/deepeval/raw/standard`, the summary script must select the newest raw
DeepEval export in that directory and record the selected source path in
summary metadata. Users may still pass a specific raw JSON file to avoid
directory selection.

## Summary Schema

Normalized summary documents should include run-level mode metadata:

```json
{
  "run_id": "20260518_170000.standard",
  "query_mode": "standard",
  "source_results_path": "data/deepeval/raw/standard/20260518_170000.json",
  "cases": []
}
```

Case names should remain the original golden case names. Mode belongs in
run-level metadata, not in case names or golden-case attributes.

The summary script should preserve mode metadata when loading an already
normalized summary.

## Compare Semantics

Default compare behavior:

```text
current standard run -> previous standard summary
current discorag run -> previous discorag summary
```

If the user supplies `--baseline`, the script may compare against that file
even when modes differ. In that case the compare report must include enough
metadata to make the comparison explicit:

```json
{
  "query_mode": "discorag",
  "baseline_query_mode": "standard"
}
```

The script must not silently compare a `standard` run against a `discorag`
baseline discovered automatically from latest files or timestamped history.

Legacy normalized summaries without `query_mode` may be used only when supplied
explicitly as `--baseline`. They should be reported as:

```json
{
  "baseline_query_mode": "unknown"
}
```

Legacy mode-agnostic summaries must not participate in automatic baseline
discovery.

## Threshold Semantics

This slice does not change metric thresholds.

The correct contract is:

- DeepEval metrics have documented default thresholds, commonly `0.5`.
- This repository constructs metric objects in `tests/eval_support.py`.
- The accepted behavior for this slice is to keep the current metric
  construction unchanged.
- Any future threshold change must be explicit in `tests/evals/CONTRACTS.md`
  and covered by targeted tests.

Do not describe pass/fail as entirely "DeepEval built-in" if repository code
explicitly configures metric objects.

## Commands

Recommended raw export commands:

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

Fallback raw export commands if DeepEval CLI does not pass custom pytest
options through:

```bash
RAGFLOW_LITE_EVAL_QUERY_MODE=standard \
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval
```

```bash
RAGFLOW_LITE_EVAL_QUERY_MODE=discorag \
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/discorag \
./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py \
  --run-deepeval
```

Recommended summary commands:

```bash
./.venv/bin/python tests/evals/summarize_results.py \
  --results data/deepeval/raw/standard \
  --query-mode standard \
  --export-all
```

```bash
./.venv/bin/python tests/evals/summarize_results.py \
  --results data/deepeval/raw/discorag \
  --query-mode discorag \
  --export-all
```

## Risks

### Mode-Leaking Goldens

Putting mode into the golden fixture would fragment the dataset and make
same-question comparisons harder. Mode belongs to the run, not the case.

### Compare Against the Wrong Baseline

Current compare logic is mode-agnostic. If mode is not included in run identity
and output naming, compare results can look valid while comparing unrelated
evaluation targets.

### Latest File Overwrite

Only separating raw exports is not enough. If summary, failed-case, metrics, or
compare latest files remain mode-agnostic, one mode can overwrite the other.
This slice stops writing new mode-agnostic latest files.

### Threshold Drift

Changing thresholds while adding mode support would make it unclear whether
score movement came from query mode behavior or metric policy. Threshold changes
must be a separate slice.

### Cross-Mode Interpretation

Cross-mode comparison is useful but easy to misread. `standard` and `discorag`
may trade off answer quality, contextual precision, and recall differently.
Automatic cross-mode comparison should wait until same-mode historical
evaluation is stable.

## Acceptance Criteria

- `--query-mode standard` sends `"mode": "standard"` to `/api/v0/queries`.
- `--query-mode discorag` sends `"mode": "discorag"` to `/api/v0/queries`.
- Goldens remain shared and mode-free.
- Summary documents include run-level `query_mode`.
- Summary documents record the selected raw export source path when `--results`
  is a directory.
- Raw exports can be stored under mode-specific folders.
- `latest.standard.*.json` and `latest.discorag.*.json` do not overwrite each
  other.
- Mode-agnostic `latest.*.json` files are not written.
- `run_id` includes mode exactly once.
- Timestamped history file names derive from `run_id` and do not append mode a
  second time.
- Default compare discovers only same-mode historical summaries.
- Explicit `--baseline` can compare across modes and records both modes.
- Explicit legacy baselines without mode metadata are accepted as
  `baseline_query_mode: "unknown"`.
- Existing explicit output path behavior remains usable.
- Existing `--run-deepeval` gating remains unchanged.

## Implementation Notes

Likely file touch points:

- `tests/conftest.py`: add and validate `--query-mode`.
- `tests/evals/test_rag_deepeval.py`: read selected mode and pass it in query
  payloads; fall back to `RAGFLOW_LITE_EVAL_QUERY_MODE` when needed.
- `tests/evals/summarize_results.py`: add `--query-mode`, mode-aware latest
  paths, mode-aware run id handling, newest-file directory selection, legacy
  baseline handling, and same-mode baseline discovery.
- `tests/evals/AGENTS.md`: update commands after implementation.
- `tests/evals/CONTRACTS.md`: record the mode and artifact contracts after
  implementation.

Tests should focus on:

- option validation;
- query payload mode propagation;
- summary mode metadata;
- source raw export path metadata;
- mode-aware latest path selection;
- no new mode-agnostic latest outputs;
- run id mode suffix applied exactly once;
- same-mode baseline discovery;
- explicit cross-mode baseline reporting.
- explicit legacy baseline reporting as unknown mode.

Live DeepEval execution remains an opt-in validation step and should not be
required for unit tests.
