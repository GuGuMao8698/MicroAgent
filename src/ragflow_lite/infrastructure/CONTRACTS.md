# Infrastructure Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/infrastructure`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Scope

Infrastructure adapters implementing `domain.ports`: providers, Infinity,
JSON/file storage, parser, chunker, retriever, and answerer.

Leaf adapter folders that do NOT get their own CONTRACTS.md (too small,
single-purpose):

- [answerers/](answerers/)
- [chunkers/](chunkers/)
- [embedders/](embedders/)
- [ingestion/](ingestion/)
- [llms/](llms/)
- [loaders/](loaders/)
- [nlp/](nlp/)
- [parsers/](parsers/)
- [retrievers/](retrievers/)
- [storage/](storage/)
- [vector_indexes/](vector_indexes/)

## Adapter Boundary Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `build_services` in [../api/deps/providers.py](../api/deps/providers.py)

Default vector index:
- `InfinityDenseVectorIndex` is the default runtime vector index.
- `LocalJsonVectorIndex` is fallback / test-double style storage; it is not the
  default runtime path.

Embedding dimension:
- Current embedding dimension contract is `2048`
  (`Settings.ark_embedding_dimensions`, wired through `ArkEmbeddingRuntimeConfig.dimensions`).
- `EmbeddingSignature` dicts (`{"provider": "ark", "model": ..., "dimensions": ...}`)
  are compatibility guards used at index write time, not documentation-only metadata.

Provider wiring:
- Embedding: `ArkMultimodalTextEmbedder` (Ark SDK).
- Non-embedding LLM: `DeepSeekChatCompletionsClient` via `DeepSeekChatAnswerer`,
  `DeepSeekChatEvidenceExtractor`, `DeepSeekChatIntraChunkDiscourseExtractor`,
  `DeepSeekChatQueryGrounder`.
- Structurer LLM: `LLMInterChunkDiscourseGraphBuilder` and `LLMDiscoRAGAnswerBlueprintBuilder`
  both use `DiscoRAGStructurerRuntimeConfig`, decoupled from the answer model.
- OpenAI Responses adapters (`OpenAIResponsesAnswerer`, `OpenAIResponsesEvidenceExtractor`,
  `OpenAIResponsesQueryGrounder`) remain legacy; they are not the default runtime path.
- Default model: `deepseek-v4-flash` with `reasoning_effort="high"`.

Logging boundary:
- Infrastructure may translate low-level exceptions and log bounded adapter outcomes.
- Application layer owns main workflow outcome logs.

## Chunk Auxiliary Text Fields

Reviewed at: `2026-05-11T16:00:00+08:00`
Status: Active
Owner: `InfinityDenseVectorIndex`, `chunk_text_fields.py`

Source of truth:
- Default chunk auxiliary `match_text` uses only tokenizer-derived fields:
  `filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks`.
- `filename` and `text` remain stored columns, but are not default
  `match_text` fallback fields.
- Chunk tables missing `filename_kwd`, `filename_tks`, `content_tks`, or
  `content_sm_tks` are incompatible and must fail during initialization
  (`_validate_chunk_auxiliary_text_columns` raises `RuntimeError`).

Invariant:
- `CHUNK_FIELD_MATCH_TEXT_FIELDS` must not include `filename` or `text`.
- Schema validation runs in `_ensure_tables` before any query path is active.

Forbidden stale interpretations:
- Do not add `filename^10,text` back to default chunk auxiliary `match_text`.
- Do not treat legacy chunk tables (lacking tokenizer-derived fields) as compatible.

Verification:
- [tests/unit/infrastructure/test_chunk_text_fields.py](../../../tests/unit/infrastructure/test_chunk_text_fields.py)
- [tests/unit/infrastructure/test_infinity_dense_index.py](../../../tests/unit/infrastructure/test_infinity_dense_index.py)
- [tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py](../../../tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py)

## Ingestion Chunking Contract

Reviewed at: `2026-05-19T21:01:25+08:00`
Status: Active
Owner: `RecursiveCharacterChunker`, `Settings`

Source of truth:
- [chunkers/recursive_character.py](chunkers/recursive_character.py)
- [../config/settings.py](../config/settings.py)

Invariant:
- `Settings.chunk_size` and `RecursiveCharacterChunker.chunk_size` are a
  `cl100k_base` token budget, not a character budget.
- Default ingestion chunk budget is `512` tokens.
- Default ingestion chunk overlap is `0`.
- Recursive separator priority remains string-based; token counts only decide
  whether pieces or merged chunks fit the budget.
- Chunk metadata offsets (`start_offset`, `end_offset`) remain character
  offsets into parsed document text.

Forbidden stale interpretations:
- Do not treat `chunk_size=512` as 512 characters.
- Do not revive the old default overlap of `50`.
- Do not slice token ids and decode them back as the primary fallback path.
- Do not use per-piece token sums as the final fit check for merged chunks.

