# AGENTS.md

## Purpose
这个目录承接当前最小 V0 后端实现，只服务 `txt` / `md` / `pdf` 同步 RAG 闭环。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现围绕最小主链路演进：上传、解析、切块、索引、查询、回答。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。

## Avoid Here
- 不要把 OCR/layout/table/DeepDoc、`Infinity`、hybrid retrieval、citation、异步 pipeline 提前塞进当前实现。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把”暂时不知道放哪”的代码默认丢进 `shared`。
