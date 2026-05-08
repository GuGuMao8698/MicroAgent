# Evidence Infrastructure Active Contracts

This file owns active runtime contracts for
`src/ragflow_lite/infrastructure/evidence`.
`AGENTS.md` in this subtree should link here instead of duplicating these
contracts.

## Intra-Chunk Discourse Extraction Contract

Reviewed at: `2026-05-08T14:30:00+08:00`
Status: Active
Owner: `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- The extractor consumes `EvidencePackage.items`.
- `selected_for_discourse=True` marks retriever-selected discourse-visible evidence.

Invariant:
- Default extractor behavior has no local chunk cap.
- All retriever-selected discourse-visible chunks are eligible for RST extraction.
- Explicit caps are opt-in and must be visible in metadata.
- Metadata always exposes selected and skipped chunk ids; explicit caps make skipped ids observable when chunks are excluded.

Forbidden stale interpretations:
- `max_chunks=5` is not a valid default.
- A local extractor cap is not the source of DiscoRAG discourse-window semantics.
- RST extraction must not silently shrink MiniRAG's discourse-visible window.

Verification:
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- provider wiring assertion in `tests/unit/api/test_providers.py`
