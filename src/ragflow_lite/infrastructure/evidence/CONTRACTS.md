# Evidence Infrastructure Active Contracts

Reviewed at: `2026-05-08T19:54:53+08:00`
Status: Active

This file owns active runtime contracts for
`src/ragflow_lite/infrastructure/evidence`.
`AGENTS.md` in this subtree should link here instead of duplicating these
contracts.

## Qualification

`evidence` is an independent infrastructure submodule, not an ordinary leaf
adapter folder.

It owns several implementation families:

- graph evidence extractors;
- graph evidence stores;
- graph candidate row builders and Infinity candidate index;
- local JSON graph evidence index;
- graph evidence canonicalization;
- intra-chunk discourse extraction for DiscoRAG.

The parent `infrastructure/CONTRACTS.md` owns adapter-wide defaults. This file
owns only evidence-submodule semantics.

## Graph Evidence Extraction Contract

Owners:
- `DeepSeekChatEvidenceExtractor`
- `OpenAIResponsesEvidenceExtractor`

Source of truth:
- Extractors consume source chunks and produce `GraphEvidenceBatch` objects.
- Empty chunk input is rejected before a model call.
- Extracted evidence must reference known source chunks.

Runtime boundary:
- DeepSeek-backed extraction is the current provider-wired path.
- OpenAI Responses extraction remains a legacy adapter path.

Verification:
- `tests/unit/infrastructure/test_deepseek_evidence_extractor.py`
- `tests/unit/infrastructure/test_openai_evidence_extractor.py`
- provider wiring assertions in `tests/unit/api/test_providers.py`

## Graph Candidate And Storage Contract

Owners:
- `graph_candidate_fields.py`
- `InfinityGraphCandidateIndex`
- `GraphEvidenceInfinityStore`
- `LocalJsonGraphEvidenceStore`
- `LocalJsonGraphEvidenceIndex`

Source of truth:
- Candidate rows include `candidate_id`, `canonical_id`, `document_id`,
  `candidate_kind`, source fields, vector fields, and JSON metadata.
- `canonical_id` comes from metadata when present and falls back to the source
  entity or relation id.
- Relationship candidate output must preserve relationship fields needed to
  rebuild `MiniRelationshipCandidate`.
- Entity candidate queries merge rows by `canonical_id` and keep the strongest
  score.
- Provider wiring uses `GraphEvidenceInfinityStore` to combine document evidence
  storage with the Infinity graph candidate index.
- Local JSON graph evidence storage/indexing is a local fallback and test path,
  not the default runtime candidate index.

Verification:
- `tests/unit/infrastructure/test_graph_candidate_fields.py`
- `tests/unit/infrastructure/test_infinity_graph_candidate_index.py`
- `tests/unit/infrastructure/test_graph_evidence_infinity_store.py`
- provider wiring assertions in `tests/unit/api/test_providers.py`

## Canonicalization Contract

Owner: `graph_evidence_canonicalizer.py`

Source of truth:
- Cross-document canonicalization merges same-name entities into canonical
  entities.
- Directed relationships are merged by canonical endpoints.
- Canonical metadata records member ids and source document information.
- Relations with missing endpoints and entities with empty names are skipped.

Verification:
- `tests/unit/infrastructure/test_graph_evidence_canonicalizer.py`

## Intra-Chunk Discourse Extraction Contract

Owner: `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- The extractor consumes `EvidencePackage.items`.
- `selected_for_discourse=True` marks retriever-selected discourse-visible
  evidence.

Invariant:
- Default extractor behavior has no local chunk cap.
- All retriever-selected discourse-visible chunks are eligible for RST
  extraction.
- Explicit caps are opt-in and must be visible in metadata.
- Metadata always includes `selected_chunk_ids` and `skipped_chunk_ids`.
- `skipped_chunk_ids` may be empty; explicit caps make non-empty skipped ids
  observable when chunks are excluded.

Forbidden stale interpretations:
- `max_chunks=5` is not a valid default.
- A local extractor cap is not the source of DiscoRAG discourse-window semantics.
- RST extraction must not silently shrink MiniRAG's discourse-visible window.

Verification:
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- provider wiring assertions in `tests/unit/api/test_providers.py`
