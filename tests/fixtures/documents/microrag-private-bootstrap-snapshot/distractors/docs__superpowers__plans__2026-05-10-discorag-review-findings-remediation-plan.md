# DiscoRAG Review Findings Remediation Plan

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-review-findings-remediation.md](../specs/2026-05-10-discorag-review-findings-remediation.md)

This plan fixes all review findings from the current LLM-backed DiscoRAG graph
and blueprint change set. It assumes the broader stabilization plan in
[2026-05-08-discorag-repo-native-stabilization-plan.md](2026-05-08-discorag-repo-native-stabilization-plan.md)
is already in progress.

## Goal

Make the current change set mergeable by enforcing:

```text
strict structural validation
promotion as true replacement
planner ordering preservation
end-to-end structurer config
safe structural provenance
no deterministic planner public surface
source-backed contracts
smoke tests that catch the reviewed regressions
```

## Task 0: Baseline And Regression Lock

Purpose: capture the current failing semantics before patching.

Read-only checks:

- Confirm current `git status` has staged deletion of deterministic graph
  builder/tests plus unstaged LLM graph/blueprint changes.
- Confirm current unit suite is green despite review findings.
- Confirm there is no fake Infinity client or `infinity.connect` monkeypatch.
- Identify all references to `DiscoRAGAnswerBlueprintBuilder` and decide which
  are test-local only.

Commands:

```bash
git status --short
rg "DiscoRAGAnswerBlueprintBuilder|DeterministicInterChunk|FakeInfinity|infinity\\.connect" src tests
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Acceptance:

- Current green tests are understood as insufficient coverage, not proof that
  reviewed issues are false.
- Any remaining deterministic planner usage is mapped to remove/keep-test-only.

## Task 1: Fix Runtime Promotion Application

Purpose: make LLM planner promotion actually affect final answer contexts.

Likely files:

- `src/ragflow_lite/application/services/discorag_query_service.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- Change `_contexts_with_bounded_promotion()` to consume
  `blueprint.metadata["promotions"]`.
- Treat each promotion as `replace_chunk_id -> with_chunk_id`.
- Look up `with_chunk_id` in `retrieval_result.metadata["supplemental_discourse_chunks"]`.
- Replace the matching original answer context in place when possible.
- Keep final context count bounded by the original context count.
- Keep a derived `promoted_chunk_ids` metadata list only for observability if
  useful, not as the source of truth.
- If a promotion references a missing supplemental chunk at runtime, do not
  invent a context; because parser should have validated ids, this should be an
  observable defensive no-op or `ProcessingError` depending on current service
  error style. Prefer `ProcessingError` if reachable in normal control flow.

Acceptance:

- A valid planner promotion inserts the supplemental chunk into final contexts.
- The replaced answer chunk is absent from final contexts.
- Context count remains `<= top_k`.
- Existing non-promotion queries are unchanged.
- Smoke hard-asserts the promoted path.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 2: Enforce Replacement Semantics In Blueprint Parser

Purpose: reject append-style planner output before runtime application.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- For each valid promotion:
  - `replace_chunk_id` must be in original `answer_chunk_ids`;
  - `with_chunk_id` must be in `supplemental_chunk_ids`;
  - `with_chunk_id` must be in `final_answer_chunk_ids`;
  - `replace_chunk_id` must not be in `final_answer_chunk_ids`.
- Reject final lists that include both the replaced answer chunk and the
  supplemental chunk.
- Reject final lists that include supplemental chunks without matching
  promotion.
- Reject duplicate or conflicting promotions for the same `replace_chunk_id` or
  same `with_chunk_id`.
- Preserve structured promotions in metadata.
- Optionally derive `promoted_chunk_ids` as metadata for observability.

Acceptance:

- Valid replacement promotion passes.
- Append-style promotion fails with `ProcessingError`.
- Supplemental chunk without promotion fails.
- Promotion that replaces non-answer chunk fails.
- Promotion that inserts non-supplemental chunk fails.
- Duplicate/conflicting promotion fails.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 3: Preserve Planner Ordering When Filtering Blueprint

