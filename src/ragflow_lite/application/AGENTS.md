# AGENTS.md

## Purpose
这个目录负责业务编排层，承接 ingestion/query 两条主流程和跨模块协调。

## Do Here
- 在这里组织 `IngestionPipeline`、`QueryService` 和文本归一化。
- 通过抽象 port 协调 parser、chunker、embedder、index、answerer。
- 保持输入输出清晰，便于路由层调用和测试。

## Avoid Here
- 不要在这里直接写 FastAPI 路由或请求模型。
- 不要把具体 parser、embedder、vector index 实现写进这里。
- 不要在这里提前设计异步任务、重试、状态机或 citation 组装。
