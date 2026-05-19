# DiscoRAG Review Findings Remediation

Date: 2026-05-10
Status: Draft remediation spec
Parent spec:
[2026-05-08-discorag-repo-native-stabilization.md](2026-05-08-discorag-repo-native-stabilization.md)

This document specifies how to fix the review findings found in the current
DiscoRAG LLM-backed graph/blueprint change set. It is planning material, not an
active runtime contract. Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md`
and should be updated only after source-backed behavior lands.

## Decision

Fix all review findings by tightening the structural path around one rule:

```text
LLM may infer discourse structure.
Code must strictly validate, apply, and expose that structure.
Invalid structure raises ProcessingError.
No deterministic graph or blueprint planner fallback is allowed.
```

The fixes should use the recommended review direction:

- make promotion execution consume replacement pairs, not derived append lists;
- reject append-style promotion at parser time;
- fail fast on mixed-valid/mixed-invalid graph or blueprint output;
- route all DiscoRAG structural model calls through the explicit structurer
  config;
- preserve LLM planner ordering when filtering blueprints to final contexts;
- validate all provenance references, including `source_chunk_ids`;
- record safe provider/structurer provenance;
- remove deterministic planner exports from public application surfaces;
- align contracts and smoke tests with actual behavior.

## Structural Failure Semantics

The graph parser and blueprint parser are part of the structural safety
boundary. They should not silently produce a partial structure from malformed
model output.

Required behavior:

- invalid JSON raises `ProcessingError`;
- missing required fields raise `ProcessingError`;
- wrong field types raise `ProcessingError`;
- unknown chunk ids raise `ProcessingError`;
- unknown relation ids raise `ProcessingError`;
- unknown RST unit ids raise `ProcessingError`;
- invalid relation labels raise `ProcessingError`;
- invalid role or constraint vocab raises `ProcessingError`;
- invalid plan-step structure raises `ProcessingError`;
- self-referential graph edges raise `ProcessingError`;
- mixed valid/invalid output raises `ProcessingError`.

The only graph drop exception is `unrelated`: it is a valid paper label that
means no materialized edge. `unrelated` may be ignored without failure.

Empty graph output is valid only when the LLM returns a structurally valid empty
`relations` array. A non-empty relation array containing only invalid
non-`unrelated` entries is invalid.

## Promotion Contract

Promotion is a bounded replacement operation.

The blueprint parser should preserve structured promotions:

```json
{
  "replace_chunk_id": "answer-weak",
  "with_chunk_id": "supplemental-condition",
  "reason": "The supplemental chunk contains the condition required by the query.",
  "source_chunk_ids": ["supplemental-condition"],
  "source_relation_ids": ["rel-2"],
  "source_rst_unit_ids": ["supplemental-condition:u1"]
}
```

Validation requirements:

- `replace_chunk_id` must be an original answer chunk;
- `with_chunk_id` must be a supplemental discourse chunk;
- `with_chunk_id` must appear in `final_answer_chunk_ids`;
- `replace_chunk_id` must not appear in `final_answer_chunk_ids`;
- any supplemental chunk in `final_answer_chunk_ids` must be explained by a
  valid promotion;
- final answer context count must remain `<= top_k`;
- duplicate final chunk ids are invalid.

Runtime application should consume `metadata["promotions"]` as replacement
pairs. It should not depend on `metadata["promoted_chunk_ids"]` as the source of
truth because that loses the replacement target.

Recommended runtime behavior:

```text
for each valid promotion:
  replace the context with replace_chunk_id by supplemental[with_chunk_id]
preserve final context budget
preserve planner ordering when constructing answer-facing blueprint
```

`promoted_chunk_ids` may be emitted as derived metadata for observability, but
it must not replace the structured promotion contract.

## Planner Ordering Contract

`AnswerBlueprint.ordered_chunk_ids` is planner output and must keep its relative
order after final context filtering.

When `DiscoRAGQueryService` builds the answer-facing blueprint:

```text
ordered_chunk_ids =
  [cid for cid in blueprint.ordered_chunk_ids if cid in final_context_ids]
  + any final_context_ids not already covered, in final context order
```

It must not reconstruct the ordering primarily from retrieval/context order,
because that discards the LLM planner's organization.

## Provenance Reference Validation

Planner output may cite:

- `source_chunk_ids`;
- `source_relation_ids`;
- `source_rst_unit_ids`.

All three are structural references and must be validated:

- `source_chunk_ids` must be known answer or supplemental discourse chunk ids;
- `source_relation_ids` must be relation ids present in the inter-chunk graph;
- `source_rst_unit_ids` must be unit ids present in the RST package.

Unknown provenance references are invalid because they indicate invented or
untraceable evidence.

## Structurer Config Boundary

The structurer model role owns all DiscoRAG structural LLM calls:

```text
DeepSeekChatIntraChunkDiscourseExtractor
LLMInterChunkDiscourseGraphBuilder
LLMDiscoRAGAnswerBlueprintBuilder
```

Initial runtime may reuse DeepSeek, but provider wiring must pass the explicit
structurer config to all three components. The answer model config remains
separate and should not be used accidentally for RST extraction.

## Safe Provenance Metadata

Graph and blueprint builders should include safe LLM provenance in metadata:

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "reasoning_effort": "high",
  "builder": "llm_inter_chunk_graph_builder"
}
```

If a base URL is included, it must be safe to log. Prefer host-only or sanitized
base URL metadata. Never record API keys.

## Public Surface Cleanup

The deterministic `DiscoRAGAnswerBlueprintBuilder` may remain only as a
test-local stub or a clearly non-runtime helper. It must not be exported from
`ragflow_lite.application.services`.

Runtime and public application exports must not expose deterministic graph or
deterministic blueprint builders as active services.

## Contract Alignment

Contracts should be updated after code changes land:

- `planning_role` count must match actual implementation.
- If implementation has 7 explicit planning roles plus `context` fallback,
  contracts must say that.
- If an eighth explicit role is intended, implementation and tests must add it.
- Contracts must describe structured promotion replacement, strict parser
  failure semantics, structurer config coverage, and public-surface cleanup.

## Smoke Test Requirement

The local DiscoRAG smoke must prove the promoted path actually happens.

Required assertions:

- supplemental promoted chunk is in final answer contexts;
- replaced weak answer chunk is not in final answer contexts;
- final answer context count stays `<= top_k`;
- answer-facing blueprint preserves planner ordering over final contexts;
- graph and blueprint builders are LLM-backed test doubles, not deterministic
  builders.

Conditional assertions such as `if supplemental in contexts: ...` are not
sufficient because they let a no-promotion regression pass.

## Non-Goals

- Do not optimize p99 latency.
- Do not introduce a new small-model provider.
- Do not add query-level downgrade to MiniRAG/basic RAG.
- Do not broaden fake-client policy beyond Infinity.
- Do not restore deterministic graph or blueprint planner fallback.
