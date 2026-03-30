# AGENTS.md

## Purpose
这个目录承接当前最小后端实现，并开始演进 V1 检索与元数据能力。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕主链路演进：上传、解析、切块、索引、查询、回答。
- 优先拆清 retrieval 边界，再按 V1 当前范围接入 Infinity 全文检索、hybrid retrieval、基础 citation 和文档元数据。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、rerank、dataset 管理、异步 pipeline 提前塞进当前实现。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`。
