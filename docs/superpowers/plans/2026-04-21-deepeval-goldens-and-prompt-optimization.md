# Deepeval Goldens And Prompt Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old deepeval seed dataset with checked-in Goldens generated from the local eval docs, add explicit Infinity cleanup and prompt-optimization commands, and keep runtime prompt override opt-in.

**Architecture:** The repo keeps one checked-in docs copy under `tests/fixtures/documents`, one checked-in Goldens source-of-truth artifact at `tests/fixtures/evals/synthetic_goldens.json` (`6 docs * 10 = 60`), and two explicit offline commands for Goldens generation and prompt optimization. The app runtime remains stable, with only an optional prompt-artifact override.

**Tech Stack:** `deepeval`, pytest, existing `OpenAIResponsesAnswerer`, Infinity SDK

**Current Status:** Tasks 1 to 3 are code-complete and covered by focused unit verification. Task 4 is mostly complete: the checked-in docs copy, `synthetic_goldens.json`, and `eval-dataset-and-metrics.md` have been updated, but the prompt-optimization output artifact (`tests/fixtures/evals/optimized_answerer_prompt.txt`) has not yet been successfully generated and verified, and this plan still tracks the remaining doc/runtime validation tail.

---

### Task 1: Replace The Seed Dataset Contract

**Files:**
- Modify: `tests/eval_support.py`
- Modify: `tests/unit/test_eval_support.py`

- [x] Write failing tests for the new Goldens-backed dataset contract.
- [x] Make the eval loader consume `tests/fixtures/evals/synthetic_goldens.json` as the checked-in source-of-truth artifact.
- [x] Preserve markdown-fixture validation and the existing case shape used by the live deepeval test.

### Task 2: Add Offline Artifact Commands

**Files:**
- Create: `tests/evals/generate_goldens.py`
- Create: `tests/evals/optimize_prompt.py`
- Create: `tests/evals/cleanup_infinity.py`
- Create: `tests/unit/test_eval_artifact_scripts.py`

- [x] Write failing unit tests for artifact generation helpers, prompt-optimizer wiring, and cleanup table selection.
- [x] Implement document sync from `网页/deepeval/eval集` into `tests/fixtures/documents`.
- [x] Implement offline Goldens generation and checked-in artifact writing.
- [x] Implement prompt optimization with `GEPA`.
- [x] Implement explicit Infinity cleanup with a dry-run friendly table filter.

### Task 3: Add Optional Runtime Prompt Override

**Files:**
- Modify: `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- Modify: `src/ragflow_lite/config/settings.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Modify: `tests/unit/infrastructure/test_openai_responses_answerer.py`
- Modify: `tests/unit/api/test_providers.py`

- [x] Write failing tests for loading a custom prompt artifact without changing the default runtime behavior.
- [x] Implement prompt loading and configuration plumbing.

### Task 4: Replace Checked-In Artifacts And Docs

**Files:**
- Modify: `tests/fixtures/documents/*`
- Modify: `tests/fixtures/evals/synthetic_goldens.json`
- Modify: `阶段计划/详细设计/deepeval/eval-dataset-and-metrics.md`
- Modify: `阶段计划/详细设计/deepeval/execution-and-ci-path.md`

- [x] Replace the checked-in docs copy and `synthetic_goldens.json` with the new generated set.
- [ ] Update nearby docs so they describe the new offline generation and optimization flow rather than the old hand-maintained seed dataset.
  Progress note: `阶段计划/详细设计/deepeval/eval-dataset-and-metrics.md` has been updated, but this plan continues to track the remaining documentation/runtime-validation tail until the prompt-optimization artifact is successfully generated and the final nearby doc wording is fully settled.
