# AGENTS.md
Last updated: 2026-05-08T14:30:00+08:00

## 概述
这个目录是业务编排层，负责把 domain ports 连接成 ingestion/query 用例。它不拥有 HTTP、SDK、Infinity 或文件系统实现。

## 契约

Active contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/application --full
rtk cx overview src/ragflow_lite/application/services --full
rtk cx definition --name IngestionPipeline --from src/ragflow_lite/application/pipelines/ingestion.py --kind class
```

## 架构
```text
application/
├── pipelines/   # ingestion state machine and async task lifecycle
├── services/    # query/document/dataset/DiscoRAG orchestration
└── use_cases/   # currently empty; do not use as a dumping ground
```

- `pipelines/` owns ingestion lifecycle: parse, normalize, chunk, embed, index, optional graph evidence, dataset binding, rollback, task state.
- `services/` owns query/document/dataset orchestration: standard query, DiscoRAG query, graph-first retrieval, evidence package, blueprint building, router dispatch.
- Application code talks to parser/chunker/embedder/index/retriever/answerer/document/dataset/evidence abstractions from `domain.ports`.
- Route models and HTTP errors stay in `api`; provider clients, Infinity tables, JSON files and tokenizers stay in `infrastructure`.

## 关键约定
- `QueryService` stays generic: it depends on `Retriever` + `Answerer`, not graph/dense/hybrid/fusion details.
- `QueryModeRouter` only dispatches `"standard"` / `"discorag"`; it must not grow retrieval, evidence, or answer logic.
- `GraphFirstSourceSelection` is an internal application contract. Do not expose it or retrieval strategy knobs through HTTP.
- `DocumentService` must validate dataset existence before dataset filtering or document rebinding.
- `DatasetService` strips dataset names and rejects empty names.
- Main-link logs and metrics may record safe outcome fields only. Do not log raw document bodies, full query text, filenames as labels, or high-cardinality identifiers in metrics labels.
- Rollback remains best-effort and must not mask the original business exception.
- If a rule is specific to `services/` or `pipelines/`, put it in that child `AGENTS.md` instead of expanding this overview.

## 禁区
- 不要在 application 层直接 import FastAPI, Infinity SDK, provider SDK, or local JSON storage.
- 不要在这里做 parser selection, citation rendering, provider retry policy, or table/index DDL.
- 不要把 `use_cases/` 当成“暂时不知道放哪”的目录；没有稳定用例边界前保持空。
