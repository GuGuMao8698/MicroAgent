# LLM-Backed DiscoRAG Repo-Native Stabilization

Date: 2026-05-09
Status: Draft spec
Scope: `MicroRAG` DiscoRAG stabilization with LLM-backed RST extraction,
LLM-backed inter-chunk rhetorical graph construction, and LLM-backed blueprint
planning.

This document is a planning/specification note, not an active runtime contract.
Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md`.

## Decision

DiscoRAG's structural path must be LLM-backed through the three semantic
organization stages:

```text
MiniRAG retrieval
  -> EvidencePackageBuilder
  -> LLM intra-chunk RST extractor
  -> LLM inter-chunk rhetorical graph builder
  -> LLM DiscoRAG blueprint planner
  -> Answerer(mode="discorag", answer_blueprint=...)
```

The previous deterministic blueprint planner is the same class of problem as
the previous deterministic graph builder: it can produce stable mechanical
structures, but it cannot guarantee paper-faithful discourse-aware
organization. Runtime must not keep deterministic graph or deterministic
blueprint generation as fallback.

Deterministic code remains required for guards:

- JSON parsing;
- schema validation;
- relation type normalization;
- chunk id, relation id, and RST unit id validation;
- self-reference rejection;
- confidence clamping;
- final answer budget validation;
- bounded promotion application;
- answerer-side defensive fallback when an already validated blueprint cannot
  be consumed.

Those are contract guards, not graph/planner generation fallbacks.

## Paper Alignment

The DiscoRAG paper defines a discourse-aware route:

```text
retrieval
-> intra-chunk RST tree
-> inter-chunk rhetorical graph
-> discourse-driven planning / blueprint
-> answer generation
```

The paper's inter-chunk rhetorical graph is listwise model inference over the
retrieved chunks, not a local metadata rule graph.

The paper's discourse-driven planner is also model-generated. It is conditioned
on the query, chunks, RST trees, and inter-chunk graph. The repo-native
implementation should keep a structured `AnswerBlueprint` for engineering
control, but the plan itself must be produced by the structurer model and then
validated.

## Model Roles

DiscoRAG structural modules use a separate structurer-model role:

```text
structurer model:
  intra-chunk RST extraction
  inter-chunk rhetorical graph construction
  DiscoRAG blueprint planning

answer model:
  final natural language generation
