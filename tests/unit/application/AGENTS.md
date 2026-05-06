# AGENTS.md

这个目录测试 application orchestration contracts。它用 fakes 验证协作顺序、状态机、错误语义和 metadata 传递。

## 常用命令
```bash
./.venv/bin/python -m pytest tests/unit/application
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py tests/unit/application/test_mini_graph_first_retriever.py
```

- These tests protect orchestration semantics, not adapter implementation details.
- Fakes are expected for parser/chunker/embedder/index/retriever/answerer collaborators unless the test intentionally crosses live Infinity, which does not belong here.
- `test_ingestion.py` is the contract source for idempotency, retry, task transitions, stage cache, rollback, progress and observability.
- `test_mini_graph_first_retriever.py` protects graph-first budget, scoring, fallback and source-selection behavior.

## 关键约定
- Mock collaborators, not the behavior being specified. If the assertion is about routing, idempotency, metadata, or state transitions, keep that semantic explicit.
- Do not fake away `GraphFirstSourceSelection` metadata; downstream evidence and blueprint tests rely on it.
- Query service tests should keep `QueryService` generic and graph/fusion-agnostic.
- Router tests should assert dispatch and rejection only; retrieval or answer behavior belongs elsewhere.
- Ingestion tests should preserve parse/chunk-only cache boundaries and best-effort rollback behavior.
- Do not introduce provider SDK, FastAPI route models, or Infinity SDK dependencies into unit application tests.
