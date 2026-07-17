# Evidence Infrastructure Active Contracts

## SQLite Artifact Truth

Reviewed at: `2026-07-11`
Status: Active for graph evidence and Psi tree artifacts
Owner: `SqliteGraphEvidenceStore`, `SqlitePsiTreeStore`, `SqliteArtifactRegistry`, `SqliteGraphProjectionStore`, `PsiNodeProjectionStore`

- Runtime graph truth is each document's raw `GraphEvidenceBatch` persisted in SQLite.
- `artifact_builds`, `artifact_projections`, and `active_artifacts` own graph artifact lifecycle truth, including activation, deletion, rebuild, repair, and projection ownership.
- Infinity graph rows are derived retrieval projections. They are serviceable only when their owning build is active and their projection status is `projected`.
- Cross-document canonicalization and path expansion run at read time over raw evidence. Canonical state is not a persisted truth object.
- JSON graph evidence is no longer runtime truth. Rebuild or re-ingest is the supported transition to SQLite-backed artifacts.
- Graph deletion can mark graph builds and projections deleted, but the document remains `deleting`. Whole-document deletion is incomplete until `ArtifactDeleteCoordinator` proves graph projection cleanup, Psi projection cleanup, SQLite payload cleanup, and main chunk-index deletion.

## Psi Tree Artifacts

Reviewed at: `2026-07-11`
Status: Active
Owner: `SqlitePsiTreeStore`, `PsiNodeProjectionStore`, `InfinityPsiNodeIndex`, `PsiTopDownAuxiliaryRetriever`

Source of truth:
- SQLite owns each document-scoped Psi tree payload: tree metadata, nodes, edges,
  node-to-source-chunk mappings, and artifact lifecycle/projection state.
- The Infinity Psi node table is an isolated retrieval projection. It is not the
  main source-chunk table, and its rows are derived from the SQLite-owned build.
- `psi_node_id` is an internal node retrieval identity, never a source
  `chunk_id`. Traversal must resolve node hits through SQLite source mappings
  before fetching ordinary source chunks.
- `keyword_text` and `summary_text` contribute only to Psi node projection
  vectors and sparse fields. They never replace or augment source `Chunk.text`.

Serviceability and degradation:
- A Psi tree is query-serviceable only when its SQLite build and document are
  active, `active_artifacts` selects the build, it has a queryable layer, and an
  `infinity_psi_node` projection is recorded as `projected`.
- A projected start-layer mismatch is marked `repair_pending` before the
  configured auxiliary fallback runs.
- Missing active trees, empty mappings, projection inconsistencies, unexpected
  traversal failures, unavailable narrowing, and missing source chunks are not
  silent: the auxiliary result records a specific stop/failure reason and a
  `success`, `degraded`, `fallback`, `failed`, or `skipped` state.
- Configured `legacy` fallback returns the legacy source-chunk results with
  `fallback_source=legacy_string_retriever`; configured `none` returns no
  synthesized Psi evidence and records `fallback_source=none`.

Verification:
- [tests/unit/infrastructure/test_sqlite_psi_tree_store.py](../../../../tests/unit/infrastructure/test_sqlite_psi_tree_store.py)
- [tests/unit/infrastructure/test_psi_node_projection_store.py](../../../../tests/unit/infrastructure/test_psi_node_projection_store.py)
- [tests/unit/infrastructure/test_infinity_psi_node_index.py](../../../../tests/unit/infrastructure/test_infinity_psi_node_index.py)
- [tests/unit/infrastructure/test_psi_top_down_auxiliary_retriever.py](../../../../tests/unit/infrastructure/test_psi_top_down_auxiliary_retriever.py)

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
- Relation endpoints must match extracted entity names. The DeepSeek-backed
  runtime path uses one bounded validation-repair turn for invalid graph evidence
  JSON and still fails if the regenerated output remains invalid.

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

Reviewed at: `2026-05-11T12:00:00+08:00`
Status: Active
Owner: `LLMInterChunkDiscourseGraphBuilder`, `LLMDiscoRAGAnswerBlueprintBuilder`, `DeepSeekChatIntraChunkDiscourseExtractor`

