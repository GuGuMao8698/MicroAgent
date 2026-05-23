# tests/evals/CONTRACTS.md

Eval-specific contracts. Navigation lives in [AGENTS.md](./AGENTS.md).

## Gate requirements

- deepeval tests require `@pytest.mark.deepeval` and explicit `--run-deepeval`.
- Live evals also require live Infinity (`--run-deepeval` implies `--run-live-infinity`; see [tests/CONTRACTS.md](../CONTRACTS.md)).

## Query mode

- DeepEval RAG evaluation runs target exactly one query mode: `standard` or `discorag`.
- Preferred selector: `--query-mode standard` or `--query-mode discorag`.
- Fallback selector when a DeepEval CLI version does not forward custom pytest options: `RAGFLOW_LITE_EVAL_QUERY_MODE`.
- If both are available, the explicit pytest option wins.
- Query mode is run-level metadata. It must not be added to `RagEvalCase` or the golden fixture schema.
- The eval request body sent to `/api/v0/queries` includes `mode`.

## Metric policy

- Answerable cases with `expected_output` add the reference-based retrieval metrics: `Contextual Precision` and `Contextual Recall`.
- `standard` base metrics are `Answer Relevancy`, `Faithfulness`, and `Contextual Relevancy`.
- `discorag` base metrics are `Answer Relevancy` and `Faithfulness`; it omits `Contextual Relevancy` because DiscoRAG returns a blueprint-shaped answer-planning context, not a traditional retrieval-only context.
- Golden `additionalMetadata.answerability` allows only `answerable` and `unanswerable`; missing/blank values default to `answerable`.
- `answerability="unanswerable"` cases do not use `Contextual Precision` or `Contextual Recall` solely because they include an expected refusal answer.
- This is a query-mode policy, not a per-run skip flag. Do not add a separate CLI option for this behavior.

## Case concurrency

- The live DeepEval test uploads the shared fixture corpus before starting concurrent case evaluation.
- Golden cases run with bounded case-level concurrency.
- Default case concurrency is `20`.
- Preferred selector: `--deepeval-case-concurrency <N>`.
- Fallback selector when a DeepEval CLI version does not forward custom pytest options: `RAGFLOW_LITE_DEEPEVAL_CASE_CONCURRENCY`.
- The explicit pytest option wins over the environment fallback.
- Concurrency is per golden case. Each case keeps the internal order: query, build DeepEval test case, build metrics, run metrics, build snapshot.
- The concurrent runner does not fail fast. It summarizes all failed cases after the started case evaluations finish.
- Case concurrency is implemented inside a single test invocation; pytest-xdist behavior is outside this contract.

## Environment validation

`validate_deepeval_env` (eval_support.py) checks that these env vars are set and not placeholder values:

- `DEEPSEEK_API_KEY`
- `ARK_API_KEY`
- `ARK_EMBEDDING_MODEL`

Placeholder detection uses `_PLACEHOLDER_ENV_VALUES = {"test-deepseek-api-key", "test-ark-api-key", "ep-test-model"}`.

## Goldens and venvs

- Goldens generation: `.venv-goldens/bin/python tests/evals/generate_goldens.py`. Do not mix `.venv-goldens` dependencies into the main runtime `.venv`.
- Prompt optimization: main `.venv/bin/python tests/evals/optimize_prompt.py` (imports repo runtime code, consumes committed goldens).
- `_RAG_EVAL_GOLDENS_PATH = tests/fixtures/evals/synthetic_goldens.json` ([eval_support.py](../eval_support.py)).

## Private bootstrap goldens

- The private bootstrap dataset uses `tests/fixtures/documents/microrag-private-bootstrap-snapshot/` as its active eval corpus fixture.
- DeepEval live runs upload every file listed in the snapshot manifest as a separate runtime document before running the private bootstrap cases.
- `tests/fixtures/documents/microrag-private-bootstrap.md` is a generated compatibility/inspection packed fixture. It must not be treated as proof of cross-document retrieval.
- The packed fixture is generated from `tests/fixtures/documents/microrag-private-bootstrap-snapshot/`.
- `CONTRACTS.md` and `AGENTS.md` snapshot entries are authoritative sources.
- `docs/superpowers` snapshot entries are historical distractors and must not be the sole support for current-runtime claims.
- `tests/fixtures/evals/private_bootstrap_goldens.draft.json` is the review-stage artifact.
- `tests/fixtures/evals/synthetic_goldens.json` remains the active DeepEval artifact consumed by `tests/eval_support.py`.
- Private bootstrap golden metadata must include `corpus_fixture = "microrag-private-bootstrap-snapshot"` and `document_fixture = "microrag-private-bootstrap.md"`; `document_fixture` is compatibility metadata, not the active knowledge-base input.
- Run `tests/evals/build_private_bootstrap_goldens.py` before replacing the active artifact.

## Default deepeval model

Source: eval_support.py.

| Setting | Default | Env override |
|---|---|---|
| Model | `deepseek-v4-flash` | `DEEPEVAL_MODEL` |
| Base URL | `https://api.deepseek.com` | `DEEPEVAL_BASE_URL` |
| Reasoning effort | `high` | `DEEPEVAL_REASONING_EFFORT` |

## Summary artifacts

- `summarize_results.py --export-all --query-mode <mode>` writes mode-specific rolling latest files and timestamped history.
- Raw DeepEval exports should be separated by mode under `data/deepeval/raw/standard/` and `data/deepeval/raw/discorag/`.
- New rolling files use names such as `latest.standard.summary.json`, `latest.discorag.failed.json`, `latest.standard.metrics.json`, and `latest.discorag.compare.json`.
- Timestamped history files derive from `run_id = <timestamp>.<mode>` and do not append mode a second time.
- Mode-agnostic rolling files such as `latest.summary.json` are legacy inputs only and must not be written by the current export flow.
- Default compare discovers only previous summaries with the same `query_mode`.
- Explicit `--baseline` may compare across modes and reports both `query_mode` and `baseline_query_mode`; legacy baselines without mode metadata are reported as `baseline_query_mode: "unknown"`.
- Pytest eval runs do NOT automatically write summary artifacts. Run `summarize_results.py` after raw export.
