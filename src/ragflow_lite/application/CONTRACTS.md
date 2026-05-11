# Application Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/application`.
[AGENTS.md](./AGENTS.md) files in this subtree should link here instead of duplicating these
contracts.

## DiscoRAG Structural Pipeline Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `DiscoRAGQueryService`, `LLMDiscoRAGAnswerBlueprintBuilder`

Source of truth:
- Inter-chunk discourse graph is LLM-backed (listwise inference), no deterministic fallback.
- `LLMInterChunkDiscourseGraphBuilder` replaces the former `DeterministicInterChunkDiscourseGraphBuilder`.
- Paper relation set: 21 labels including `unrelated`; 20 non-`unrelated` labels materialize as graph edges.
- `unrelated` is parsed and dropped, never materialized as `InterChunkDiscourseRelation`.
- Graph builder consumes `IntraChunkDiscoursePackage` via the `InterChunkDiscourseGraphBuilder` port (sync).
- Structurer model is configured independently from answer model via `DiscoRAGStructurerRuntimeConfig`.
- Blueprint planner is LLM-backed via `LLMDiscoRAGAnswerBlueprintBuilder`. `DiscoRAGAnswerBlueprintBuilder` is retained only as a test stub.

Invariant:
- Validation failure (unparseable JSON, all relations invalid) must raise `ProcessingError`, not silently return an empty or deterministic graph.
- Single invalid relations are dropped; per-category drop counts are observable in graph metadata.
- LLM model/provider metadata is observable in `graph.metadata["llm"]`.
- Blueprint maps 20 materialized labels to planning semantics: conflict (`contradicts`, `contrasts_with`, `replaces`), support (`supports`, `justifies`), background (`background_for`), elaboration (`elaborates`, `supplements`, `specifies`, `exemplifies`).
- Promotion triggers: `contradicts`, `contrasts_with`, `replaces`. `qualifies` is not in the paper set and no longer triggers promotion.
- RST signals (nuclearity, planning_role, rst_relation) influence blueprint constraints and lead selection when compatible with graph-derived ordering.
- Blueprint planner validation failure raises `ProcessingError`; no deterministic blueprint fallback in runtime.
- Answerer blueprint fallback (missing/invalid blueprint → score ordering) is a defensive last line with observable reason (`missing_blueprint`, `invalid_blueprint`). It is NOT a planner fallback; partially invalid blueprints (containing unknown chunk IDs) are treated as invalid.

Forbidden stale interpretations:
- Do not retain or reintroduce `DeterministicInterChunkDiscourseGraphBuilder` as runtime fallback.
- Do not reintroduce `DiscoRAGAnswerBlueprintBuilder` as runtime planner (test-only stub).
- Do not treat `qualifies` as a valid inter-chunk relation label for promotion or constraints.
- Do not treat `chunk_token_budget` or `context_token_budget` as required DiscoRAG behavior.
- Do not use [docs/superpowers/plans](../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py](../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py](../../../tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py)
- [tests/unit/application/test_discorag_answer_blueprint_builder.py](../../../tests/unit/application/test_discorag_answer_blueprint_builder.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../tests/unit/application/test_discorag_local_smoke.py)
- [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)

## DiscoRAG Budget Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `MiniGraphFirstRetriever`, `DiscoRAGQueryService`

Source of truth:
- Public final answer context budget: normalized `QueryRequest.top_n` after `top_k` alias handling.
- `MiniGraphFirstRetriever` derives the effective discourse-visible budget per request; the resulting `GraphFirstSourceSelection.discourse_selection_k` records that budget.

Invariant:
- `QueryRequest.top_n` is normalized before application services consume the request.
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
- Do not use historical [docs/superpowers/plans](../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/application/test_mini_graph_first_retriever.py](../../../tests/unit/application/test_mini_graph_first_retriever.py)
- [tests/unit/application/test_discorag_query_service.py](../../../tests/unit/application/test_discorag_query_service.py)
- stale scan for `max_chunks: int = 5` and `discourse_selection_n == top_n`

## Application Service Boundary Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `QueryModeRouter`, `QueryService`, `MiniGraphFirstRetriever`

Invariant:
- `QueryModeRouter` dispatches by query mode only; retrieval, evidence, and answer logic stay in downstream services.
- `QueryService` remains generic over `Retriever` + `Answerer`; do not couple it to graph-first or provider-specific internals.
- `GraphFirstSourceSelection` is an internal application contract; downstream collaborators may consume its metadata, but public API surfaces must not expose its full internal shape.

## DiscoRAG Degraded Fallback Contract

Reviewed at: `2026-05-11T12:00:00+08:00`
Status: Active
Owner: `DiscoRAGQueryService`

Source of truth:
- When RST extraction, inter-chunk graph construction, or blueprint planning exhausts structurer attempts, `DiscoRAGQueryService` catches `StructurerAttemptsExhaustedError` and degrades to MiniRAG direct answer.
- Fallback uses `retrieval_result.chunks` exactly as contexts, `mode="standard"`, `blueprint=None`.
- Result metadata includes `discorag_degraded == True` and a user-visible `discorag_error` block from `exc.safe_metadata()` with stage, error_type, failure_type, attempts, max_attempts, message, and `user_visible=True`.
- Fallback does not append supplemental discourse chunks and does not use a blueprint.
- Degraded fallback records success observability (`record_query_outcome("succeeded")`, `query_succeeded` log with `degraded=True`).

Invariant:
- Only `StructurerAttemptsExhaustedError` from structurer stages (rst_extraction, inter_chunk_graph, blueprint) triggers fallback.
- Plain `ProcessingError` from structurer collaborators propagates as hard failure.
- Runtime invariant failures after a valid blueprint (e.g. promotion runtime errors from `_contexts_with_bounded_promotion`, blueprint-context consistency errors from `_blueprint_for_contexts`) remain hard errors and propagate upward.
- Non-`ProcessingError` exceptions also propagate upward and do not trigger fallback.
- Fallback metadata is structured and user-visible without regex parsing.

Forbidden stale interpretations:
- Do not catch all `ProcessingError` for structurer fallback; only `StructurerAttemptsExhaustedError` qualifies.
- Do not treat post-blueprint runtime errors as recoverable; they remain hard errors.
- Do not use regex to extract fallback metadata from exception messages.

Verification:
- [tests/unit/application/test_discorag_query_service.py](../../../tests/unit/application/test_discorag_query_service.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../tests/unit/application/test_discorag_local_smoke.py)
