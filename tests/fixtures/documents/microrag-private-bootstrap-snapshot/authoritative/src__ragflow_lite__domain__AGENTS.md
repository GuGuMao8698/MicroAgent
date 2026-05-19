# AGENTS.md

## Purpose
这个目录负责稳定的业务边界，承载核心对象、抽象接口和领域错误。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/domain --full
rtk cx symbols --kind class --name '*' --file src/ragflow_lite/domain/models
rtk cx symbols --kind class --name '*' --file src/ragflow_lite/domain/ports
```

## 架构
```text
domain/
├── models/   # stable domain objects (Document, Chunk, retrieval/answer types, ingestion task, graph evidence, DiscoRAG types)
├── ports/    # stable abstract interfaces (parser, chunker, embedder, vector/retrieval, answerer, store, evidence, discourse)
└── errors/   # domain-level exceptions (DocumentNotFound, DatasetNotFound, IdempotencyKeyMissing, etc.)
```

## Avoid Here
- 不要依赖 FastAPI、数据库客户端、文件系统或外部 SDK 细节。
- 不要把具体实现塞进 `domain`。
