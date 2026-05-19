# LLM-Backed DiscoRAG Repo-Native Stabilization Plan

Date: 2026-05-09
Status: Ready for implementation after confirmation
Spec: [../specs/2026-05-08-discorag-repo-native-stabilization.md](../specs/2026-05-08-discorag-repo-native-stabilization.md)

This is the execution checklist for the current DiscoRAG slice. The spec
defines target behavior. This plan defines implementation order, likely files,
acceptance criteria, and verification commands.

## Goal

Make the repo-native DiscoRAG path paper-faithful at the structural level:

```text
MiniRAG selects evidence.
LLM RST extracts local discourse structure.
LLM inter-chunk graph models cross-chunk rhetoric.
LLM blueprint planner organizes evidence.
Final answer contexts do not silently grow.
Promotion is bounded replacement.
Invalid structural output fails clearly with ProcessingError.
```

## Decisions Already Confirmed

- Blueprint planner invalid output should fail with a clear `ProcessingError`.
- Do not add query-level downgrade to MiniRAG/basic RAG in this slice.
- Fake-client prohibition is scoped to Infinity only.
- Runtime and public exports must not retain deterministic blueprint planner.
- Reusable code from the old planner may survive only as non-semantic parser,
  validator, or applicator helpers.
- Do not retain deterministic graph generation as runtime fallback.

## Guardrails

- Keep `docs/superpowers/` as local ignored planning material.
- Do not add `chunk_token_budget` work.
- Do not make `context_token_budget` a required DiscoRAG behavior.
- Do not let graph or blueprint planning query indexes, expand MiniRAG paths, or
  retrieve new chunks.
- Do not expose internal graph/planner knobs through `QueryModeRouter` or HTTP
  mode routing.
- Do not optimize p99 latency in this slice.
- Do not introduce a new small-model provider in this slice; reuse DeepSeek for
  the structurer role through explicit wiring.

## Task 0: Baseline Reconnaissance

Purpose: lock the current code surface before editing.

Read-only checks:

- All references to deterministic graph and deterministic blueprint builders.
- Provider wiring for `DiscoRAGQueryService`.
- Existing graph, blueprint, query-service, answerer, and provider tests.
- Current `AnswerBlueprint` domain shape.
- Current promotion executor/filtering behavior.
- Current structurer model settings and DeepSeek client construction patterns.
- Current contract text that will become stale after the LLM planner lands.

Likely files:

- `src/ragflow_lite/application/services/discorag_answer_blueprint_builder.py`
- `src/ragflow_lite/application/services/discorag_query_service.py`
- `src/ragflow_lite/application/services/inter_chunk_discourse_graph_builder.py`
- `src/ragflow_lite/application/services/__init__.py`
- `src/ragflow_lite/domain/models/entities.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_parser.py`
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py`
- `tests/unit/api/test_providers.py`

Acceptance:

- List every runtime/public deterministic blueprint reference to remove.
- Confirm whether old deterministic planner tests should be deleted, rewritten,
  or split into validator/applicator tests.
- Confirm current answerer fallback metadata shape.
- Confirm source-backed structurer settings names.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_answer_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/api/test_providers.py -q
```

## Task 1: LLM Blueprint Output Contract

Purpose: define and test the model-output contract before runtime wiring.

Likely files:

