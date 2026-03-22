# AGENTS.md

## Purpose
这个目录负责业务编排层，承接 use case、pipeline 和跨模块协调。

## Do Here
- 在这里组织 `IngestionPipeline` 和查询回答用例。
- 通过抽象 port 协调多个模块，而不是依赖具体实现细节。
- 保持 use case 输入输出清晰，便于路由层调用和测试。

## Avoid Here
- 不要在这里直接写 FastAPI 路由或请求模型。
- 不要把具体 parser、embedder、vector index 实现写进这里。
- 不要让该层反向依赖 `infrastructure` 的具体细节。
