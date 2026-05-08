# AGENTS.md
Last updated: 2026-05-08T14:30:00+08:00

Active contracts: [CONTRACTS.md](./CONTRACTS.md)。本文件保留 evidence 命令和导航；运行不变量见本地契约文件。

这个目录实现 graph evidence extraction, canonical graph view, candidate indexing, path expansion and intra-chunk discourse extraction.

## 关键命令
```bash
./.venv/bin/python -m pytest tests/unit/infrastructure/test_graph_evidence_infinity_store.py tests/unit/infrastructure/test_infinity_graph_candidate_index.py
```

- Extractors call LLMs and validate strict JSON structures; they should accept one document's chunks at a time.
- `GraphEvidenceInfinityStore` dual-writes JSON graph evidence and Infinity candidate rows.
- `InfinityGraphCandidateIndex` owns `graph_entities` / `graph_relationships` candidate tables and the relationship-candidate hydration path used by graph-first retrieval.
- `LocalJsonGraphEvidenceIndex` is the query-time graph view and BFS path expander; cross-document canonicalization is query-time unless explicitly changed.

## 边界提示
- Active runtime contracts for discourse extraction and evidence persistence live in [CONTRACTS.md](./CONTRACTS.md).
- Keep this file for evidence-directory navigation, local commands, and ownership pointers only.
