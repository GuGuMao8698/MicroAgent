# AGENTS.md

## Purpose
这个目录负责 FastAPI HTTP 接口层，只处理入口附近的职责。

## Do Here
- 在 `routes/v0` 放当前 `health`、`documents`、`queries` 接口。
- 在 `schemas` 放请求与响应模型。
- 在 `deps` 放依赖组装、服务获取和路由层适配。
- 查询接口不暴露检索策略参数；HTTP 请求/响应结构保持稳定。

## Avoid Here
- 不要在这里编排 parser、chunking、embedding、index、answer 主流程。
- 不要在路由里直接操作本地存储、JSON 索引或回答策略实现。
- 不要把领域对象和基础设施实现混放到 `api`。
- 不要把 `Infinity` 查询细节或 fusion 参数下沉到路由层。
