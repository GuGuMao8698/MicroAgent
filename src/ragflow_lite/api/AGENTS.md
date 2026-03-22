# AGENTS.md

## Purpose
这个目录负责 HTTP 接口层，只处理 FastAPI 入口附近的职责。

## Do Here
- 在 `routes/v0` 放 V0 接口。
- 在 `schemas` 放请求与响应模型。
- 在 `deps` 放依赖注入、路由层公共依赖和适配。

## Avoid Here
- 不要在这里编排 parser、chunking、embedding、index、answer 主流程。
- 不要在路由里直接操作底层存储或向量检索实现。
- 不要把领域对象和基础设施实现混放到 `api`。
