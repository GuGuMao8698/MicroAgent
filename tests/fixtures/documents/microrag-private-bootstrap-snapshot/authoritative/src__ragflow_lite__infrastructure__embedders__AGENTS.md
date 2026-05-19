# AGENTS.md

这个目录实现 text embedding adapter。它 converts chunks/query text into normalized dense vectors.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- embedding adapter -- implements chunk and query embedding
- `embed_query()` must receive the raw user query for dense retrieval

## Avoid Here
- 不要添加第二个 embedding provider 或 provider registry。
- 不要 log raw text sent to embedding API 或 returned vectors。
- Sparse/fulltext query rewriting 属于 retriever，不在这里。