Source of truth:
- DiscoRAG structurer calls use bounded attempts controlled by `DiscoRAGStructurerRuntimeConfig.timeout_seconds` (default 90) and `max_attempts` (default 2), wired through providers.
- Structurer calls pass `max_retries=0` to `DeepSeekChatCompletionsClient`, ensuring one structurer attempt equals one SDK request.
- Validation failures are repaired by asking the same structurer model to regenerate a complete JSON object using multi-turn context and a short validation feedback turn (`build_validation_repair_messages` in [structurer_retry.py](structurer_retry.py)).
- Timeout retries start a fresh original attempt (reset `repair_messages = None`).
- `StructurerAttemptState` tracks attempts, failure type, and failure summaries per stage.
- Exhausted attempts raise `StructurerAttemptsExhaustedError` (extends `ProcessingError`) with structured `stage`, `failure_type`, `attempts`, `max_attempts`, `message`, and `safe_metadata()`.
- Plain `ProcessingError` inside an attempt triggers repair when attempts remain.
- `is_timeout_error()` classifies exceptions by class name and message content.
- RST extraction rejects missing, duplicate, and unknown chunk structures; incomplete LLM output triggers validation repair.
- Parsers remain strict; runtime services do not patch invalid structure.

Invariant:
- One structurer attempt = one SDK request (no hidden transport retries).
- Exhausted attempts raise `StructurerAttemptsExhaustedError`; the caller decides fallback policy.
- Plain `ProcessingError` from parser validation triggers repair when attempts remain, exhaustion when budget is spent.
- Validation repair uses `complete_messages_json()` (multi-turn); fresh attempts use `complete_json()` (single-turn).
- Builders do not fall back to deterministic output on exhaustion.
- Provider wiring forwards `timeout_seconds` and `max_attempts` from `DiscoRAGStructurerRuntimeConfig` to all three structurer constructors.

Forbidden stale interpretations:
- Do not re-enable low-level DeepSeek retry for structurer calls.
- Do not catch `StructurerAttemptsExhaustedError` as a generic `ProcessingError` in application services; use the specific type.

Verification:
- [tests/unit/infrastructure/test_structurer_retry.py](../../../../tests/unit/infrastructure/test_structurer_retry.py)
- [tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py](../../../../tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_deepseek_discourse_extractor.py](../../../../tests/unit/infrastructure/test_deepseek_discourse_extractor.py)
- [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)

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

Reviewed at: `2026-05-22T16:48:56+08:00`
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
- `final_answer_chunk_ids` is the complete ordered final-answer context list after promotion replacement, not a selected-useful subset.
- Supplemental chunks in `final_answer_chunk_ids` require a valid matching promotion.
- Parser coverage is computed from builder/parser input `answer_chunk_ids` plus valid promotion replacements, never from model-authored coverage fields.
- Non-promotion outputs must contain every answer candidate id exactly once.
- Promotion outputs must contain the expected final ids after replacing answer ids with promoted supplemental ids; missing, unexpected, or duplicate final ids raise `ProcessingError` with diagnostic fields.
- Missing final context ids use the existing validation-repair attempt path when attempts remain; there is no independent missing-id retry loop.
- `top_k` remains a hard parser guardrail; builder input should already fit coverage plus budget, and parser must not silently drop ids to satisfy budget.
- Role vocabulary: lead, support, background, caveat, comparison, definition, condition, context.
- Constraint vocabulary: caveat, condition, conflict, comparison, support, background, definition, ordering.
- Structurer model is configured via `DiscoRAGStructurerRuntimeConfig` (same config as graph builder, decoupled from answer model).

Forbidden stale interpretations:
- Do not reintroduce `DiscoRAGAnswerBlueprintBuilder` as runtime planner.
- Do not treat `ProcessingError` from planner as a signal to downgrade to basic RAG.
- Do not treat `final_answer_chunk_ids` as a free subset selector.
- Do not use [docs/superpowers/plans](../../../../docs/superpowers/plans) or [docs/superpowers/specs](../../../../docs/superpowers/specs) as active runtime contracts.

Verification:
- [tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py)
- [tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py](../../../../tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py)
- [tests/unit/application/test_discorag_local_smoke.py](../../../../tests/unit/application/test_discorag_local_smoke.py)
- [tests/unit/api/test_providers.py](../../../../tests/unit/api/test_providers.py)
