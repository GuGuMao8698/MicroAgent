# Application Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/application`.
`AGENTS.md` files in this subtree should link here instead of duplicating these
contracts.

## DiscoRAG Budget Contract

Reviewed at: `2026-05-08T12:56:51+08:00`
Status: Active
Owner: `MiniGraphFirstRetriever`, `DiscoRAGQueryService`

Source of truth:
- Public final answer context budget: `QueryRequest.top_n`.
- Discourse-visible budget: `MiniGraphFirstRetriever.discourse_selection_k`.

Invariant:
- `top_n` is the final answer context budget.
- Default `top_n=6` means final answer contexts are bounded to 6.
- Default `discourse_selection_k = 2 * top_n`.
- Default `top_n=6` means RST / inter-chunk graph visibility is 12 chunks.
- Supplemental discourse chunks participate in RST, inter-chunk graph, and blueprint construction.
- Supplemental discourse chunks do not append to final answer contexts.
- Promotion is bounded replacement, not append.

Forbidden stale interpretations:
- Do not treat `discourse_selection_k` as equal to `top_n`.
- Do not reintroduce extractor-local defaults such as `max_chunks=5`.
- Do not use historical `docs/superpowers/plans` or `docs/superpowers/specs` as active runtime contracts.

Verification:
- `tests/unit/application/test_mini_graph_first_retriever.py`
- `tests/unit/application/test_discorag_query_service.py`
- stale scan for `max_chunks: int = 5` and `discourse_selection_n == top_n`
