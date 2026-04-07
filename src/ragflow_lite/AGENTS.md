# AGENTS.md

## Purpose
这个目录承接当前最小后端实现。V1 已完成，当前演进 V2 检索质量增强能力。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕主链路演进：上传、解析、切块、索引、查询、回答。
- 当前默认检索后端是 Infinity hybrid path（`InfinityHybridRetriever`），通过 `InfinityDenseVectorIndex.search_hybrid()` 一次调用完成全文 + dense 并行检索，复用 Infinity 原生 `weighted_sum` fusion。pure dense / pure fulltext 仅保留为 index 层内部回归/诊断能力，不再作为公共运行时模式暴露。
- V1 已落地：基础 inline citation、文档 metadata 读写闭环（只读 API，`DocumentCatalog` + `GET /documents`）。
- 本阶段不引入 Postgres 状态管理。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、rerank、dataset 管理、异步 pipeline 提前塞进当前实现。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`。