```

Initial implementation may reuse the current DeepSeek provider/model for the
structurer role because no smaller dedicated model is available yet. That reuse
must be explicit in settings/provider wiring. A later small-model swap should be
a configuration change, not an architecture rewrite.

The graph builder and blueprint planner must not depend on the final answerer
object. They may use the same provider family, but their role, model name,
reasoning effort, and safe provider metadata should be observable.

## Boundary Contract

MiniRAG owns evidence selection.

DiscoRAG owns evidence organization:

- intra-chunk RST structures;
- inter-chunk rhetorical graph;
- answer blueprint planning;
- bounded promotion proposal and execution.

The structural builders and planner must not:

- query entity or relationship indexes;
- expand MiniRAG topology paths;
- change MiniRAG source selection;
- rerank standard query mode;
- retrieve additional chunks;
- append final answer contexts.

They may consume:

- query text;
- selected answer chunks;
- supplemental discourse-visible chunks;
- chunk text and stable canonical chunk ids;
- compact RST units/roles/relations;
- inter-chunk graph relations;
- MiniRAG metadata as prior context, not as a substitute for model inference.

## Budget Semantics

The final answer context budget is the public `top_n` / service `top_k` budget.

`discourse_selection_k` is a wider visibility budget for discourse
organization. By default it may be derived as `2 * top_k`.

Required behavior:

- `selected_for_answer=True` chunks form the initial final answer candidates.
- `selected_for_discourse=True` chunks form the discourse-visible evidence
  window.
- Supplemental discourse chunks are `selected_for_discourse=True` and
  `selected_for_answer=False`.
- Supplemental discourse chunks can be used by RST extraction, LLM graph
  construction, and LLM blueprint planning.
- Supplemental discourse chunks must not be appended to final contexts.
- Promotion must replace an existing final answer context and keep final answer
  context count bounded by `top_k`.

`chunk_token_budget` and `context_token_budget` are out of scope for this
stabilization.

## LLM Inter-Chunk Graph

The graph builder receives an `IntraChunkDiscoursePackage` and derives the
discourse-visible chunk set from its evidence package.

The prompt should include stable local identifiers:

```text
CHUNK[1] id=<canonical_chunk_id>
<chunk text>
```

If RST structures are available, include compact summaries:

```text
main/claim units
supporting units
condition / qualification / contrast units
available intra-chunk relations
```

Output is structured JSON:

```json
{
  "relations": [
    {
      "source_chunk_id": "chunk-c",
      "target_chunk_id": "chunk-a",
      "relation_type": "contradicts",
      "rationale": "The source updates or opposes the target claim.",
      "confidence": 0.82
    }
  ]
}
```

The allowed materialized inter-chunk relation labels are:

```text
supports
contradicts
elaborates
exemplifies
causes
results_from
enables
prevents
precedes
follows
simultaneous
background_for
generalizes
specifies
compares_with
contrasts_with
supplements
replaces
motivates
justifies
```

`UNRELATED` / `unrelated` is a paper label but must not materialize as an edge.
Unknown labels, unknown chunk ids, and self references must not enter the graph.

Graph failure semantics:

- invalid or unusable LLM graph output raises a clear `ProcessingError`;
- runtime must not call a deterministic graph builder as fallback;
- empty graph is valid only when the model returns a valid empty relation list
  or the discourse-visible chunk set is empty.

## Functional RST Projection

The RST extractor remains LLM-backed and should normalize noisy model output
into compact planning signals rather than attempting a full academic RST parser.

Target planning roles:

```text
claim
evidence
elaboration
definition
condition
qualification
contrast
context
```

Target intra-chunk relation projections:

```text
supports
elaborates
qualifies
contrasts
causes
temporal_next
example_of
defines
background_for
```

Unknown roles should degrade to `context`; unknown relation labels should be
dropped. Prompt labels and normalization aliases must stay aligned. For
example, if the prompt allows `sequences`, the normalizer must map it to
`temporal_next`.

## LLM Blueprint Planner

The blueprint planner is the third structural model stage. It consumes the query,
answer candidates, supplemental discourse chunks, RST structures, inter-chunk
graph, and final answer budget. It returns a structured plan that the answerer
can consume.

Recommended runtime class:

```text
LLMDiscoRAGAnswerBlueprintBuilder
```

The existing deterministic `DiscoRAGAnswerBlueprintBuilder` must not remain as a
runtime planner or public service export. If reusable code is needed, extract it
as non-semantic helpers such as:

```text
parse_llm_discorag_blueprint
validate_discorag_blueprint
apply_blueprint_to_contexts
```

Those helpers must not generate a plan.

### Planner Input

The planner prompt should include:

- query;
- final answer budget / `top_k`;
- answer chunk candidates;
- supplemental discourse-visible chunks;
- chunk text snippets;
- RST unit ids, unit text, roles, nuclearity, and intra-chunk relation
  projections;
- inter-chunk relation ids, source/target chunk ids, relation labels,
  confidence, and rationales;
- instruction that supplemental chunks may enter final contexts only through
  replacement promotion.

### Planner Output

Use strict JSON. Recommended shape:

```json
{
  "final_answer_chunk_ids": ["chunk-a", "chunk-c", "chunk-b"],
  "chunk_roles": {
    "chunk-a": "lead",
    "chunk-c": "support",
    "chunk-b": "caveat"
  },
  "promotions": [
    {
      "replace_chunk_id": "chunk-weak",
      "with_chunk_id": "chunk-c",
      "reason": "The supplemental chunk contains the condition required by the query.",
      "source_relation_ids": ["rel-2"],
      "source_rst_unit_ids": ["chunk-c:u1"]
    }
  ],
  "answer_constraints": [
    {
      "type": "caveat",
      "text": "Mention the condition before generalizing the answer.",
      "source_chunk_ids": ["chunk-b"],
      "source_relation_ids": ["rel-4"],
      "source_rst_unit_ids": ["chunk-b:u2"]
    }
  ],
  "plan_steps": [
    {
      "text": "State the direct answer from chunk-a.",
      "source_chunk_ids": ["chunk-a"],
      "source_relation_ids": [],
      "source_rst_unit_ids": ["chunk-a:u0"]
    }
  ],
  "metadata": {
    "planner": "llm_discorag_answer_blueprint_builder"
  }
}
```

Role vocabulary should stay compact:

```text
lead
support
background
caveat
comparison
definition
condition
context
```

Constraint vocabulary should stay compact:

```text
caveat
condition
conflict
comparison
support
background
definition
ordering
```

### Planner Validation

Validation must reject or fail clearly when:

- output is not valid JSON;
- required fields are missing;
- `final_answer_chunk_ids` is empty while answer candidates exist;
- final chunk count exceeds `top_k`;
- final chunk ids contain duplicates;
- any chunk id is unknown;
- a supplemental chunk appears in `final_answer_chunk_ids` without a matching
  valid replacement promotion;
- a promotion replaces an unknown chunk;
- a promotion replaces a supplemental chunk instead of an answer chunk;
- a promotion inserts an answer chunk as if it were supplemental;
- any referenced relation id is unknown;
- any referenced RST unit id is unknown;
- chunk roles reference chunks outside final/discourse-visible evidence;
- constraints or plan steps invent unsupported evidence.

Planner failure semantics:

- invalid or unusable LLM planner output raises a clear `ProcessingError`;
- runtime must not call a deterministic blueprint planner as fallback;
- query-level downgrade is not part of this slice;
- answerer fallback remains defensive only and should not mask planner failures.

## Answerer Consumption

The answerer receives:

- final contexts already bounded by `top_k`;
- `mode="discorag"`;
- validated `AnswerBlueprint`.

The answerer should use blueprint ordering, roles, constraints, and plan steps
when present. If the answerer receives a missing or invalid blueprint despite
upstream validation, it may fall back to score/context order as a defensive
guard, but this fallback must be observable with a reason such as:

```text
missing_blueprint
invalid_blueprint
partially_invalid_blueprint
```

Partial invalidity matters. A blueprint that contains both valid and unknown
chunk ids is invalid; the answerer must not silently ignore the unknown ids and
claim the blueprint was applied.

## Review Finding Disposition

The latest review findings are folded into this stabilization:

| Finding | Disposition |
| --- | --- |
| deterministic blueprint appends promoted ids | Replace with LLM planner and validation that forbids append promotion. Do not patch the deterministic planner as runtime code. |
| answerer only falls back when all blueprint ids are invalid | Still fix. Answerer fallback is the defensive last line and must catch partial invalidity. |
| RST prompt allows `sequences` but normalizer does not | Still fix. RST extractor remains active. |
| graph metadata omits provider/structurer provenance | Still fix. Graph builder remains active. |
| deterministic graph/blueprint stale exports | Clean runtime and public exports. |
| root contract omits structurer env/config surface | Update after source-backed behavior lands. |
| fake Infinity client concern | No fake Infinity client was found. Fake-client policy remains scoped to Infinity only. |

## Smoke And Verification

The full-chain smoke should exercise mocked structurer calls for graph and
blueprint planning, not deterministic graph or deterministic blueprint builders.

Smoke shape:

```text
MiniGraphFirstRetriever
  -> EvidencePackageBuilder
  -> fake or LLM-backed IntraChunkDiscourseExtractor
  -> LLMInterChunkDiscourseGraphBuilder with mocked response
  -> LLMDiscoRAGAnswerBlueprintBuilder with mocked response
  -> bounded promotion/application
  -> fake Answerer
