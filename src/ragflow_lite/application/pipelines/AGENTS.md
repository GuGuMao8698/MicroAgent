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

## 边界提示
- Active runtime contracts for ingestion and task lifecycle live in [../CONTRACTS.md](../CONTRACTS.md).
- Keep this file focused on pipeline entrypoints, local commands, and file-role navigation.
