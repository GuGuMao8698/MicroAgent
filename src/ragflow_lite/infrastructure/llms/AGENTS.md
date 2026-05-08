# AGENTS.md

这个目录封装 non-embedding LLM client。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- Chat Completions client wrapper -- text and JSON completion helpers for answerers, query grounders, evidence extractors
- JSON mode adds required JSON instruction

## Avoid Here
- 不要在 callers 里重复低-level request construction。
- 不要 log prompts、user query text、document chunks、response payloads 或 API keys。