- New `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- Possibly `src/ragflow_lite/domain/models/entities.py`
- New `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`
- Existing `tests/unit/application/test_discorag_answer_blueprint_builder.py` may
  be replaced or narrowed to non-semantic helper coverage.

Implementation notes:

- Parse strict JSON output from the planner model.
- Validate `final_answer_chunk_ids` against answer/discourse-visible chunk ids.
- Validate `chunk_roles` against compact role vocabulary.
- Validate `promotions` as replacement, not append.
- Validate `answer_constraints` and `plan_steps`.
- Validate referenced inter-chunk relation ids.
- Validate referenced RST unit ids.
- Reject duplicate final chunk ids.
- Reject final context count greater than `top_k`.
- Reject supplemental chunk inclusion without a valid replacement promotion.
- Reject unknown chunk, relation, or RST unit references.
- Raise `ProcessingError` for invalid/unusable output.

Acceptance:

- Valid planner output becomes an `AnswerBlueprint` plus metadata needed by
  bounded promotion/application.
- Invalid JSON raises `ProcessingError`.
- Unknown chunk ids raise `ProcessingError`.
- Unknown relation ids raise `ProcessingError`.
- Unknown RST unit ids raise `ProcessingError`.
- Budget overflow raises `ProcessingError`.
- Supplemental append raises `ProcessingError`.
- Replacement promotion is accepted only when it replaces an answer chunk with a
  supplemental discourse chunk.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 2: LLMDiscoRAGAnswerBlueprintBuilder

Purpose: replace deterministic blueprint generation with model-backed discourse
planning.

Likely files:

- New `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- `src/ragflow_lite/infrastructure/evidence/__init__.py`
- New `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `src/ragflow_lite/domain/ports.py` or equivalent port definitions, if needed

Implementation notes:

- Keep the builder protocol compatible with `DiscoRAGQueryService`:
  `build(package, graph, ...) -> AnswerBlueprint` if feasible.
- Prompt includes query, answer chunks, supplemental discourse chunks, compact
  RST structures, inter-chunk graph relations, and final answer budget.
- The builder calls the structurer model/client, not the answerer object.
- The builder uses the parser/validator from Task 1.
- Metadata records safe provider/model/reasoning-effort/builder provenance.
- No deterministic planner fallback.
- Empty planner output is invalid when answer candidates exist.

Acceptance:

- Builder calls the provided structurer client.
- Prompt/input contains answer candidates and supplemental discourse chunks.
- Prompt/input contains RST unit ids and relation projections.
- Prompt/input contains inter-chunk relation ids and labels.
- Parser failures surface as `ProcessingError`.
- No code path constructs the old deterministic blueprint planner.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 3: Runtime Wiring Replacement

Purpose: make runtime DiscoRAG use LLM graph and LLM blueprint structural
builders.

Likely files:

- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `src/ragflow_lite/config/__init__.py`
- `src/ragflow_lite/application/services/discorag_query_service.py`
- `src/ragflow_lite/application/services/__init__.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/application/test_discorag_query_service.py`

Implementation notes:

- Wire `LLMInterChunkDiscourseGraphBuilder`.
- Wire `LLMDiscoRAGAnswerBlueprintBuilder`.
- Use explicit structurer settings while initially reusing DeepSeek.
- Keep answer model wiring separate.
- Remove deterministic blueprint planner from runtime construction.
- Remove deterministic blueprint planner from public application service export.
- Keep no fake Infinity clients; provider unit tests that need Infinity behavior
  should stay behind `--run-live-infinity`.

Acceptance:

- Provider tests assert `DiscoRAGQueryService` receives the LLM blueprint
  planner.
- Provider tests assert structurer settings are threaded to graph and blueprint
  builders.
- No runtime path wires the deterministic blueprint planner.
- No runtime path wires deterministic graph fallback.
- Public `application.services` exports do not expose deterministic blueprint or
  deterministic graph builders as active services.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

## Task 4: Remove Or Demote Deterministic Blueprint Code

Purpose: clean the old mechanical planner so it cannot be mistaken for runtime
DiscoRAG capability.

Likely files:

- `src/ragflow_lite/application/services/discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `src/ragflow_lite/application/services/__init__.py`
- imports in provider/query-service tests

Implementation notes:

- Delete the deterministic planner if no helper code remains useful.
- If helper code remains useful, rename/extract it so it is clearly not a
  planner, for example:
  - `blueprint_context_applicator.py`
  - `answer_blueprint_validation.py`
- Do not retain a class whose job is to generate a blueprint from rules.
- Remove tests that assert deterministic relation-to-plan mapping.
- Replace tests with parser/validator/applicator behavior where relevant.

Acceptance:

- No runtime/public deterministic blueprint planner remains.
- No tests lock old mechanical label mapping as intended runtime behavior.
- Any remaining helper has no semantic planning responsibility.
- `rg "DiscoRAGAnswerBlueprintBuilder|Deterministic.*Blueprint"` returns only
  expected new compatibility references or no hits.

