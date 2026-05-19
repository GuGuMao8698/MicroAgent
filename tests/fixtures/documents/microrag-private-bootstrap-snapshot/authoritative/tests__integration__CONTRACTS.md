# tests/integration/CONTRACTS.md

Integration test contracts. Navigation lives in [AGENTS.md](./AGENTS.md).

## Live Infinity marker

Tests requiring a real Infinity instance must use `@pytest.mark.live_infinity` and run only with `--run-live-infinity`. Without the flag, marked tests are skipped. See [tests/CONTRACTS.md](../CONTRACTS.md) for gate semantics.

## Endpoint lifecycle

- `POST /documents` returns `202 + Location + queued`; clients poll `GET /documents/{id}` to terminal state.
- Keep live table cleanup isolated to the test scope; do not mix local runtime data with committed fixtures.

## Table isolation

Integration tests use `assign_isolated_infinity_tables(settings, tmp_path)` to generate scoped table names (hash-based suffix from `tmp_path`). Tables are registered for cleanup and dropped at session end when `run_live_infinity` is active. See [tests/CONTRACTS.md](../CONTRACTS.md) for cleanup helpers.

## No fake Infinity

Do not replace live Infinity behavior with fakes in this tree. Tests that claim live storage/index/query behavior must use the real Infinity SDK.
