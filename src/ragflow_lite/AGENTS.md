# AGENTS.md

## Purpose
这个目录承接当前最小后端实现，并开始演进 V1 检索与元数据能力。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕主链路演进：上传、解析、切块、索引、查询、回答。
- 当前默认检索后端是 Infinity dense path（`InfinityDenseVectorIndex`），已支持 full-text 检索基线（`RAGFLOW_LITE_RETRIEVAL_MODE=fulltext`），hybrid 为下一步。
- 保持现有分层不变，优先做默认检索后端替换和最小元数据落盘。
- 本阶段不引入 Postgres 状态管理。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、rerank、dataset 管理、异步 pipeline 提前塞进当前实现。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`。
