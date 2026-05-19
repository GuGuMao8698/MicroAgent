# AGENTS.md

这个目录实现 answerer adapter 和回答 prompt 模板。它只把 `AnswerRequest` 转成 provider 调用并清洗回答。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- answerer adapters -- implement `Answerer` port
- prompt templates -- repo-tracked files (not inline source constants)
- `FALLBACK_ANSWER` -- shared no-context answer

## Avoid Here
- 不要添加 retrieval、rerank 或 evidence selection 逻辑。
- 不要 log provider payloads、raw contexts、full query text 或 generated answers。
