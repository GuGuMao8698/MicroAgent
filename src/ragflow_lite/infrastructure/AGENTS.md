# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 把和文件系统、本地向量表示、JSON 索引、markdown 解析有关的实现放在这里。
- 当前只服务最小本地向量路径，但接口上保留后续替换空间。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要提前接入 `pdf`、外部 embedding API、Infinity 或异步任务编排。
