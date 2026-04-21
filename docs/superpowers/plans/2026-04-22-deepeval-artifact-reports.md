# Deepeval Artifact Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize deepeval artifacts under `data/deepeval/` and extend the existing results summarizer to emit summary, failed-only, metrics, and comparison reports.

**Architecture:** Keep `tests/evals/summarize_results.py` as the only post-processing entrypoint. Add small pure helper functions for report derivation, keep CLI options explicit, and update the local workflow docs plus ignore rules to match the new artifact layout.

**Tech Stack:** Python, pytest, existing deepeval artifact JSON format

---

### Task 1: Extend Deepeval Artifact Post-Processing

**Files:**
- Modify: `tests/evals/summarize_results.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`
- Modify: `.gitignore`
- Modify: `tests/AGENTS.md`
- Create: `data/deepeval/raw/.gitkeep`
- Create: `data/deepeval/summary/.gitkeep`
- Create: `data/deepeval/failed/.gitkeep`
- Create: `data/deepeval/metrics/.gitkeep`
- Create: `data/deepeval/compare/.gitkeep`

- [ ] Add path helpers and defaults for the new `data/deepeval/*` layout while preserving explicit legacy-path support.
- [ ] Add helper functions for failed-only report generation, metric averages, and baseline comparison.
- [ ] Extend the CLI with explicit output flags for summary, failed-only, metrics, and comparison artifacts.
- [ ] Add focused unit coverage for the new helper outputs and baseline delta behavior.
- [ ] Update `.gitignore` and `tests/AGENTS.md` so the recommended workflow matches the new artifact layout.

### Task 2: Verify The New Workflow

**Files:**
- No additional files expected

- [ ] Run focused unit tests for `tests/unit/test_eval_artifact_scripts.py`.
- [ ] Run the summarizer against existing raw artifacts to write the new report set under `data/deepeval/`.
- [ ] Inspect the generated files to confirm the directory layout and report shapes are readable.

## Execution Note

The user explicitly requested no TDD for this small implementation. Use focused post-change verification instead of a red-green loop.
