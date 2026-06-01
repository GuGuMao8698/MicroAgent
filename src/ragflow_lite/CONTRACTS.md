# Package-Level Active Contracts

This file owns active runtime contracts for `src/ragflow_lite`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Active Module Contracts

Child modules that own their own CONTRACTS.md:

- [api/CONTRACTS.md](api/CONTRACTS.md) -- HTTP surface, endpoints, schemas, status codes, observability
- [application/CONTRACTS.md](application/CONTRACTS.md) -- DiscoRAG budget, service boundary
- [infrastructure/CONTRACTS.md](infrastructure/CONTRACTS.md) -- adapter defaults, provider wiring, embedding/vector-index contracts

## Package Boundary Contract

Reviewed at: `2026-05-08T16:00:00+08:00`
Status: Active

Source of truth:
- Package name: `ragflow_lite` (internal Python package).
- Environment variable prefix: `RAGFLOW_LITE_*`.
- API prefix: `/api/v0` (configurable via `Settings.api_prefix`).

Mode routing and provider wiring:
- Default query path and dispatch semantics are owned by [application/CONTRACTS.md](application/CONTRACTS.md).
- Infinity hybrid chunk retrieval is an auxiliary retrieval capability, not an independently selectable HTTP strategy.
- Retrieval mode is fixed to hybrid; `RAGFLOW_LITE_RETRIEVAL_MODE` is rejected at startup if set.
- All runtime provider config comes from host environment (`DEEPSEEK_API_KEY`, `ARK_API_KEY`, `ARK_EMBEDDING_MODEL`); no secrets are read from or committed in the source tree.
- `Settings.require_runtime_provider_configs()` validates required env vars at startup and raises if missing.
- Optional Ark VLM figure description is gated by `MICRORAG_FIGURE_VLM_ENABLED` (default `false`) and requires `ARK_FIGURE_MODEL` when enabled. Wiring details are in [infrastructure/CONTRACTS.md](infrastructure/CONTRACTS.md).
- Media asset store root is `data/media/pdf-assets` under the project root.

Layering:
- HTTP surface is only in `api`.
- Business orchestration is only in `application`.
- Stable domain objects and ports are only in `domain`.
- External SDK, Infinity, filesystem, and provider details are only in `infrastructure`.
- `shared` is restricted to cross-cutting helpers (logging, request context, metrics); it must not hold business orchestration, provider calls, or routing control flow.

## Documentation Rule

All active runtime contracts in this subtree follow the governance standard:
source-backed, dated, owned, and verifiable. See [docs/agent-doc-governance.md](../../docs/agent-doc-governance.md)
for the full governance standard. AGENTS.md files in child directories must not duplicate
active semantics; they may only point to the nearest CONTRACTS.md.
