# tests/CONTRACTS.md

Source-backed test harness semantics. Navigation lives in [AGENTS.md](./AGENTS.md).

## CLI gates

| Option | Default | Effect |
|---|---|---|
| `--run-live-infinity` | `false` | Enables tests marked `@pytest.mark.live_infinity`. |
| `--run-deepeval` | `false` | Enables tests marked `@pytest.mark.deepeval`. Requires the `deepeval` package. |

`run_deepeval` implies `run_live_infinity`:
```python
run_live_infinity = config.getoption("--run-live-infinity") or run_deepeval
```
(conftest.py `pytest_collection_modifyitems`)

Without the relevant flag, marked tests are skipped automatically.

## Markers

Registered in `pytest_configure` (conftest.py):

- `live_infinity` — test connects to a real Infinity instance.
- `deepeval` — optional deepeval-based RAG evaluation.

## Placeholder environment defaults

conftest.py sets these placeholder values via `os.environ.setdefault`:

| Variable | Placeholder |
|---|---|
| `DEEPSEEK_API_KEY` | `test-deepseek-api-key` |
| `OPENAI_API_KEY` | `test-openai-api-key` |
| `ARK_API_KEY` | `test-ark-api-key` |
| `ARK_EMBEDDING_MODEL` | `ep-test-model` |

conftest.py clears `RAGFLOW_LITE_LOG_LEVEL`, `RAGFLOW_LITE_LOG_FORMAT`, `RAGFLOW_LITE_METRICS_ENABLED` from the environment.

## deepeval prompt variant

conftest.py `_set_deepeval_plain_prompt_variant` monkeypatches `RAGFLOW_LITE_OPENAI_RENDER_CITATIONS=false` for any item marked `deepeval`, keeping citation rendering disabled during metric evaluation.

## Fixture document path

`fixture_documents_dir` returns [tests/fixtures/documents](fixtures/documents).

## Scoped app settings and client fixtures

- `app_settings` (conftest.py): creates `Settings` with `tmp_path`. Normal tests and DeepEval `fresh` mode call `assign_isolated_infinity_tables` and `register_infinity_table_cleanup`. DeepEval `reuse` mode assigns fixed private-bootstrap eval tables and does not register them for cleanup.
- `app`: `create_app(app_settings)`, installs fake DeepSeek JSON clients.
- `client`: `TestClient(app)`, installs fake query support clients.

## Live Infinity cleanup helpers

Source: [infinity_test_support.py](infinity_test_support.py).

- `assign_isolated_infinity_tables(settings, tmp_path)`: uses `tmp_path` hash for table name suffix (6 tables per settings).
- `register_infinity_table_cleanup(settings)`: registers settings + table names for session-end cleanup.
- `drop_registered_infinity_tables()`: drops all registered isolated tables (called in `pytest_sessionfinish` when `run_live_infinity` or `run_deepeval`).
- `clear_registered_infinity_tables()`: clears registrations without dropping (called in `pytest_sessionfinish` when no live gate).
- `_LIVE_TABLE_PREFIXES`: `("documents_", "chunks_", "graph_entities_", "graph_relationships_")`.

## Session finish behavior

`pytest_sessionfinish` (conftest.py):
- If `run_live_infinity` or `run_deepeval`: calls `drop_registered_infinity_tables()`.
- Otherwise: calls `clear_registered_infinity_tables()`.
- Session cleanup drops only registered isolated tables. Reusable private-bootstrap eval tables are intentionally not registered.

## Placeholder detection

[eval_support.py](eval_support.py) `_PLACEHOLDER_ENV_VALUES = {"test-deepseek-api-key", "test-ark-api-key", "ep-test-model"}`. Used by `validate_deepeval_env` to reject placeholder credentials.
