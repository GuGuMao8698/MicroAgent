# AGENTS.md

## Purpose
这个目录负责底层实现，承接 parser、chunker、embedder、vector index、answerer、storage 等具体能力。

## Do Here
- 在这里实现 `domain/ports` 定义的抽象接口。
- 默认向量索引主路径是 `InfinityDenseVectorIndex`，承接 dense vector search 和最小文档元数据读写。
- `LocalJsonVectorIndex` 仍保留但不再作为默认主路径。
- 当前 embedding 维度契约是 `2048`。
- Infinity SDK 的 `to_pl()` 返回 `(polars.DataFrame, extra_dict)` 元组；`show_columns()` 返回 `polars.DataFrame`。
- 外部回答器实现放在 `infrastructure/answerers`，当前默认回答器是 OpenAI Responses answerer。
- 检索器实现放在 `infrastructure/retrievers`，当前默认是纯向量 `VectorRetriever`；retriever 只负责 `embed_query -> vector_index.search` 的单步调用，不承担 hybrid、fusion、rerank 或 citation 组装。
- `InfinityFullTextRetriever` 直接调用 `InfinityDenseVectorIndex.search_text()`，不做 query embedding；通过 `RAGFLOW_LITE_RETRIEVAL_MODE=fulltext` 启用。
- `InfinityDenseVectorIndex` 初始化时对 chunk 表的 `text` 列幂等创建全文索引（`<chunk_table>_text_fulltext_idx`），`search_text()` 调用 `match_text` 做全文匹配。
- 当前的 embedding 运行时实现就是 Ark 文本 embedding，索引会记录 embedding 签名。
- grounded answer 必须基于 retrieval contexts，不要把外部模型调用扩散到 `api` 或 `application`。
- 允许实现最小 `BasicPdfParser`，使用轻量依赖（`pypdf`）完成数字原生 PDF 的基础文本抽取。
- 本阶段不引入 hybrid、rerank、Postgres persistence。全文检索基线已落地。

## Avoid Here
- 不要在这里定义业务流程和用例编排。
- 不要反向决定 `domain` 的边界。
- 不要因为当前只有一个 provider 就提前抽象多 provider 框架，也不要把 provider-specific 配置或密钥处理散落到无关模块。
- 不要提前接入 OCR/layout/table/DeepDoc 级 PDF 栈、rerank、多 provider 扩展、异步任务编排，也不要在 Ark 之外扩散新的 embedding provider 运行时路径。
