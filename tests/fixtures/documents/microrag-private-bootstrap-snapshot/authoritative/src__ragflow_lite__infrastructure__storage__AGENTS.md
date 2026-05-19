# AGENTS.md

这个目录实现 local document byte storage。它 stores uploaded source files, not indexes or parsed documents.

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `LocalDocumentStore` -- writes upload bytes under configured local directories, returns `DocumentAsset`
- Used by ingestion before parsing/indexing

## Avoid Here
- 不要在这里存储 embeddings、graph evidence、task state、dataset bindings 或 parsed text。
- 不要从 storage 推断 parser behavior。
- 不要 log raw file content 或写入 secrets/runtime config 到 upload directories。
