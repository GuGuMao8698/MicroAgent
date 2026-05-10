# Evidence Infrastructure Active Contracts

Reviewed at: `2026-05-08T19:54:53+08:00`
Status: Active

This file owns active runtime contracts for
`src/ragflow_lite/infrastructure/evidence`.
[AGENTS.md](./AGENTS.md) in this subtree should link here instead of duplicating these
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
- intra-chunk discourse extraction for DiscoRAG;
- LLM inter-chunk discourse graph builder and output parser;
- LLM DiscoRAG blueprint planner and output parser.

The parent [../CONTRACTS.md](../CONTRACTS.md) owns adapter-wide defaults. This file
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
- [tests/unit/infrastructure/test_deepseek_evidence_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_evidence_extractor.py)
- [tests/unit/infrastructure/test_openai_evidence_extractor.py](../../../../tests/unit/infrastructure/test_openai_evidence_extractor.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Graph Candidate And Storage Contract

Owners:
- [graph_candidate_fields.py](graph_candidate_fields.py)
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
- [tests/unit/infrastructure/test_graph_candidate_fields.py](../../../../tests/unit/infrastructure/test_graph_candidate_fields.py)
- [tests/unit/infrastructure/test_infinity_graph_candidate_index.py](../../../../tests/unit/infrastructure/test_infinity_graph_candidate_index.py)
- [tests/unit/infrastructure/test_graph_evidence_infinity_store.py](../../../../tests/unit/infrastructure/test_graph_evidence_infinity_store.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Canonicalization Contract

Owner: [graph_evidence_canonicalizer.py](graph_evidence_canonicalizer.py)

Source of truth:
- Cross-document canonicalization merges same-name entities into canonical
  entities.
- Directed relationships are merged by canonical endpoints.
- Canonical metadata records member ids and source document information.
- Relations with missing endpoints and entities with empty names are skipped.

Verification:
- [tests/unit/infrastructure/test_graph_evidence_canonicalizer.py](../../../../tests/unit/infrastructure/test_graph_evidence_canonicalizer.py)

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
- [tests/unit/infrastructure/test_deepseek_discourse_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_discourse_extractor.py)
- provider wiring assertions in [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

## Structurer Retry Boundary

Reviewed at: `2026-05-10T20:00:00+08:00`
Status: Active
Owner: `LLMInterChunkDiscourseGraphBuilder`, `LLMDiscoRAGAnswerBlueprintBuilder`, `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- DiscoRAG structurer calls use bounded attempts controlled by `DiscoRAGStructurerRuntimeConfig.timeout_seconds` (default 90) and `max_attempts` (default 2).
- Validation failures are repaired by asking the same structurer model to regenerate a complete JSON object using multi-turn context and a short validation feedback turn (`build_validation_repair_messages` in [structurer_retry.py](structurer_retry.py)).
- Timeout retries start a fresh original attempt (reset `repair_messages = None`).
- `StructurerAttemptState` tracks attempt counts, repair counts, and timeout counts per stage.
- `is_timeout_error()` classifies exceptions by class name and message content.
- Parsers remain strict; runtime services do not patch invalid structure.

Invariant:
- Each builder loop raises `ProcessingError` with an `"failed after N attempts"` message when all attempts are exhausted.
- Validation repair uses `complete_messages_json()` (multi-turn); fresh attempts use `complete_json()` (single-turn).
- Builders do not fall back to deterministic output on exhaustion; the caller decides fallback policy.

Verification:
- [tests/unit/infrastructure/test_structurer_retry.py](../../../../tests/unit/infrastructure/test_structurer_retry.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_deepseek_discourse_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_discourse_extractor.py)

## LLM Inter-Chunk Discourse Graph Contract

Reviewed at: `2026-05-09T20:00:00+08:00`
Status: Active
Owner: `LLMInterChunkDiscourseGraphBuilder`, `parse_llm_inter_chunk_graph`

Source of truth:
- `LLMInterChunkDiscourseGraphBuilder` implements the `InterChunkDiscourseGraphBuilder` port (sync).
- Uses structurer model via `DeepSeekChatCompletionsClient.complete_json()` for listwise graph inference.
- Prompt uses stable `CHUNK[N] id=<canonical_chunk_id>` identifiers; includes compact RST summaries when structures are available.
- `parse_llm_inter_chunk_graph()` validates raw LLM JSON against discourse-visible chunk IDs.
- Paper relation labels: 21 including `unrelated` (`PAPER_INTER_CHUNK_RELATION_TYPES`); 20 materialized (`MATERIALIZED_RELATION_TYPES`).

Invariant:
- No deterministic graph fallback. `DeterministicInterChunkDiscourseGraphBuilder` is not wired in runtime.
- `unrelated` relations are dropped, not materialized. Omitted pairs are treated as unrelated.
- Invalid relations (bad chunk IDs, self-references, unknown types) are individually dropped; drop counts per category are observable in metadata.
- Overall unusable output (parse failure or all relations invalid) raises `ProcessingError`.
- `DiscourseUnit` has functional RST projections: `nuclearity` (nucleus/satellite/joint), `rst_relation` (9 normalized labels), `planning_role` (7 compact roles: claim, evidence, definition, condition, qualification, contrast, procedure; plus `context` fallback for unmapped roles).

Forbidden stale interpretations:
- Do not reintroduce `DeterministicInterChunkDiscourseGraphBuilder` as runtime fallback.
- Do not treat `qualifies` as a valid inter-chunk relation label.

Verification:
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../../tests/unit/application/test_discorag_local_smoke.py)

## LLM DiscoRAG Blueprint Planner Contract

Reviewed at: `2026-05-09T21:00:00+08:00`
Status: Active
Owner: `LLMDiscoRAGAnswerBlueprintBuilder`, `parse_llm_discorag_blueprint`

Source of truth:
- `LLMDiscoRAGAnswerBlueprintBuilder` implements the `BlueprintBuilder` port (sync).
- Uses structurer model via `DeepSeekChatCompletionsClient.complete_json()` for discourse-aware blueprint planning.
- Builder consumes `IntraChunkDiscoursePackage` and `InterChunkDiscourseGraph`; derives answer/supplemental chunks and top_k budget from the evidence package.
- Prompt includes: query, top_k budget, answer candidates, supplemental discourse chunks with CHUNK[N] identifiers, RST unit details (id, role, nuclearity, rst_relation), intra-chunk RST relations, and inter-chunk graph relations with synthesized IDs.
- `parse_llm_discorag_blueprint()` validates raw LLM JSON: chunk IDs, relation IDs, RST unit IDs, budget, role/constraint vocabularies, promotion replacement semantics.

Invariant:
- No deterministic blueprint planner fallback. `DiscoRAGAnswerBlueprintBuilder` is retained only as a test stub; it is not wired in runtime providers.
- Blueprint validation failure (unparseable JSON, unknown chunk/relation/RST IDs, budget overflow, invalid promotion) raises `ProcessingError`.
- Promotions are strictly replacement (answer chunk out, supplemental chunk in); append is rejected.
- Supplemental chunks in `final_answer_chunk_ids` require a valid matching promotion.
- Role vocabulary: lead, support, background, caveat, comparison, definition, condition, context.
- Constraint vocabulary: caveat, condition, conflict, comparison, support, background, definition, ordering.
- Structurer model is configured via `DiscoRAGStructurerRuntimeConfig` (same config as graph builder, decoupled from answer model).

Forbidden stale interpretations:
- Do not reintroduce `DiscoRAGAnswerBlueprintBuilder` as runtime planner.
- Do not treat `ProcessingError` from planner as a signal to downgrade to basic RAG.
- Do not use [docs/superpowers/plans](../../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../../tests/unit/application/test_discorag_local_smoke.py)
- [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)
