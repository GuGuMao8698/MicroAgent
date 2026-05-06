# AGENTS.md

这个目录测试 domain models and ports. Keep it small, pure and implementation-free.

- Tests here protect field preservation, default factories, optional fields, and protocol boundaries.
- Domain tests should not need filesystem, FastAPI, Infinity, provider SDKs, or runtime environment variables.
- Do not encode infrastructure behavior in domain tests.
- When adding a domain model, test stable contract fields and mutable default isolation.
- When adding a port, test that it remains a protocol only if that matters to callers.
- Do not assert transient implementation repr/order details unless they are part of the domain contract.
