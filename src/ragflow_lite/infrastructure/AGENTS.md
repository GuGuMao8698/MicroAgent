# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 默认向量索引主路径是 `InfinityDenseVectorIndex`，承接 dense vector search、hybrid retrieval 和 `DocumentCatalog` 文档目录读路径。`index_document()` 写入 `asset.metadata` 到 `parser_metadata_json`；`list_documents()` / `get_document()` 提供只读目录语义。
- `LocalJsonVectorIndex` 仍保留但不再作为默认主路径。
- 当前 embedding 维度契约是 `2048`。
- Infinity SDK 的 `to_pl()` 返回 `(polars.DataFrame, extra_dict)` 元组；`show_columns()` 返回 `polars.DataFrame`。
- 外部回答器实现放在 `infrastructure/answerers`，当前默认回答器是 OpenAI Responses answerer。
- 检索器实现放在 `infrastructure/retrievers`，当前生产 retriever 是 `InfinityHybridRetriever`；通过 `embed_query(raw query)` + sparse-query 分析 -> `search_hybrid()` 调用 Infinity 原生 `weighted_sum` fusion，不承担 rerank 或 citation 组装。
- sparse-query 分析只服务全文分支，是 retriever 内部实现细节；dense embedding 仍使用原始 query。
- hybrid sparse 匹配使用 `filename` 与 `text` 两个字段；诊断型 `search_text()` 保持单字段 `text` 语义。
- hybrid 检索内部会先扩大候选，再裁回 `top_k`；这是内部策略，不提升为公共配置。
- OpenAI answerer 负责基于 context 编号的基础 inline citation：prompt 按 score 降序编号 contexts 为 `[1]`..`[n]`，instructions 要求模型使用 `<cite:n>` token 引用，输出后 answerer 将合法 `<cite:n>` 转换为用户可见的 `[n]`，移除越界和非法 token，裸方括号数字不做处理，返回的 `contexts` 顺序与编号对齐。不要提前引入句子级 citation 或 rerank。
- `InfinityDenseVectorIndex.search()` 和 `search_text()` 保留为 index 层内部回归/诊断能力，不重新暴露成独立运行时模式。
- `InfinityDenseVectorIndex` 初始化时对 chunk 表的 `text`、`filename` 列幂等创建全文索引；`search_text()` 调用 `match_text` 做全文匹配。
- 当前的 embedding 运行时实现就是 Ark 文本 embedding，索引会记录 embedding 签名。
- grounded answer 必须基于 retrieval contexts，不要把外部模型调用扩散到 `api` 或 `application`。
- 允许实现最小 `BasicPdfParser`，使用轻量依赖（`pypdf`）完成数字原生 PDF 的基础文本抽取。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要因为当前只有一个 provider 就提前抽象多 provider 框架，也不要把 provider-specific 配置或密钥处理散落到无关模块。
- 不要提前接入 OCR/layout/table/DeepDoc 级 PDF 栈、rerank、多 provider 扩展、异步任务编排，也不要在 Ark 之外扩散新的 embedding provider 运行时路径。
