# AGENTS.md

这个目录测试 API and live-system boundaries. It is the correct place for real Infinity-backed endpoint and core path checks.

## 命令
```bash
./.venv/bin/python -m pytest tests/integration --run-live-infinity
```

- `api/` covers request/response contracts and async document lifecycle.
- `infrastructure/` covers real Infinity SDK/table/index/query behavior.
- These tests may require local services and exported runtime provider keys depending on the path under test.

- Use `@pytest.mark.live_infinity` for tests requiring real Infinity and run only with `--run-live-infinity`.
- Preserve async upload contract: `POST /documents` returns `202 + Location + queued`, then clients poll `GET /documents/{id}` to terminal state.
- Keep live table cleanup isolated to the test scope; do not mix local runtime data with committed fixtures.
- Do not replace live Infinity behavior with fakes in this tree.
- Keep integration tests narrow and purposeful; broad quality evaluation belongs in `tests/evals`.
