# AGENTS.md

## Purpose
这个目录只承接跨层复用、且不属于某一业务层的轻量基础能力。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/shared --full
```

## 文件说明
- `observability.py` -- Prometheus metrics helpers, structured logging, request/trace context
  - Ingestion task metrics: `ingest_task_accepted_total`, `ingest_task_retry_total`, `ingest_stage_cache_total`, `ingest_task_duration_seconds`, `ingest_task_queue_delay_seconds`
- `__init__.py` -- package marker

## Avoid Here
- 不要把业务流程、路由编排、provider 调用或 repository 逻辑放进来。
- 不要在这里引入重量级 observability framework。
