# AGENTS.md

## Purpose
这个目录是后端源码根目录，负责承接 V0 的模块化分层骨架。

## Do Here
- 保持 `api`、`application`、`domain`、`infrastructure` 的清晰分层。
- 让实现与 [V0模块化Pipeline计划.md](/home/xia/ragflow-lite/计划/V0模块化Pipeline计划.md) 对齐。
- 只在这里放后端源码，不把测试夹具、运行数据或临时脚本混进来。

## Avoid Here
- 不要把 V1-V3 的能力提前塞进 V0 骨架。
- 不要跨层放置代码，例如把路由逻辑写进 `domain`，或把业务流程塞进 `api`。
- 不要把“暂时不知道放哪”的代码默认丢进 `shared`。
