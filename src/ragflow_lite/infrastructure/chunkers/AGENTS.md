# AGENTS.md

这个目录实现 document chunking。它 consumes normalized `ParsedDocument` and emits stable `Chunk` objects.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `RecursiveCharacterChunker` -- preserves paragraph/CJK punctuation behavior
- `FixedWindowChunker` -- simple baseline
- Both propagate document metadata, excluding internal parser metadata keys

## Avoid Here
- 不要在 chunker 里做 parsing、normalization、embedding、indexing 或 citation formatting。
