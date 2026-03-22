# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage、loader 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 把和外部系统、文件系统、模型服务、索引后端有关的实现放在这里。
- 为后续 `Infinity` 和 hybrid retrieval 预留扩展点，但当前只服务 V0 向量路径。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要把 HTTP 路由或请求响应模型放进这里。
