# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 把和文件系统、本地向量表示、JSON 索引、markdown 解析有关的实现放在这里。
- 外部回答器实现放在 `infrastructure/answerers`，当前默认回答器是 OpenAI Responses answerer。
- 检索器实现放在 `infrastructure/retrievers`，当前默认是纯向量 `VectorRetriever`；retriever 只负责 `embed_query -> vector_index.search` 的单步调用，不承担 hybrid、fusion、rerank 或 citation 组装。
- 当前的 embedding 运行时实现就是 Ark 文本 embedding，本地 JSON 索引会记录 embedding 签名。
- grounded answer 必须基于 retrieval contexts，不要把外部模型调用扩散到 `api` 或 `application`。
- 允许实现最小 `BasicPdfParser`，使用轻量依赖（`pypdf`）完成数字原生 PDF 的基础文本抽取。
- 允许实现 V1 所需的最小全文索引、混合检索支撑和文档元数据落盘/读取能力。
- 当前只服务最小本地向量路径，但接口上保留后续替换空间。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要因为当前只有一个 provider 就提前抽象多 provider 框架，也不要把 provider-specific 配置或密钥处理散落到无关模块。
- 不要提前接入 OCR/layout/table/DeepDoc 级 PDF 栈、rerank、多 provider 扩展、异步任务编排，也不要在 Ark 之外扩散新的 embedding provider 运行时路径。
