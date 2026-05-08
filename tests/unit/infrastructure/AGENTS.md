# AGENTS.md

Unit-wide rules: see [../CONTRACTS.md](../CONTRACTS.md).

## Directory role

Infrastructure adapters and low-level text/index/provider contracts. Heaviest unit subtree.

## Quick commands
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure
./.venv/bin/python -m pytest tests/unit/infrastructure/test_query_analysis.py tests/unit/infrastructure/test_infinity_hybrid_retriever.py
```

## File map

These tests protect adapter contracts: tokenizer behavior, sparse query normalization, chunking, parsing, provider wrappers, local JSON stores, Infinity config surfaces, and graph/vector candidate row builders.

## Boundary rules

- Preserve raw-query versus sparse-query assertions: dense embedding gets raw query, hybrid sparse branch gets analyzed query.
- Sparse-query tests must cover NFKC, whitespace, Latin lowercase, CJK boundaries, tech tokens, and symbol fallback.
- Parser tests must preserve native-PDF boundaries and failure behavior; do not normalize corrupted/encrypted PDFs into success.
- Provider adapter tests should validate strict JSON handling and no-call behavior for empty input.
- Local JSON index/store tests should preserve atomic replace, delete, and signature validation semantics.
