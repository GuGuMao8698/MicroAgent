# AGENTS.md
Last updated: 2026-05-08T15:10:00+08:00

Active contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只保留服务导航、本地命令和所有权指引；运行不变量见本地契约文件。

这个目录存放 query、document、dataset 和 DiscoRAG 相关的 application service 文件。

## 关键命令
```bash
rtk cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --kind class
rtk cx references --name QueryService --file src/ragflow_lite/application/services/query_service.py --unique
```

## 文件地图
- [query_service.py](query_service.py): standard query service.
- [discorag_query_service.py](discorag_query_service.py): DiscoRAG query service.
- [query_mode_router.py](query_mode_router.py): query mode router.
- [mini_graph_first_retriever.py](mini_graph_first_retriever.py): graph-first retriever service.
- [evidence_package_builder.py](evidence_package_builder.py): evidence package helper.
- [inter_chunk_discourse_graph_builder.py](inter_chunk_discourse_graph_builder.py): inter-chunk discourse graph helper.
- [discorag_answer_blueprint_builder.py](discorag_answer_blueprint_builder.py): DiscoRAG answer blueprint helper.
- [document_service.py](document_service.py): document service.
- [dataset_service.py](dataset_service.py): dataset service.
- [text_normalization.py](text_normalization.py): text normalization helpers.
- [_query_observability.py](_query_observability.py): query observability helpers.

## 边界提示
- 本文件只保留服务导航、本地命令、文件角色和错层提醒。
