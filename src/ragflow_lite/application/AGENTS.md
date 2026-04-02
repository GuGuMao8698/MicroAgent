# AGENTS.md

## Purpose
这个目录负责业务编排层，承接 ingestion/query 两条主流程和跨模块协调。

## Do Here
- 在这里组织 `IngestionPipeline`、`QueryService`、`Retriever` 和文本归一化。
- 通过抽象 port 协调 parser、chunker、embedder、index、retriever、answerer。
- 编排"查询 -> 检索 -> 回答"主流程，允许编排基础 citation 的来源传递。
- `QueryService` 继续只依赖 `Retriever` 协议，不感知 `dense` / `fulltext` 的具体实现。
- 保持输入输出清晰，便于路由层调用和测试。

## Avoid Here
- 不要在这里直接写 FastAPI 路由或请求模型。
- 不要把具体 parser、embedder、vector index 实现写进这里。
- 不要在这里做复杂 citation/rerank/异步任务编排。
- 不要在 application 层硬编码检索模式判断，也不要提前做 hybrid / fusion 编排。
