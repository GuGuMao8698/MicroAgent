# AGENTS.md

这个目录提供 ingestion task 的单进程内存实现。它是 runtime adapter，不是分布式队列。

## Active Contracts
Runtime contracts: [../CONTRACTS.md](../CONTRACTS.md)。本文件只负责导航和命令指引，不重复运行契约。

## 文件说明
- `InMemoryTaskStore` -- tracks task state and idempotency key ownership
- `InMemoryStageCache` -- stores parse/chunk stage artifacts only
- `InlineTaskRunner` -- synchronous, useful for tests
- `BackgroundTaskRunner` -- in-process async runner

## Avoid Here
- 这些实现是 thread-safe in-process helpers；不提供跨进程、持久化或分布式队列保证。
- 不要添加 database、broker 或 persistence 依赖。
