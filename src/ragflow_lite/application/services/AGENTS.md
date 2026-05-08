# AGENTS.md
Last updated: 2026-05-08T14:30:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只保留服务导航、本地命令和所有权指引；运行不变量见本地契约文件。

这个目录承接 query、document、dataset 和 DiscoRAG 的 application service。它编排 domain ports，不拥有 HTTP 或底层 adapter。

## 关键命令
```bash
rtk cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --kind class
rtk cx references --name QueryService --file src/ragflow_lite/application/services/query_service.py --unique
```

- `QueryService` is intentionally generic and knows only `Retriever` + `Answerer`.
- `DiscoRAGQueryService` owns the DiscoRAG sequence (retrieval → evidence → intra-chunk discourse → inter-chunk graph → blueprint → answer) but delegates each step to a collaborator.
- `MiniGraphFirstRetriever` owns graph-first retrieval and `GraphFirstSourceSelection`.
- `EvidencePackageBuilder` carries source-selection metadata into evidence items and package metadata, including supplemental discourse chunks from retriever metadata.
- `DeterministicInterChunkDiscourseGraphBuilder` builds a sparse chunk-level graph from explicit metadata and shared topology heuristics.
- `DiscoRAGAnswerBlueprintBuilder` consumes the inter-chunk graph to produce relation-aware constraints and plan steps.
- `DocumentService` and `DatasetService` are application wrappers around catalog/store semantics, not storage implementations.

## 边界提示
- Runtime behavior for these services lives in [../CONTRACTS.md](../CONTRACTS.md).
- Keep this file for service ownership, code navigation, and "edit the right layer" warnings only.
