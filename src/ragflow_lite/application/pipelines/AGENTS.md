# AGENTS.md
Last updated: 2026-05-08T14:30:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件保留 pipeline 命令和导航；运行不变量见本地契约文件。

这个目录负责 ingestion pipeline 和异步任务生命周期。它连接 parser、chunker、embedder、index、evidence 和 dataset ports。

## 关键命令
```bash
rtk cx definition --name IngestionPipeline --from src/ragflow_lite/application/pipelines/ingestion.py --kind class
./.venv/bin/python -m pytest tests/unit/application/test_ingestion.py
```

- `IngestionPipeline` supports legacy synchronous `ingest()` and async `submit()` / `process_task()` / `get_snapshot()`.
- Supported file types are `.txt`, `.md`, and `.pdf`.
- The pipeline normalizes parsed text, aligns parser page text to `page_spans`, chunks, embeds, indexes, optionally extracts graph evidence, then optionally binds a dataset.
- Async HTTP upload is expected to submit work and return quickly; background processing happens through the configured runner.
- Stage cache covers parse/chunk only; embed/index/evidence writes are not cached.

## 关键约定
- Async ingestion requires `Idempotency-Key`; missing keys are API/client errors, not new task identities.
- Retry semantics stay at most two attempts: first failure requeues once, second failure becomes terminal `failed`.
- Task states must support polling through `queued`, `processing`, and terminal states.
- Parser metadata, especially `parser_strategy`, must be preserved into indexed document metadata.
- Dataset binding happens in the controlled ingestion flow; binding failure must clean binding state without hiding the original exception.
- Rollback is best-effort across graph evidence, vector index, document store and dataset binding. Log rollback failure, but do not replace the original business error.
- Do not turn the in-process runner into a cross-process or persistent queue unless the task explicitly opens that architecture.
- Do not add OCR/layout/table parsing here; parser capability belongs in `infrastructure/parsers`.
