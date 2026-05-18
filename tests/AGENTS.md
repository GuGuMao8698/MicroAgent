# AGENTS.md

Active test harness semantics: see [CONTRACTS.md](./CONTRACTS.md).

## Directory role

Tests, fixtures, and optional evaluation. Root AGENTS covers cross-tree navigation; subtree-specific rules live in the nearest [AGENTS.md](./AGENTS.md) or [CONTRACTS.md](./CONTRACTS.md).

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/application tests/unit/infrastructure
./.venv/bin/python -m pytest tests/evals/test_rag_deepeval.py --run-deepeval
DEEPEVAL_RESULTS_FOLDER=./data/deepeval/raw/standard ./.venv/bin/deepeval test run tests/evals/test_rag_deepeval.py --run-deepeval --query-mode standard
./.venv/bin/python tests/evals/summarize_results.py --results data/deepeval/raw/standard --query-mode standard --export-all
```

## Architecture
```text
tests/
├── unit/          # module and boundary tests
├── integration/   # API/live main-link tests
├── evals/         # optional deepeval scripts and tests
├── fixtures/      # committed static txt/md/pdf/eval fixtures
└── eval_support.py
```

## File map notes

- [unit/test_eval_gating.py](unit/test_eval_gating.py) tests marker/option/env gating itself and must not require the `deepeval` package.
- [fixtures/documents](fixtures/documents) holds committed sample documents only; runtime outputs and local screenshots stay out of fixtures.
- Answerer prompt source of truth is the tracked templates under [src/ragflow_lite/infrastructure/answerers](../src/ragflow_lite/infrastructure/answerers), not inline constants.
- Manual smoke follows [docker/AGENTS.md](../docker/AGENTS.md); do not copy compose output into tests.

## Boundary rules

- Prefer failure-path and boundary tests over happy-path-only coverage, especially provider failure mapping, startup failure, dimension guards, dataset/catalog behavior, async ingestion state, citation/PDF page metadata, and observability.
