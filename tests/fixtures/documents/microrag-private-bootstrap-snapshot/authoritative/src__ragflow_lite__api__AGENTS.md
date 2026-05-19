# AGENTS.md

## Purpose
这个目录负责 FastAPI HTTP 接口层，只处理 HTTP 入口附近的职责。

## Active Contracts
Runtime contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/api --full
rtk cx overview src/ragflow_lite/api/routes --full
```

## 架构
```text
api/
├── routes/v0/    # HTTP endpoints (health, documents, queries, datasets)
├── schemas/      # request/response models
├── deps/         # dependency wiring, service lookup, route-layer adapters
└── observability.py  # route-level metrics helpers
```

## Avoid Here
- 不要在这里编排 parser、chunking、embedding、index、answer 主流程。
- 不要把领域对象和基础设施实现混放到 `api`。
