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
