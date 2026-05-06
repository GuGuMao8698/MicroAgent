# AGENTS.md

这个目录承接 query、document、dataset 和 DiscoRAG 的 application service。它编排 domain ports，不拥有 HTTP 或底层 adapter。

## 关键命令
```bash
rtk cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --kind class
rtk cx references --name QueryService --file src/ragflow_lite/application/services/query_service.py --unique
```

- `QueryService` is intentionally generic and knows only `Retriever` + `Answerer`.
- `DiscoRAGQueryService` owns the DiscoRAG sequence but delegates each step to a collaborator.
- `MiniGraphFirstRetriever` owns query grounding, graph candidate lookup, path expansion, auxiliary chunk retrieval, scoring and `GraphFirstSourceSelection`.
- `EvidencePackageBuilder` carries source-selection metadata into evidence items and package metadata.
- `DocumentService` and `DatasetService` are application wrappers around catalog/store semantics, not storage implementations.

## 关键约定
- Do not expose retrieval/fusion strategy knobs through HTTP or service DTOs.
- Keep `GraphFirstSourceSelection` internal; downstream code may consume its metadata, but API responses must not depend on its full shape.
- `QueryModeRouter` rejects unknown runtime modes and must not duplicate query business logic.
- `MiniGraphFirstRetriever` scoring stays aligned with MiniRAG mini-mode Counter/vote behavior; do not reintroduce local weight tuning unless that task is explicit.
- `discourse_selection_n` defaults to answer budget semantics; do not confuse it with graph candidate or final context budgets.
- Discourse extraction should consume `selected_for_discourse=True` evidence first, then fill from original order if needed.
- `DocumentService` validates dataset existence before filtering, binding, or rebinding.
- `DatasetService` strips names and rejects empty names.
- Observability helpers log bounded outcome fields only; never log raw document bodies, full query text, or high-cardinality metrics labels.
