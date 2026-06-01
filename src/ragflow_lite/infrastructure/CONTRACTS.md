# Infrastructure Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/infrastructure`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
contracts.

## Scope

Infrastructure adapters implementing `domain.ports`: providers, Infinity,
JSON/file storage, parser, chunker, retriever, answerer, media assets,
and optional VLM adapters.

Leaf adapter folders that do NOT get their own CONTRACTS.md (too small,
single-purpose):

- [answerers/](answerers/)
- [chunkers/](chunkers/)
- [embedders/](embedders/)
- [ingestion/](ingestion/)
- [llms/](llms/)
- [loaders/](loaders/)
- [media/](media/)
- [nlp/](nlp/)
- [parsers/](parsers/)
- [retrievers/](retrievers/)
- [storage/](storage/)
- [vector_indexes/](vector_indexes/)
- [vlm/](vlm/)

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
- Default chunk auxiliary `match_text` uses tokenizer-derived fields plus
  academic sparse fields:
  `filename_kwd^30,paper_title_tks^24,filename_tks^20,academic_role_kwd^18,section_tks^12,caption_tks^10,media_context_tks^9,visual_description_tks^8,element_type_kwd^8,element_label_tks^6,content_tks^2,content_sm_tks`.
- `filename` and `text` remain stored columns, but are not default
  `match_text` fallback fields.
- Chunk tables missing `filename_kwd`, `filename_tks`, `content_tks`,
  `content_sm_tks`, or any academic sparse field are incompatible and must
  fail during initialization (`_validate_chunk_auxiliary_text_columns`
  raises `RuntimeError`).

Invariant:
- `CHUNK_FIELD_MATCH_TEXT_FIELDS` must not include `filename` or `text`.
- `ACADEMIC_CHUNK_TEXT_FIELDS` lists academic-specific sparse columns in the chunk schema.
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

## Academic PDF Ingestion

Reviewed at: `2026-06-01T12:00:00+08:00`
Status: Active
Owner: `DoclingPdfParser`, `DocumentChunker`, `AcademicPdfChunker`, `LocalPdfMediaAssetStore`, `chunk_text_fields.py`, `metadata_sanitizer.py`

Source files:
- [parsers/docling_pdf_adapter.py](parsers/docling_pdf_adapter.py) -- Docling-backed PDF parser emitting `ParsedPdfDocument`
- [chunkers/document_chunker.py](chunkers/document_chunker.py) -- dispatches to academic or generic chunker
- [chunkers/academic_pdf.py](chunkers/academic_pdf.py) -- element-level chunker for academic PDFs
- [media/pdf_asset_store.py](media/pdf_asset_store.py) -- local media asset staging/commit/rollback/delete
- [vlm/ark_figure_describer.py](vlm/ark_figure_describer.py) -- optional Ark VLM figure description (Gate B)
- [vector_indexes/chunk_text_fields.py](vector_indexes/chunk_text_fields.py) -- academic sparse text fields
- [../application/services/metadata_sanitizer.py](../application/services/metadata_sanitizer.py) -- public metadata whitelist for API responses
- [../domain/models/academic_pdf_fields.py](../domain/models/academic_pdf_fields.py) -- canonical `AcademicSparseFieldDescriptor` and `ACADEMIC_SPARSE_FIELD_DESCRIPTORS`

