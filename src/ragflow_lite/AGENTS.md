# AGENTS.md

## 概述
这个目录是后端源码根，只维护分层边界和源码级导航。具体实现约束应写到最近的子目录 `AGENTS.md`。

## Active Contracts
Runtime contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite --full
rtk cx overview src/ragflow_lite/application/services --full
rtk cx overview src/ragflow_lite/infrastructure --full
```

## 架构
```text
src/ragflow_lite/
├── api/             # FastAPI routes, schemas, deps
├── application/     # ingestion/query orchestration and services
├── config/          # env-backed runtime settings
├── domain/          # models, ports, domain errors
├── infrastructure/  # parser/chunker/embedder/index/provider/storage adapters
└── shared/          # cross-cutting logging/metrics/request helpers only
```

## 关键约定
- 不要在源码根重复具体符号清单、provider 迁移状态或阶段流水账；这些内容会漂移，应下沉到最近子目录或阶段文档。
- 不要跨层放置代码：route 不编排 parser/index/answer，domain 不依赖 FastAPI/SDK/文件系统，infrastructure 不反向决定业务流程。
- 不要把尚未进入默认主链路的 OCR/layout/table/DeepDoc、外部 rerank、dataset-aware query filter 或新检索主路径顺手塞入当前实现。
- 新增 abstraction 前先确认它表达稳定 port、消除真实重复或形成明确 extension point；不要为单一 provider 预建框架。
- 后端源码目录不放测试夹具、运行数据、临时脚本或 compose 产物。
