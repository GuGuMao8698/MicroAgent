# AGENTS.md

Unit-wide rules: see `../CONTRACTS.md`.

## Directory role

Application orchestration contract tests. Uses fakes to verify collaboration order, state machines, error semantics, and metadata passing.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/application
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py tests/unit/application/test_mini_graph_first_retriever.py
```

## File map

- `test_ingestion.py` — idempotency, retry, task transitions, stage cache, rollback, progress, observability.
- `test_mini_graph_first_retriever.py` — graph-first budget, scoring, fallback, source-selection.

## Boundary rules

- Mock collaborators, not the behavior being specified. If the assertion is about routing, idempotency, metadata, or state transitions, keep that semantic explicit.
- Do not introduce provider SDK, FastAPI route models, or Infinity SDK dependencies into unit application tests.
- Query service tests should keep `QueryService` generic and graph/fusion-agnostic.
- Router tests should assert dispatch and rejection only; retrieval or answer behavior belongs elsewhere.