Key invariants:
- `.pdf` routes to `DoclingPdfParser` via `CompositeParser`.
- `DoclingPdfParser` emits `ParsedDocument` with `structured_payload` of type `ParsedPdfDocument`.
- `DocumentChunker` dispatches: `ParsedPdfDocument` payload routes to `AcademicPdfChunker`; all other payloads route to `RecursiveCharacterChunker`.
- `AcademicPdfChunker` produces one chunk per element; chunk text includes paper title, section path, caption, media context, and VLM visual description as retrieval signals.
- Media assets (`PdfMediaAsset`) are internal-only: `storage_path`, `local_path`, `temporary_path`, `media_root`, `base64`, and `raw_docling_object` are `INTERNAL_METADATA_KEYS` stripped by `sanitize_chunk_metadata` before API responses.
- Media asset commit (`commit_assets`) runs after downstream persistence (embedding write, dataset binding) succeeds; on binding failure the staged assets are rolled back, not committed.
- Academic sparse fields derive from a single canonical descriptor tuple `ACADEMIC_SPARSE_FIELD_DESCRIPTORS` in `academic_pdf_fields.py`: `paper_title_tks`, `academic_role_kwd`, `section_tks`, `caption_tks`, `media_context_tks`, `visual_description_tks`, `element_type_kwd`, `element_label_tks`. All downstream consumers (match-text weights, schema validation, public metadata keys) iterate this tuple; no sparse field may be added to the schema without a matching descriptor entry.
- `CHUNK_FIELD_MATCH_TEXT_FIELDS` includes academic fields with boosted weights; legacy tables missing these fields fail fast during `_validate_chunk_auxiliary_text_columns`.
- `LocalPdfMediaAssetStore` media root is `settings.project_root / "data" / "media" / "pdf-assets"`.
- Media assets support only `image/png` with `.png` extension; max default `10 MiB`.
- Optional Ark VLM figure description is gated by `MICRORAG_FIGURE_VLM_ENABLED` (default `false`) and requires `ARK_FIGURE_MODEL` when enabled.
- VLM figure descriptions flow into chunk text (`visual_description` field) and sparse fields (`visual_description_tks`) when the VLM gate is enabled; when disabled, `visual_description` is empty and `visual_description_tks` is an empty string.

Forbidden stale interpretations:
- Do not treat `pypdf` or `pdf_native_text` as the active PDF runtime.
- Do not revive `native-text pdf` or `digital-native text extraction` as the active PDF strategy.
- Do not expose `storage_path`, `local_path`, `media_root`, or `base64` in API responses.
- Do not add non-PNG media types without updating `LocalPdfMediaAssetStore._validate_asset`.
- Do not add academic sparse fields to the schema, match-text weights, or public metadata keys without a matching `AcademicSparseFieldDescriptor` entry.

Verification:
- [tests/unit/infrastructure/test_docling_pdf_adapter.py](../../../tests/unit/infrastructure/test_docling_pdf_adapter.py)
- [tests/unit/infrastructure/test_academic_pdf_chunker.py](../../../tests/unit/infrastructure/test_academic_pdf_chunker.py)
- [tests/unit/infrastructure/test_parsers.py](../../../tests/unit/infrastructure/test_parsers.py)
- [tests/unit/infrastructure/test_chunk_text_fields.py](../../../tests/unit/infrastructure/test_chunk_text_fields.py)
- [tests/unit/infrastructure/test_ark_figure_describer.py](../../../tests/unit/infrastructure/test_ark_figure_describer.py)
- [tests/unit/infrastructure/test_pdf_asset_store.py](../../../tests/unit/infrastructure/test_pdf_asset_store.py)
- [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)
- [tests/unit/domain/test_academic_pdf_models.py](../../../tests/unit/domain/test_academic_pdf_models.py)
- [tests/unit/domain/test_academic_pdf_fields.py](../../../tests/unit/domain/test_academic_pdf_fields.py)
- [tests/unit/application/test_pdf_payload_codec.py](../../../tests/unit/application/test_pdf_payload_codec.py)
- [tests/integration/infrastructure/test_live_infinity_core_paths.py](../../../tests/integration/infrastructure/test_live_infinity_core_paths.py)

## Known Submodule Contracts

- [evidence/CONTRACTS.md](evidence/CONTRACTS.md) -- graph evidence extraction, candidate indexing, storage, canonicalization, intra-chunk discourse extraction, inter-chunk graph building, and blueprint planning.

## Verification

- Provider wiring: [tests/unit/api/test_providers.py](../../../tests/unit/api/test_providers.py)
- Embedding signature guards: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for embedder-related test files)
- Vector index: [tests/unit/infrastructure](../../../tests/unit/infrastructure) (check for index-related test files)
