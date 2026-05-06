# AGENTS.md

这个目录提供 ingestion task 的单进程内存实现。它是 runtime adapter，不是分布式队列。

- `InMemoryTaskStore` tracks task state and idempotency key ownership.
- `InMemoryStageCache` stores parse/chunk stage artifacts only.
- `InlineTaskRunner` is synchronous and useful for tests.
- `BackgroundTaskRunner` is the default in-process async runner for app wiring.
- These implementations are thread-safe in-process helpers; they do not provide cross-process, durable, or distributed queue guarantees.
- Keep idempotency reservation atomic from the application perspective.
- Do not cache embed/index/provider side effects in stage cache.
- Runner handlers must receive document ids and let `IngestionPipeline.process_task()` own business transitions.
- Do not add database, broker, or persistence dependencies here without explicit approval.
