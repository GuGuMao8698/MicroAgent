# AGENTS.md

这个目录目前只有 package marker。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 注意
- 不要把新 loader 放到这里，除非先确认它是稳定基础设施边界。
- 当前 upload/document byte handling 在 `infrastructure/storage` 和 application ingestion。
- Parser dispatch 在 `infrastructure/parsers`。
- 不要把这里当作一次性 import scripts 或 fixture loaders 的堆放地。
