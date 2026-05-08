# Application Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/application`.
`AGENTS.md` files in this subtree should link here instead of duplicating these
contracts.

## DiscoRAG Budget Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `MiniGraphFirstRetriever`, `DiscoRAGQueryService`

Source of truth:
- Public final answer context budget: `QueryRequest.top_n`.
- `MiniGraphFirstRetriever` derives and normalizes the effective discourse-visible budget as `discourse_selection_k`.

Invariant:
- `top_n` is the final answer context budget.
- Default `top_n=6` means final answer contexts are bounded to 6.
- When no explicit discourse budget override is provided, the effective `discourse_selection_k` defaults to `2 * top_n`.
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

## Application Service Boundary Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `QueryModeRouter`, `QueryService`, `MiniGraphFirstRetriever`

Invariant:
- `QueryModeRouter` dispatches by query mode only; retrieval, evidence, and answer logic stay in downstream services.
- `QueryService` remains generic over `Retriever` + `Answerer`; do not couple it to graph-first or provider-specific internals.
- `GraphFirstSourceSelection` is an internal application contract; downstream collaborators may consume its metadata, but public API surfaces must not expose its full internal shape.

Forbidden stale interpretations:
- Do not move retrieval-strategy knobs or graph-first internals into HTTP query-mode dispatch.
- Do not treat service-local orchestration metadata as a public API contract unless the API layer documents it explicitly.
