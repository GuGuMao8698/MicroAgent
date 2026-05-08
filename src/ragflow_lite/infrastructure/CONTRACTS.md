# Infrastructure Active Contracts

This file owns active runtime contracts for `src/ragflow_lite/infrastructure`.
`AGENTS.md` in this subtree should link here instead of duplicating these
contracts.

## Scope

Infrastructure adapters implementing `domain.ports`: providers, Infinity,
JSON/file storage, parser, chunker, retriever, and answerer.

Leaf adapter folders that do NOT get their own CONTRACTS.md (too small,
single-purpose):

- `answerers/`
- `chunkers/`
- `embedders/`
- `ingestion/`
- `llms/`
- `loaders/`
- `nlp/`
- `parsers/`
- `retrievers/`
- `storage/`
- `vector_indexes/`

## Adapter Boundary Contract

Reviewed at: `2026-05-08T16:00:00+08:00`
Status: Active
Owner: `build_services` in `api/deps/providers.py`

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
- OpenAI Responses adapters (`OpenAIResponsesAnswerer`, `OpenAIResponsesEvidenceExtractor`,
  `OpenAIResponsesQueryGrounder`) remain legacy; they are not the default runtime path.
- Default model: `deepseek-v4-flash` with `reasoning_effort="high"`.

Logging boundary:
- Infrastructure may translate low-level exceptions and log bounded adapter outcomes.
- Application layer owns main workflow outcome logs.

## Known Submodule Contracts

- `evidence/CONTRACTS.md` -- graph evidence extraction, candidate indexing, storage, canonicalization, and intra-chunk discourse extraction.

## Verification

- Provider wiring: `tests/unit/api/test_providers.py`
- Embedding signature guards: `tests/unit/infrastructure/` (check for embedder-related test files)
- Vector index: `tests/unit/infrastructure/` (check for index-related test files)
