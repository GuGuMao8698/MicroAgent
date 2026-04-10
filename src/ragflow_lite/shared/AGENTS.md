# AGENTS.md

## Purpose
这个目录只承接跨层复用、且不属于某一业务层的轻量基础能力。

## Do Here
- 放 request/trace context、logging formatter、结构化日志 helper、Prometheus helper 这类真正 cross-cutting 的 observability 代码。
- 保持 helper 小而稳定，优先服务现有主链路，而不是为未来抽象通用平台。
- 让这里的 API 保持无业务语义，便于 `api` / `application` / `infrastructure` 共同复用。

## Avoid Here
- 不要把业务流程、路由编排、provider 调用或 repository 逻辑放进来。
- 不要为了“方便复用”把半个 application 层搬进 `shared`。
- 不要在这里引入重量级 observability framework 或新的公共运行时路径。