```

Assertions:

- evidence package contains answer chunks and supplemental discourse chunks;
- graph builder receives all discourse-visible chunks;
- blueprint planner receives query, answer chunks, supplemental chunks, RST
  structures, graph relations, and final answer budget;
- invalid graph output does not silently become deterministic graph output;
- invalid planner output does not silently become deterministic blueprint output;
- planner output references existing relation ids and RST unit ids;
- final answer contexts stay `<= top_k`;
- promotion is replacement, not append;
- answerer receives `mode="discorag"` and a validated blueprint.

## Non-Goals

- Do not optimize p99 latency in this slice.
- Do not introduce a new small-model provider in this slice.
- Do not merge graph and blueprint model calls in this slice.
- Do not keep deterministic graph generation as runtime fallback.
- Do not keep deterministic blueprint generation as runtime fallback.
- Do not reintroduce `chunk_token_budget`.
- Do not treat `context_token_budget` as required DiscoRAG behavior.
- Do not clone the paper's benchmark setup, embedding choice, chunk size, beam
  width, or fine-tuning configuration.
- Do not expose graph/planner internals through HTTP query mode routing.
- Do not broaden fake-client policy beyond Infinity without a separate decision.

## Implementation Order

The execution plan is maintained in
[../plans/2026-05-08-discorag-repo-native-stabilization-plan.md](../plans/2026-05-08-discorag-repo-native-stabilization-plan.md).

High-level order:

1. Confirm current references and stale deterministic planner surfaces.
2. Define LLM blueprint parser/validator contract.
3. Implement LLM blueprint planner.
4. Wire runtime to LLM graph and LLM blueprint structural builders.
5. Remove deterministic graph/blueprint public runtime surfaces.
6. Fix still-relevant review findings.
7. Add full-chain smoke.
8. Promote source-backed facts into active contracts.
