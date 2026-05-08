# AGENTS.md

这个目录实现 vector index and catalog/dataset storage surfaces.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 快速命令
```bash
rtk cx overview src/ragflow_lite/infrastructure/vector_indexes --full
./.venv/bin/python -m pytest tests/unit/infrastructure/test_infinity_dense_index.py tests/unit/infrastructure/test_local_index.py
```

## 文件说明
- Infinity dense index -- document rows, chunk rows, dataset rows, document-dataset bindings
- Local JSON vector index -- fallback/test-double with atomic replace
- [chunk_text_fields.py](chunk_text_fields.py) -- localized sparse fields for hybrid chunk retrieval

## Avoid Here
- 不要引入 rerank、tag API、dataset-aware query filtering 或新的 primary retrieval path。
- 不要在 tests 里伪造跨 real index/query-builder 边界的 Infinity behavior。
