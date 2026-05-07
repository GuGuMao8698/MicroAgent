# AGENTS.md

这个目录承接 query、document、dataset 和 DiscoRAG 的 application service。它编排 domain ports，不拥有 HTTP 或底层 adapter。

## 关键命令
```bash
rtk cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --kind class
rtk cx references --name QueryService --file src/ragflow_lite/application/services/query_service.py --unique
```

- `QueryService` is intentionally generic and knows only `Retriever` + `Answerer`.
- `DiscoRAGQueryService` owns the DiscoRAG sequence (retrieval → evidence → intra-chunk discourse → inter-chunk graph → blueprint → answer) but delegates each step to a collaborator.
- `MiniGraphFirstRetriever` owns query grounding, graph candidate lookup, path expansion, auxiliary chunk retrieval, scoring and `GraphFirstSourceSelection`. The default discourse window is `2 * top_k` (via `_DEFAULT_DISCOURSE_SELECTION_MULTIPLIER`); supplemental discourse chunks are retained in `result.metadata["supplemental_discourse_chunks"]`.
- `EvidencePackageBuilder` carries source-selection metadata into evidence items and package metadata, including supplemental discourse chunks from retriever metadata.
- `DeterministicInterChunkDiscourseGraphBuilder` builds a sparse chunk-level graph from explicit metadata (`inter_chunk_relation_type` / `inter_chunk_target_chunk_id`) and shared topology metadata. It supports 6 relation types via `_RELATION_TYPES` (`qualifies`, `supports`, `background_for`, `elaborates`, `example_of`, `contradicts`). Explicit metadata takes precedence over the shared-topology heuristic. It is the first implementation of the `InterChunkDiscourseGraphBuilder` port; LLM-backed builders may follow.
- `DiscoRAGAnswerBlueprintBuilder` consumes the inter-chunk graph to add relation-type-aware constraints and plan steps. `contradicts` triggers a dedicated caution; `qualifies` adds a qualification constraint; non-promoting types (`supports`, `background_for`, `elaborates`, `example_of`) add usage guidance only. Promotion (`promoted_chunk_ids`) is limited to `qualifies` and `contradicts`, and is bounded replacement, not append. The answer-facing blueprint (`_blueprint_for_contexts`) is filtered to only reference final answer context chunks.
- `DocumentService` and `DatasetService` are application wrappers around catalog/store semantics, not storage implementations.

## 关键约定
- Do not expose retrieval/fusion strategy knobs through HTTP or service DTOs.
- Keep `GraphFirstSourceSelection` internal; downstream code may consume its metadata, but API responses must not depend on its full shape.
- `QueryModeRouter` rejects unknown runtime modes and must not duplicate query business logic.
- `MiniGraphFirstRetriever` scoring stays aligned with MiniRAG mini-mode Counter/vote behavior; do not reintroduce local weight tuning unless that task is explicit.
- No-path entity candidates (those without relation-backed `TopologyPath`) are retained via `_merge_trimmed_no_path_candidates()` at top 20% (minimum 1) before path truncation; `no_path_candidate` is a recognized score component. Do not bypass this merge or move it after `_score_source_chunks()`.
- `discourse_selection_n` defaults to `2 * top_k` when not explicitly set; supplemental chunks are stored in retriever metadata, not in answer contexts. Do not confuse it with graph candidate or final context budgets.
- Discourse extraction should consume `selected_for_discourse=True` evidence first, then fill from original order if needed.
- Promotion (`promoted_chunk_ids`) is bounded replacement: promoted supplemental chunks replace the weakest answer contexts within the original budget (`len(retrieval_result.chunks)`). It is NOT append. Only `qualifies` and `contradicts` are promotable; `supports`, `background_for`, `elaborates`, `example_of` affect constraints only.
- `DocumentService` validates dataset existence before filtering, binding, or rebinding.
- `DatasetService` strips names and rejects empty names.
- Observability helpers log bounded outcome fields only; never log raw document bodies, full query text, or high-cardinality metrics labels.
