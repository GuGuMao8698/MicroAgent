# tests/evals/CONTRACTS.md

Eval-specific contracts. Navigation lives in [AGENTS.md](./AGENTS.md).

## Gate requirements

- deepeval tests require `@pytest.mark.deepeval` and explicit `--run-deepeval`.
- Live evals also require live Infinity (`--run-deepeval` implies `--run-live-infinity`; see [tests/CONTRACTS.md](../CONTRACTS.md)).

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

- `summarize_results.py --export-all` writes rolling `latest.*` files and timestamped summary/failed/metrics history.
- Pytest eval runs do NOT automatically write summary artifacts. Run `summarize_results.py` after raw export.
