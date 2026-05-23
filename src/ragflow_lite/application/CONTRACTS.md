# Application Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/application`.
[AGENTS.md](./AGENTS.md) files in this subtree should link here instead of duplicating these
contracts.

## DiscoRAG Structural Pipeline Contract

Reviewed at: `2026-05-22T16:54:51+08:00`
Status: Active
Owner: `DiscoRAGQueryService`, `LLMDiscoRAGAnswerBlueprintBuilder`

Source of truth:
- `DiscoRAGQueryService` orchestrates MiniRAG retrieval, RST extraction, inter-chunk graph construction, blueprint planning, and answer assembly.
- Runtime structurer collaborators are LLM-backed; application services do not provide deterministic graph or blueprint planner fallbacks.
- Detailed planner/parser semantics live in [../infrastructure/evidence/CONTRACTS.md](../infrastructure/evidence/CONTRACTS.md).

Invariant:
- Upstream graph/blueprint validation failures propagate as `ProcessingError`; application services must not silently replace them with empty or deterministic planner outputs.
- Answerer blueprint fallback (missing/invalid blueprint → score ordering) is a defensive last line with observable reason (`missing_blueprint`, `invalid_blueprint`). It is NOT a planner fallback; partially invalid blueprints (containing unknown chunk IDs) are treated as invalid.
- `_blueprint_for_contexts()` remains a hard runtime invariant; complete final-context coverage failures should normally be rejected earlier by `parse_llm_discorag_blueprint()`.

Forbidden stale interpretations:
- Do not document evidence-layer parser, label, promotion-trigger, or RST-planning semantics here; keep them in [../infrastructure/evidence/CONTRACTS.md](../infrastructure/evidence/CONTRACTS.md).
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

## Contract E: MiniRAG Retrieval Rewrite Contract

Reviewed at: 2026-05-14
Status: Active
Owner: `MiniGraphFirstRetriever`

### Source of truth
`MiniGraphFirstRetriever.retrieve_context()`, `retrieval_rewrite.py` helpers, CoT grounding rewriters.

### Invariant
- Retrieval rewrite is an internal MiniRAG capability owned by `MiniGraphFirstRetriever`.
- `/queries` does not expose a rewrite strategy field; routing remains `standard` or `discorag`.
- The deterministic gate uses final answer candidates (`selected_for_answer`), not internal graph/path/discourse-only candidates. Threshold: `selected_answer_candidate_count < ceil(requested_top_n / 2)`.
- `cot_grounding` may produce only explicit `solution_steps`; the grounding layer extracts entities, relations, and answer-type keywords.
- CoT rewrite may run at most once. Post-rewrite assessment may mark retrieval degraded but must not trigger recursive rewrite.
- If CoT rewrite exhausts attempts, retrieval falls back to the cached initial candidate snapshot and must not rerun raw-query MiniRAG retrieval.
- `DiscoRAGQueryService` receives the resolved MiniRAG retrieval result and does not own rewrite decisions.
- Retrieval rewrite metadata remains a runtime side-channel for callers that need degraded retrieval state.
- `format_retrieval_rewrite_notice` in `infrastructure/answerers/_input_formatting.py` does not emit prompt text; answerer prompts do not include deterministic degraded-retrieval notices.

### Forbidden stale interpretations
- `cot_grounding` does not output entities, relations, or answer-type keywords directly.
- Post-rewrite assessment is observation-only; it never triggers a second rewrite.
- Rewrite failure and DiscoRAG structurer exhaustion are separate fallback paths.
- Do not treat hidden model chain-of-thought as a runtime contract.
- Do not infer retrieval quality warnings from generated answer text; use structured runtime/UI state instead.

### Verification
```
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py tests/unit/application/test_mini_graph_first_retriever.py tests/unit/application/test_discorag_query_service.py -q
```

## Agent Retrieval Service Contract

Reviewed at: 2026-05-15
Status: Active
Owner: `AgentRetrievalService`

### Source of truth
`AgentRetrievalService`, `model_facing_retrieval.py` ordering helpers.

### Invariant
- `AgentRetrievalService` is retrieval-only: it builds answer-facing requests for `standard` and `discorag`, serializes model-facing evidence, and must not call `Answerer.answer()`.
- Standard model-facing contexts use U-shaped score ordering (second-highest moved to tail).
- DiscoRAG model-facing contexts use score-descending ordering with the final blueprint at the payload tail.
- DiscoRAG retrieval requires a non-null blueprint; missing blueprint raises `ProcessingError`.
- Model-facing payload omits `mode`, top-level operational `metadata`, degraded state, source selection, retrieval rewrite state, graph internals, and debug traces.
- Retrieval rewrite low-quality state remains runtime/UI metadata and must not be inserted into answer prompts.

### Forbidden stale interpretations
- Do not call `Answerer.answer()` from the agent retrieval path.
- Do not insert `mode` or operational metadata into model-facing payloads.
- Do not treat `format_retrieval_rewrite_notice()` as producing prompt text; it returns `[]`.

### Verification
```
.venv/bin/python -m pytest tests/unit/application/test_agent_retrieval_service.py tests/unit/application/test_model_facing_retrieval.py -q
```