Purpose: ensure the answerer consumes planner ordering, not retrieval ordering.

Likely files:

- `src/ragflow_lite/application/services/discorag_query_service.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`

Implementation notes:

- In `_blueprint_for_contexts()`, build `ordered_chunk_ids` from
  `blueprint.ordered_chunk_ids` filtered to final context ids.
- Append any final context ids not covered by planner ordering in final context
  order as a defensive completion step.
- Keep `answer_context_chunk_ids` metadata in actual final context order.
- Do not reorder the actual `contexts` list unless Task 1's replacement
  requires local in-place replacement.

Acceptance:

- Answer-facing blueprint preserves planner relative order.
- Final contexts still remain bounded.
- Context metadata remains truthful about the actual context list.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

## Task 4: Make Graph Parser Strict

Purpose: align graph parsing with `ProcessingError` structural failure
semantics.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_parser.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py`

Implementation notes:

- Keep `unrelated` as the only whitelisted non-edge drop.
- Raise `ProcessingError` for:
  - non-object relation entries;
  - missing source/target/relation fields;
  - unknown relation labels;
  - unknown source/target chunk ids;
  - self references.
- Decide whether invalid confidence should clamp or fail. Existing spec allows
  confidence clamping, so keep clamping for numeric out-of-range confidence and
  treat non-numeric optional confidence as absent.
- Update tests that currently expect mixed valid/invalid payloads to pass.

Acceptance:

- Valid graph passes.
- Empty `relations: []` passes.
- `unrelated` entries are dropped without failure.
- Mixed valid + unknown chunk fails.
- Mixed valid + self reference fails.
- Mixed valid + invalid relation label fails.
- Mixed valid + missing fields fails.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py -q
```

## Task 5: Make Blueprint Parser Strict For All Structural Fields

