# AGENTS.md

Integration contracts: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

API and live-system boundary tests. Correct place for real Infinity-backed endpoint and core path checks.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/integration --run-live-infinity
```

## Architecture
```text
tests/integration/
├── api/              # request/response contracts, async document lifecycle
└── infrastructure/   # real Infinity SDK/table/index/query behavior
```

## Boundary rules

- Keep integration tests narrow and purposeful; broad quality evaluation belongs in [tests/evals](../evals).
- These tests may require local services and exported runtime provider keys depending on the path under test.
