# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

## 概述
这个目录是业务编排层，存放 ingestion 与 query 相关的 application 代码。

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
├── pipelines/   # ingestion pipeline files
├── services/    # application service files
└── use_cases/   # reserved for a future stable use-case boundary
```

## 文件地图
- `pipelines/`: ingestion 相关目录。
- `services/`: query、document、dataset、DiscoRAG 相关目录。
- `use_cases/`: 预留目录；只有在形成稳定 use-case 边界后再启用。

## 边界提示
- 运行契约统一看 [CONTRACTS.md](./CONTRACTS.md)。
- 子目录 `AGENTS.md` 只保留导航、命令、文件角色和错层提醒。

## 禁区
- 不要在 application 层直接 import FastAPI, Infinity SDK, provider SDK, or local JSON storage.
- 不要在这里放 parser selection、provider retry policy、table/index DDL 之类的 adapter 细节。
- 不要把 `use_cases/` 当成“暂时不知道放哪”的目录。