Verification:
- [tests/unit/infrastructure/test_recursive_character_chunker.py](../../../tests/unit/infrastructure/test_recursive_character_chunker.py)
- [tests/unit/infrastructure/test_chunker.py](../../../tests/unit/infrastructure/test_chunker.py)
- [tests/unit/application/test_ingestion.py](../../../tests/unit/application/test_ingestion.py)
- [tests/unit/test_probe_chunking_script.py](../../../tests/unit/test_probe_chunking_script.py)
- `scripts/probe_chunking.py --input tests/fixtures/documents/microrag-private-bootstrap.md --output-dir data/chunk-probes/token-budget-check`

## ACP Runtime and Session Store Contract

Reviewed at: 2026-05-18T00:00:00+08:00
Status: Active
Owner: `AcpClient`, `AgentSessionStore`

Source of truth:
- ACP runtime integration is a process boundary. UI-visible data must pass through MicroRAG redaction before leaving infrastructure.
- `AgentSessionStore` stores local UI metadata only. Claude Code JSONL transcripts remain the conversation source of truth.

Invariant:
- `AcpClient.start()` uses `from None` to break exception chains; `__cause__` is always `None` on startup failure.
- `_request()` returns raw ACP JSON-RPC result dicts (unfiltered). Backend-only keys (`transcript_path`, `cwd`, etc.) remain available to internal callers. Redaction happens at the HTTP route/response schema boundary, not inside `AcpClient`.
- `redact_acp_event()` strips `BACKEND_ONLY_KEYS` from result dicts (shallow, top-level only). Available as a public utility but not called by `_request()`.
- `redact_acp_error()` replaces messages containing sensitive markers with a fixed generic message.
- `AppServices` stores an ACP client factory and constructs `AcpClient` lazily when agent routes first access `services.acp_client`; non-agent service construction must not require a prepared agent runtime.
- Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `scripts/run_microagent.sh`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp --setting-sources project"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, default `data/agent-runtime/workspace`), `agent_config_dir` (env `MICRORAG_AGENT_CONFIG_DIR`, default `data/agent-runtime/config`), and `microagent_dir` (env `MICRORAG_MICROAGENT_DIR`, default `src/ragflow_lite/microagent`).
- MicroAgent skills and subagents are bundled runtime assets under `src/ragflow_lite/microagent/.claude/skills` and `src/ragflow_lite/microagent/.claude/agents`.
- The MicroAgent project settings file is `src/ragflow_lite/microagent/.claude/settings.json`; it is copied from the local source runtime, local-only, gitignored, required before agent startup, and not content-inspected during migration.
- Product conversation workspace state remains under `data/agent-runtime/workspace`; `setup_agent_runtime()` prepares workspace/config/shim state and must not create or populate `src/ragflow_lite/microagent`.
- `_build_acp_client(settings)` rejects runtime paths that do not resolve to the project-owned defaults from `default_agent_runtime_paths(settings.project_root)`.
- ACP child processes receive `CLAUDE_CONFIG_DIR`, `MICRORAG_AGENT_CWD`, `MICRORAG_AGENT_CONFIG_DIR`, `MICRORAG_MICROAGENT_DIR`, `PATH`, and `PYTHONPATH` through `AcpRuntimeConfig.env`.
- `AgentSessionStore` schema has no `messages`, `conversation`, or `transcript_json` columns.
- Session ordering is `ORDER BY updated_at DESC, created_at DESC, id DESC` for deterministic tiebreaking.

Forbidden stale interpretations:
- Do not re-chain exceptions from `start()` via `from exc`.
- Do not pass raw JSON-RPC error messages through to UI without redaction.
- Do not store conversation content in `AgentSessionStore`.
- Do not fall back to repository root as product ACP cwd.
- Do not treat repository-root `.claude/settings*` or real `~/.claude/settings.json` as product runtime configuration.
- Do not reintroduce generated or copied product skills under `data/agent-runtime/workspace/.claude/skills`.
- Do not let ambient parent-shell `CLAUDE_CONFIG_DIR` select product runtime config.
- Do not reintroduce `src/ragflow_lite/agent_runtime/settings.json` as a source-controlled permissions template.

Verification:
- [tests/unit/infrastructure/test_acp_client_redaction.py](../../../tests/unit/infrastructure/test_acp_client_redaction.py)
- [tests/unit/infrastructure/test_agent_session_store.py](../../../tests/unit/infrastructure/test_agent_session_store.py)
- [tests/unit/api/test_acp_wiring.py](../../../tests/unit/api/test_acp_wiring.py)
- [tests/unit/agent_runtime/test_setup.py](../../../tests/unit/agent_runtime/test_setup.py)

## Known Submodule Contracts

- [evidence/CONTRACTS.md](evidence/CONTRACTS.md) -- graph evidence extraction, candidate indexing, storage, canonicalization, intra-chunk discourse extraction, inter-chunk graph building, and blueprint planning.

## Verification

- Provider wiring: [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)
- Embedding signature guards: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for embedder-related test files)
- Vector index: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for index-related test files)
