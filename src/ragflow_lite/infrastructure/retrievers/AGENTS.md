# AGENTS.md

这个目录实现 query grounding, sparse query analysis and auxiliary hybrid retrieval.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

## 文件说明
- `query_analysis.py` -- NFKC/whitespace/lowercase/CJK-boundary/tech-token sparse query normalization
- query grounding adapters -- produce structured JSON from raw queries
- hybrid retriever -- auxiliary chunk retrieval for graph-first flow

## Avoid Here
- 不要添加 rerank、citation assembly 或新的 primary retrieval path。
- 不要把 hybrid/fusion tuning 暴露为 HTTP API 或 public service configuration。
- 不要 log raw query text 或 provider payloads。
