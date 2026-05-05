# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 默认向量索引主路径是 `InfinityDenseVectorIndex`，承接 dense vector search、hybrid retrieval、`DocumentCatalog` 文档目录读路径和 `DatasetStore` dataset 管理与绑定。
- `LocalJsonVectorIndex` 仍保留但不再作为默认主路径。
- 当前 embedding 维度契约是 `2048`。
- 外部回答器实现放在 `infrastructure/answerers`，当前有 `DeepSeekChatAnswerer`（DeepSeek Chat Completions）和 `OpenAIResponsesAnswerer`（legacy）。
- 检索器实现放在 `infrastructure/retrievers`，`InfinityHybridRetriever` 作为辅助 chunk 检索器（auxiliary），通过 `embed_query(raw query)` + sparse-query 分析 -> `search_hybrid()` 调用 Infinity 原生 `weighted_sum` fusion，不承担 rerank 或 citation 组装。
- query grounding 实现放在 `infrastructure/retrievers/`：`DeepSeekChatQueryGrounder` 通过 DeepSeek Chat Completions 产出 `answer_type_keywords` 和 `entities_from_query`；`OpenAIResponsesQueryGrounder` 保留为 legacy。
- `LocalJsonVectorIndex` 和 `InfinityDenseVectorIndex` 均已实现 `get_chunks(chunk_ids)` 方法，供拓扑检索回收 chunk 文本。
- `infrastructure/evidence` 承接 evidence 相关具体实现：ingestion 侧 graph evidence extractor/store 与 graph candidate sidecar，query-time canonical graph evidence view（跨文档同名实体/有向边合并）、hybrid entity/relationship candidate retrieval + BFS path expansion，以及 query-time intra-chunk discourse extractor。保持 provider 调用、持久化和验证逻辑各自收敛，不把阶段状态写成长期说明。
- sparse-query 分析只服务全文分支，是 retriever 内部实现细节；dense embedding 仍使用原始 query。
- hybrid sparse 匹配使用 `filename` 与 `text` 两个字段；诊断型 `search_text()` 保持单字段 `text` 语义。
- hybrid 检索内部可以扩大候选后再裁回 `top_k`，但这些调优仍是内部策略；不要把已收口的 V2 检索细节提升为公共配置，也不要引入 rerank、tag API 或额外主路径。
- 保持现有 inline citation、PDF 页感知 citation 和 parser strategy baseline 稳定；需要引用精确快照时看归档和测试，不在本文件重复展开内部 metadata 细节。
- 当前 parser baseline 仍是 `txt`、`md`、`pdf` 的现有原生解析路径；`pdf` 继续走数字原生文本，不做 OCR fallback。
- 低层实现只在明确的异常翻译/吞异常边界记录日志，例如 `parser_failed`、`local_index_write_failed`、startup/rollback failure；不记录原始文档/查询内容。
- `infrastructure/ingestion/` 提供单进程 in-memory 实现：`InMemoryTaskStore`、`InMemoryStageCache`、`InlineTaskRunner`（线程安全，支持 handler 注入）。这些是进程内实现，不提供跨进程或持久化保证。
- 应用层负责主链路级日志与业务 outcome；infra 不扩散为全量 provider debug trace，也不在每个 helper 上加噪声日志。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要因为当前只有一个 provider 就提前抽象多 provider 框架，也不要把 provider-specific 配置或密钥处理散落到无关模块。
- 不要提前接入 OCR/layout/table/DeepDoc 级 PDF 栈、rerank、多 provider 扩展，也不要在 Ark 之外扩散新的 embedding provider 运行时路径。非 embedding LLM 已迁移至 DeepSeek Chat Completions（`infrastructure/llms/`）。
- 不要把 provider request/response payload、原始文本或高基数字段写进日志。
