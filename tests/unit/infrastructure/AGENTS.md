# AGENTS.md

这个目录测试 infrastructure adapters and low-level text/index/provider contracts. It is the heaviest unit subtree.

## 常用命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

- These tests protect adapter contracts: tokenizer behavior, sparse query normalization, chunking, parsing, provider wrappers, local JSON stores, Infinity config surfaces and graph/vector candidate row builders.
- Fake Ark/DeepSeek/OpenAI clients are allowed for non-Infinity provider boundaries.
- Tests named around Infinity config or pure helper behavior may stay unit-level, but anything crossing real Infinity SDK/table/query output belongs under live integration with `@pytest.mark.live_infinity`.

## 关键约定
- Do not add fake/stub/mock Infinity clients, databases, tables, query builders, or `infinity.connect` monkeypatches.
- Preserve raw-query versus sparse-query assertions: dense embedding gets raw query, hybrid sparse branch gets analyzed query.
- Sparse-query tests must cover NFKC, whitespace, Latin lowercase, CJK boundaries, tech tokens and symbol fallback.
- Parser tests must preserve native-PDF boundaries and failure behavior; do not normalize corrupted/encrypted PDFs into success.
- Provider adapter tests should validate strict JSON handling and no-call behavior for empty input.
- Local JSON index/store tests should preserve atomic replace, delete and signature validation semantics.
