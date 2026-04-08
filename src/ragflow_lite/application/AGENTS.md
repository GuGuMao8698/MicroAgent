# AGENTS.md

## Purpose
这个目录负责业务编排层，承接 ingestion/query 两条主流程和跨模块协调。

## Do Here
- 在这里组织 `IngestionPipeline`、`QueryService`、`DocumentService`、`Retriever` 和文本归一化。
- 通过抽象 port 协调 parser、chunker、embedder、index、retriever、answerer、document catalog。
- `IngestionPipeline` 负责把 parser 提供的逐页文本对齐到归一化后的 `page_spans`，并透传 / 持久化 `parser_strategy` metadata；不在这里做 citation 格式化或 parser 选择。
- `DocumentService` 透传 `DocumentCatalog` 的 list/get 语义，不引入额外策略分支。
- `QueryService` 继续只依赖 `Retriever` 协议，不感知具体检索实现或 fusion 细节。
- `IngestionPipeline` / `QueryService` 负责主链路阶段日志和业务指标（如 ingest/query outcome），但只记录安全字段，不记录原始文档内容或完整 query 文本。
- rollback 保持 best-effort：分别尝试清理 `vector_index` 与 `document_store`，失败时记录 `rollback_failed` 日志但不覆盖原始业务异常。
- 保持输入输出清晰，便于路由层调用和测试。

## Avoid Here
- 不要在这里直接写 FastAPI 路由或请求模型。
- 不要把具体 parser、embedder、vector index 实现写进这里。
- 不要在这里做复杂 citation/rerank/异步任务编排。
- 不要在 application 层硬编码检索模式判断，也不要下沉 hybrid / fusion 细节。
- 不要记录原始 query/document 内容，也不要把高基数字段推进 metrics label。
