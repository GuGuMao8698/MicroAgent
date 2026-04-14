# AGENTS.md

## Purpose
这个目录负责 FastAPI HTTP 接口层，只处理 HTTP 入口附近的职责。

## Do Here
- 在 `routes/v0` 放当前对外 HTTP surface：`health`、`POST /documents`（ingestion，必须携带 `Idempotency-Key` header，提交后立即返回 `202 Accepted` + `Location` header，不等待索引完成）、`GET /documents`（文档列表，可选 `dataset_id` 查询参数过滤）、`GET /documents/{id}`（文档详情；异步 ingestion 的轮询入口，返回任务状态 + 可选 catalog 数据）、`PATCH /documents/{id}/dataset`（重绑/解绑）、`POST /queries`（查询）、`POST /datasets`、`GET /datasets`、`GET /datasets/{id}`、`DELETE /datasets/{id}`（dataset CRUD）。
- 在 `schemas` 放请求与响应模型（含 `DocumentResponse`、`DocumentListResponse`、`DocumentIngestionResponse`（202）、`DocumentDetailResponse`、`DocumentTaskResponse`）。
- 在 `deps` 放依赖组装、服务获取和路由层适配。
- 查询接口不暴露检索策略参数；HTTP 请求/响应结构保持稳定。
- 文档读取接口通过 `DocumentService` -> `DocumentCatalog` 获取数据，未知 `document_id` 返回 `404`。
- `POST /documents` 缺少 `Idempotency-Key` header 时返回 `400`；命中相同 key 时复用已有异步任务身份，而不是新建上传任务。
- 默认 app wiring 下，`POST /documents` 只负责接受上传并入队；客户端通过 `GET /documents/{id}` 轮询到终态。
- 路由层负责 request context / trace header 绑定与回写、HTTP 错误映射日志（`request_error` warning）、未处理异常边界日志（`request_unhandled_exception` error），以及可选 `/metrics` 路由注册。
- HTTP metrics 只记录低基数 label；`route` 必须优先使用模板路径，不把 `document_id`、query、文件名等高基数值写进 label。
- 保持响应结构稳定，不在路由层发散业务日志，也不在这里拼业务指标。

## Avoid Here
- 不要在这里编排 parser、chunking、embedding、index、answer 主流程。
- 不要在路由里直接操作本地存储、JSON 索引或回答策略实现。
- 不要把领域对象和基础设施实现混放到 `api`。
- 不要把 `Infinity` 查询细节或 fusion 参数下沉到路由层。