Purpose: stop half-valid blueprint output from reaching the answerer.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_parser.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py`

Implementation notes:

- `chunk_roles` must be an object if present.
- Every `chunk_roles` key must be known.
- Every role must be in the compact vocabulary.
- `answer_constraints` must be a list if present.
- Every constraint must be an object.
- Constraint `type` must be in vocabulary.
- Constraint `text` should be a string; reject non-string text.
- `plan_steps` must be a list if present.
- Every plan step must be an object.
- Plan step `text` should be a string; reject non-string text.
- Validate `source_chunk_ids` against known answer + supplemental chunk ids.
- Validate `source_relation_ids` and `source_rst_unit_ids` as today.
- Validate source id fields are lists of strings, not arbitrary iterables.

Acceptance:

- Invalid role fails.
- Invalid constraint type fails.
- Non-object constraint fails.
- Non-object plan step fails.
- Unknown `source_chunk_ids` fails.
- Wrong source id field type fails.
- Valid constraints and plan steps still produce `answer_constraints` and
  `plan_steps` strings for `AnswerBlueprint`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

## Task 6: Route RST Through Structurer Config

Purpose: make the structurer model boundary end-to-end.

Likely files:

- `src/ragflow_lite/api/deps/providers.py`
- `src/ragflow_lite/config/settings.py`
- `tests/unit/api/test_providers.py`
- active contracts after behavior lands

Implementation notes:

- Construct `DeepSeekChatIntraChunkDiscourseExtractor` from
  `structurer_runtime_config`, not `deepseek_runtime_config`.
- Keep answerer construction on answer/deepseek runtime config.
- Ensure graph and blueprint builders continue to use the same structurer
  config.
- Update provider tests to assert RST, graph, and blueprint structural
  components share the structurer model/reasoning/base URL.

Acceptance:

- Changing `DISCORAG_STRUCTURER_*` affects RST, graph, and blueprint structural
  builders.
- Answerer config remains separate.
- Provider tests pass with `--run-live-infinity`.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

## Task 7: Add Safe Provenance Metadata

Purpose: make graph/blueprint structural outputs debuggable.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

Implementation notes:

- Include provider/structurer provenance in `llm_metadata`.
- Use safe fields only:
  - `provider`;
  - `model`;
  - `reasoning_effort`;
  - `builder`;
  - optionally sanitized `base_url` or `base_url_host`.
- Never include API keys.
- If builder constructors currently do not accept provider name, add a default
  such as `provider="deepseek"` or thread it from provider wiring.

Acceptance:

- Graph metadata includes safe provider provenance.
- Blueprint metadata includes safe provider provenance.
- Tests assert no API key appears in metadata.

Suggested verification:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

## Task 8: Remove Deterministic Planner Public Export

Purpose: prevent accidental reuse of deterministic blueprint planning.

Likely files:

- `src/ragflow_lite/application/services/__init__.py`
- `tests/unit/application/test_discorag_answer_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`

Implementation notes:

- Remove `DiscoRAGAnswerBlueprintBuilder` from
  `ragflow_lite.application.services` exports.
- If tests still need it as a stub, import it directly from its module or move
  the stub to test helpers.
- Do not wire it in providers.
- Keep any retained deterministic class explicitly documented as test-only until
  it can be deleted.

Acceptance:

- `from ragflow_lite.application.services import DiscoRAGAnswerBlueprintBuilder`
  no longer works or is no longer used in tests.
- Provider runtime still wires `LLMDiscoRAGAnswerBlueprintBuilder`.
- `rg "DiscoRAGAnswerBlueprintBuilder" src tests` shows only intentional
  direct test-stub references and contract warnings.

Suggested verification:

```bash
rg "DiscoRAGAnswerBlueprintBuilder" src tests
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_answer_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py -q
```

## Task 9: Align RST Contract And Alias Tests

Purpose: keep contracts source-backed and make the `sequences` fix robust.

Likely files:

- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

Implementation notes:

- Either update contract to 7 explicit planning role buckets plus `context`
  fallback, or add the missing eighth role in implementation and tests.
- Preserve `sequences -> temporal_next`.
- Add mixed-case/whitespace alias coverage if normalizer is intended to be
  case/space tolerant.

Acceptance:

- Contract role count matches implementation.
- `sequences`, `Sequences`, and whitespace-padded variants behave as intended.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

## Task 10: Harden Full-Chain Smoke

Purpose: make smoke catch the exact regression found in review.

Likely files:

- `tests/unit/application/test_discorag_local_smoke.py`

Implementation notes:

- Replace conditional promotion assertion with hard assertions:
  - promoted supplemental chunk is present;
  - replaced answer chunk is absent;
  - final context count is bounded.
- Assert answer-facing blueprint preserves planner ordering.
- Assert both graph and blueprint builders are LLM-backed test doubles.

Acceptance:

- Smoke fails before Task 1 promotion fix.
- Smoke passes after promotion fix.
- Smoke does not use deterministic graph or deterministic blueprint builders.

Suggested verification:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

## Task 11: Promote Contracts After Source Fixes

Purpose: update active contracts only after code and tests prove behavior.

Likely files:

- `src/ragflow_lite/CONTRACTS.md`
- `src/ragflow_lite/application/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/CONTRACTS.md`
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`

Rules:

- Document strict parser failure semantics.
- Document structured promotion replacement and runtime application.
- Document structurer config covers RST, graph, and blueprint.
- Document safe provenance metadata.
- Document deterministic planner public export removal.
- Fix stale role-count statement.
- Keep planning details out of active contracts.

Acceptance:

- Contracts describe current source-backed behavior only.
- No stale deterministic graph/blueprint assumptions remain.

## Final Verification Gate

Run focused tests:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Run provider wiring with live Infinity:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Run full unit suite:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run whitespace check:

```bash
git diff --check && git diff --cached --check
```

Optional live integration check:

```bash
.venv/bin/python -m pytest \
  tests/integration/infrastructure/test_live_infinity_core_paths.py \
  tests/integration/infrastructure/test_live_infinity_dense_legacy_compat.py \
  tests/integration/api/test_live_infinity_endpoints.py \
  --run-live-infinity -q
```