Suggested verification:

```bash
rg "DiscoRAGAnswerBlueprintBuilder|Deterministic.*Blueprint" src tests
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 5: Still-Relevant Review Findings

Purpose: fix review findings that remain relevant after replacing the planner.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
- `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- `src/ragflow_lite/application/services/__init__.py`
- `src/ragflow_lite/CONTRACTS.md`
- related tests

Implementation notes:

- Add RST normalization alias: `sequences -> temporal_next`.
- Add test coverage for prompt-literal `sequences`.
- Add graph metadata for safe provider/model/structurer provenance.
- Tighten answerer fallback so partially invalid blueprint ids are invalid and
  observable.
- Remove stale deterministic graph export if still exposed.
- Do not patch the old deterministic blueprint append behavior unless helper
  extraction leaves a real applicator bug; the runtime planner should be gone.

Acceptance:

- RST prompt labels and normalizer labels are aligned.
- Graph metadata includes enough safe provenance to debug structurer wiring.
- Answerer fallback records partial invalidity instead of silently ignoring
  unknown ids.
- Public exports do not advertise deterministic graph/blueprint builders as
  active runtime services.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

## Task 6: Full-Chain Local Smoke

Purpose: verify repo-native DiscoRAG behavior without network calls.

Likely files:

- `tests/unit/application/test_discorag_local_smoke.py`
- fixtures/helpers near existing DiscoRAG tests

Implementation notes:

- Use mocked structurer clients for graph and blueprint model calls.
- Do not use deterministic graph or deterministic blueprint builders.
- Keep fake clients scoped to non-Infinity boundaries. No fake Infinity client.
- Build an evidence package with answer chunks plus supplemental discourse
  chunks.
- Make graph output include relation ids used by planner output.
- Make RST output include unit ids used by planner output.
- Planner output should promote a supplemental chunk by replacement.

Acceptance:

- MiniRAG/EvidencePackageBuilder creates answer and supplemental discourse
  chunks.
- LLM graph builder receives all discourse-visible chunks.
- LLM blueprint planner receives query, answer chunks, supplemental chunks, RST,
  graph, and budget.
- Final answer contexts are `<= top_k`.
- Supplemental chunk promotion is replacement, not append.
- Answerer receives `mode="discorag"` and a validated blueprint.
- Invalid planner output raises `ProcessingError`.
- Invalid graph output raises `ProcessingError`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 7: Contract Promotion

Purpose: update active contracts only after source-backed behavior lands.

Likely files:

- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- possibly nearest config contract/guidance if config semantics require it

Rules:

- Promote only source-backed facts.
- Keep planning details in `docs/superpowers/`.
- Document that RST, inter-chunk graph, and blueprint planner are LLM-backed
  structural stages.
- Document no deterministic graph or blueprint runtime fallback.
- Document structurer model semantics and env/config surface.
- Document `ProcessingError` behavior for invalid planner output.
- Document answerer fallback as defensive, observable, and not a planner
  fallback.
- Do not document `chunk_token_budget`.
- Do not document `context_token_budget` as required DiscoRAG behavior.
- Keep `AGENTS.md` files as navigation only.

Acceptance:

- Active contracts describe current runtime behavior, not future work.
- Contract links and verification commands point to real tests.
- No stale deterministic graph or deterministic blueprint assumptions remain.
- Root provider contract lists the structurer env/config surface if active.

## Final Stabilization Gate

Run parser/builder floors:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Run application and answerer floors:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_evidence_package_builder.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Run provider wiring with live Infinity enabled:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Run the full unit suite:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run core live Infinity checks:

```bash
.venv/bin/python -m pytest \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_live_infinity_endpoints.py \
  --run-live-infinity -q
```

Optional endpoint live gate:

```bash
.venv/bin/python -m pytest tests/integration/api/test_v0_endpoints.py --run-live-infinity -q
```

Current known risk: one endpoint test can time out while waiting for document
indexing to reach terminal state within 3 seconds. Treat that separately unless
this slice explicitly takes on live endpoint timing stabilization.
