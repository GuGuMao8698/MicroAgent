# AGENTS.md

这个目录封装 RAGFlow tokenizer backend。它 supports sparse/fulltext fields and query text analysis.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Public helpers: `tokenize()` and `fine_grained_tokenize()`
- Backend loading errors raise `RAGFlowTokenizerUnavailableError`
- Tokenizer dependency is isolated here for testability

## Avoid Here
- 不要为 sparse fields 静默 fallback 到其他 tokenizer。
- Query normalization 规则属于 [../retrievers/query_analysis.py](../retrievers/query_analysis.py)，不在这里。
- 不要 log raw user queries 或 document text。
