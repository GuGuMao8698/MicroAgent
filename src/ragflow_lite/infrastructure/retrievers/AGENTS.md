# AGENTS.md

这个目录实现 query grounding, sparse query analysis and auxiliary Infinity hybrid retrieval. It is not the graph-first orchestrator.

## 关键命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

- `DeepSeekChatQueryGrounder` produces `answer_type_keywords` and `entities_from_query` for graph retrieval.
- `InfinityHybridRetriever` embeds the raw query, builds a sparse chunk query, and calls `InfinityDenseVectorIndex.search_hybrid()`.
- `query_analysis.py` owns NFKC/whitespace/lowercase/CJK-boundary/tech-token sparse query normalization.

## 关键约定
- `embed_query()` must receive the original raw query; only sparse/fulltext branch uses analyzed chunk text query.
- `InfinityHybridRetriever` is auxiliary chunk retrieval for graph-first flow; do not add rerank, citation assembly, or a new primary retrieval path here.
- Query grounding adapters must validate structured JSON and reject empty queries without model calls.
- Preserve tech-token behavior for `c++`, `c#`, `node.js`, `api_v1`, `gpt-4o` and symbol fallback coverage.
- Do not expose hybrid/fusion tuning as HTTP API or public service configuration.
- Do not log raw query text or provider payloads.
