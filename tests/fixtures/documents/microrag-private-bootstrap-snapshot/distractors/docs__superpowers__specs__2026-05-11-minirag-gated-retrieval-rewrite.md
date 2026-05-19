# MiniRAG Gated Retrieval Rewrite

Date: 2026-05-11
Status: Draft design spec

This document specifies a gated retrieval rewrite feature for MiniRAG. It is
planning material, not an active runtime contract. Active contracts remain in
`src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Decision

Add an internal MiniRAG retrieval rewrite path that triggers only when the
first raw-query retrieval result is judged below expectation.

The feature is not a complete multi-query planner. It does not expose a new
HTTP parameter, does not add a new `/queries` mode, and does not introduce
LangGraph, LlamaIndex, HyDE, Step-Back, or a parallel multi-route retrieval
framework.

The first implementation should use one strategy:

```text
cot_grounding
```

`cot_grounding` asks the LLM to produce explicit, retrieval-facing steps for
solving the user query. These are structured grounding steps, not hidden model
chain-of-thought. The output is used as additional input to the grounding
layer, while the grounding layer remains responsible for extracting MiniRAG
retrieval parameters such as entities, relations, and answer-type keywords.
The original user query remains in the retrieval input set.

The intended high-level flow is:

```text
raw query
-> MiniRAG initial retrieval
-> cache initial candidates
-> quality gate
-> if acceptable:
     continue with initial candidates
-> if below expectation:
     request CoT grounding rewrite
     retry once if rewrite output fails
     if rewrite succeeds:
       use raw query + solution_steps for enriched grounding and retrieval
       merge enriched candidates with cached initial candidates
       apply MiniRAG final output window
       assess the final selected candidates without triggering another rewrite
     if rewrite still fails:
       record failure metadata
       continue with cached initial candidates
-> downstream DiscoRAG evidence organization and answering
```

## Current Implementation Facts

Current boundary re-check found:

- Root `AGENTS.md` is navigational, and `CLAUDE.md` points to `AGENTS.md`.
- Active runtime contracts remain under `src/ragflow_lite/**/CONTRACTS.md`.
- `docs/superpowers/specs` and `docs/superpowers/plans` are planning material,
  not runtime contract sources.
- `/queries` still routes only by `mode`, currently `standard` or `discorag`.
- The current active MiniRAG path is centered on
  `MiniGraphFirstRetriever.retrieve_context()`.
- `MiniGraphFirstRetriever` already owns the relevant sequence:
  grounding, entity index lookup, relationship index lookup, path expansion,
  auxiliary chunk retrieval, scoring, and final selection.
- `DiscoRAGQueryService` starts after retrieval. It should not become the owner
  of retrieval rewrite decisions.
- Existing `QueryGrounder` implementations produce basic grounded query data,
  but they do not own rewrite gating, retry state, initial-candidate caching,
  or rewrite failure fallback.
- Current DiscoRAG degraded fallback handles exhausted structurer attempts. It
  is a different fallback path from this feature's rewrite failure fallback.
- No current code references LangGraph or LlamaIndex.
- The top-level `阶段计划` directory is not part of the current repo tree used
  for this spec.

## Goals

1. Improve recall when the first raw-query MiniRAG retrieval is weak because
   the user query is vague, under-specified, or poorly aligned with indexed
   entity/relation wording.
2. Preserve the original query as a first-class retrieval input.
3. Add CoT-derived grounding only as a bounded retrieval enhancement.
4. Cache initial raw-query candidates before triggering the rewrite path.
5. Avoid repeating the same raw-query MiniRAG retrieval when rewrite fails.
6. Make gate decisions, rewrite attempts, failures, and fallback source
   observable in metadata.
7. Preserve existing MiniRAG final output budgets and DiscoRAG downstream
   contracts.

## Non-Goals

- Do not add a public API field for rewrite strategy.
- Do not add a new `QueryModeRouter` mode.
- Do not move retrieval rewrite into `DiscoRAGQueryService`.
- Do not turn this into a full query decomposition or multi-query planner.
- Do not add HyDE, Step-Back, or mixed rewrite strategies in this slice.
- Do not add LangGraph or LlamaIndex in this slice.
- Do not add support for new document formats.
- Do not bypass MiniRAG final output windows.
- Do not use deterministic fallback text as a fake CoT rewrite result.
- Do not treat hidden model chain-of-thought as a runtime contract.
- Do not let CoT rewrite directly output MiniRAG retrieval parameters such as
  entities, relations, or answer-type keywords.

## Core Concepts

### Initial Candidate Snapshot

The first raw-query MiniRAG pass must produce a reusable snapshot before the
rewrite gate triggers.

The snapshot should represent the candidates and selection state that would
have continued into the downstream path if no rewrite were attempted.

The snapshot should be sufficient to continue the query without running the
same raw-query retrieval again.

Suggested conceptual fields:

```text
InitialCandidateSnapshot
  query: str
  grounded_query: GroundedQuery
  candidates: list[RetrievedChunk]
  source_selection: GraphFirstSourceSelection | None
  metadata: dict
```

The exact type shape can be adjusted during implementation, but the contract
must preserve one rule: rewrite failure falls back to this snapshot, not to a
new raw-query retrieval.

### Grounding Gate Decision

The gate decides whether the initial retrieval result is acceptable or should
trigger `cot_grounding`.

The gate must be deterministic and local. It must not call an LLM or use an
LLM-assisted judge. SuperMew is only a reference for the `route +
rewrite_needed + trace` shape, not for its LLM binary relevance grader.

Suggested conceptual fields:

```text
GroundingGateDecision
  should_rewrite: bool
  route: "accept" | "rewrite"
  reason: str
  signals: dict
```

The first implementation should use structural signals from the initial
candidate snapshot. Examples include:

- no entity or relationship matches;
- fewer selected answer candidates than `ceil(requested_top_n / 2)`;
- weak source selection metadata;
- empty or low-confidence auxiliary retrieval;
- explicit retriever fallback reason.

The selected-answer-candidate count must be computed from final candidates
selected for answer, not from all internal graph, path, auxiliary, or
discourse-only candidates. Examples:

```text
top_n = 2 -> trigger when selected_answer_candidate_count < 1
top_n = 3 -> trigger when selected_answer_candidate_count < 2
top_n = 4 -> trigger when selected_answer_candidate_count < 2
top_n = 5 -> trigger when selected_answer_candidate_count < 3
top_n = 8 -> trigger when selected_answer_candidate_count < 4
```

The gate should be conservative. It should not trigger CoT rewrite for every
query. Prompt-based strictness controls are out of scope because they can swing
the gate between optimistic under-triggering and pessimistic over-triggering.

### CoT Grounding Result

`cot_grounding` produces explicit retrieval-facing steps. These steps describe
how to approach the user's question for retrieval purposes.

Suggested conceptual fields:

```text
CoTGroundingResult
  status: "succeeded" | "failed"
  strategy: "cot_grounding"
  original_query: str
  solution_steps: list[str]
  attempts: int
  failure_reason: str | None
```

The field name `solution_steps` is intentional. It should not be documented as
hidden chain-of-thought. It is a structured, explicit output requested for
retrieval grounding.

`CoTGroundingResult` must not include entity, relation, answer-type, or keyword
fields. Those are grounding outputs, not CoT rewrite outputs. The grounding
layer consumes the original query plus `solution_steps` and then extracts the
MiniRAG retrieval parameters.

### Enriched Grounding Input

Successful CoT rewrite must create one explicit enriched grounding input before
calling the grounding layer.

Suggested conceptual fields:

```text
EnrichedGroundingInput
  original_query: str
  solution_steps: list[str]
```

Required invariants:

- `original_query` must be the normalized raw user query from the initial
  candidate snapshot.
- `solution_steps` must come from the successful `CoTGroundingResult`.
- `solution_steps` must contain at least one non-empty step after trimming.
- the enriched grounding input must contain both `original_query` and
  `solution_steps`;
- the implementation must not call the grounding layer with only
  `solution_steps`;
- the implementation must not treat an empty or unusable `solution_steps` result
  as a successful rewrite;
- if `CoTGroundingResult.original_query` does not match the snapshot query, the
  rewrite result must be treated as invalid.

One acceptable rendering for grounding is:

```text
Original query:
<original_query>

Solution steps:
1. <solution_steps[0]>
2. <solution_steps[1]>
...
```

The exact rendering can be chosen during implementation, but this contract is
fixed: triggered successful rewrite means grounding receives the original query
and the CoT solution steps together.

### Post-Rewrite Assessment

The initial gate may trigger at most one CoT rewrite cycle. After a successful
rewrite and enriched MiniRAG retrieval, the implementation may evaluate the same
deterministic gate signals again, but only as a post-rewrite assessment.

Post-rewrite assessment must not trigger a second rewrite.

If the post-rewrite result still fails the gate, the system should continue with
the chunks produced by enriched MiniRAG retrieval and mark the retrieval as
degraded.

Suggested conceptual fields:

```text
PostRewriteAssessment
  gate_passed: bool
  reason: str
  signals: dict
```

If `gate_passed` is false, metadata should record that rewrite already ran and
still did not produce enough retrieval evidence. The answerer must receive an
explicit user-facing notice so it can tell the user that retrieval rewrite was
attempted but the available knowledge still appears insufficient.

The notice should be separate from normal answer content and should not invent
missing facts. It should communicate:

- retrieval rewrite was triggered;
- rewrite completed and enriched MiniRAG retrieval ran;
- the post-rewrite result still did not satisfy the deterministic gate;
- possible causes include missing relevant documents in the knowledge base or a
  query that is still too ambiguous;
- the user may need to rephrase the query or add the needed documents.

## Detailed Behavior

### Normal Path

When the gate decides the initial result is acceptable:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate accepts
-> continue with initial candidates
```

Metadata should record that rewrite was evaluated and not triggered.

Suggested metadata:

```text
retrieval_rewrite.enabled = true
retrieval_rewrite.triggered = false
retrieval_rewrite.gate_reason = "<reason>"
```

### Triggered And Successful Rewrite Path

When the gate decides the initial result is below expectation:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate triggers rewrite
-> cot_grounding structured output
-> enriched grounding from raw query + solution_steps
-> enriched MiniRAG retrieval
-> merge cached initial candidates + enriched candidates
-> apply final MiniRAG output window
-> post-rewrite assessment without recursive rewrite
-> downstream DiscoRAG
```

The original query must remain part of the retrieval input set. The CoT
grounding output enhances the query; it does not replace it.

The enriched retrieval pass should enhance both graph grounding and auxiliary
chunk retrieval:

- graph grounding should build an `EnrichedGroundingInput` from the initial
  snapshot query plus `solution_steps`, pass the rendered input to the grounding
  layer, and let the grounding layer extract entity, relation, and answer-type
  retrieval parameters;
- auxiliary chunk retrieval should use an enriched text query built from the
  original query plus `solution_steps`;
- the original query must remain in the auxiliary retrieval input so the
  enhanced query stays anchored to the user's wording.

The final selected chunks must remain bounded by the existing MiniRAG final
window. Additional candidate sources may expand the pool, but they must not
unboundedly append to final answer contexts.

If post-rewrite assessment still fails the gate, the enriched final selected
chunks still continue into DiscoRAG. The system must not run another CoT rewrite.
Instead, it must attach answer-facing degraded retrieval metadata and an
instruction for the answerer to explicitly tell the user that retrieval rewrite
was attempted but available evidence still appears insufficient.

### Triggered But Failed Rewrite Path

When CoT grounding fails:

```text
raw query
-> initial MiniRAG retrieval
-> initial candidate snapshot
-> gate triggers rewrite
-> cot_grounding attempt 1 fails
-> cot_grounding attempt 2 fails
-> record failure metadata
-> use initial candidate snapshot
-> downstream DiscoRAG
```

Failure must not cause a second raw-query MiniRAG retrieval. The cached initial
candidate snapshot is the fallback source.

Suggested metadata:

```text
retrieval_rewrite.enabled = true
retrieval_rewrite.triggered = true
retrieval_rewrite.strategy = "cot_grounding"
retrieval_rewrite.status = "failed"
retrieval_rewrite.attempts = 2
retrieval_rewrite.failure_reason = "<summary>"
retrieval_rewrite.fallback_source = "initial_candidate_snapshot"
```

## Retry And Failure Rules

The first implementation should allow:

```text
initial CoT grounding attempt + 1 retry
```

Rewrite failures include:

- invalid structured output;
- missing or empty `solution_steps`;
- `CoTGroundingResult.original_query` does not match the initial snapshot query;
- provider timeout;
- provider exception;
- empty usable grounding result.

After attempts are exhausted:

- record failure metadata;
- preserve the original exception summary at a safe level of detail;
- continue with `InitialCandidateSnapshot`;
- do not retry raw-query retrieval;
- do not fail the whole `/queries` request only because rewrite failed.

## Candidate Merge And Budget Rules

The feature may increase candidate sources, but it must not increase final
answer contexts beyond the MiniRAG final output budget.

Merge rules should preserve:

- stable chunk identity;
- deduplication by canonical chunk id;
- source metadata for whether a chunk came from the initial pass, enriched
  graph pass, enriched auxiliary pass, or multiple passes;
- final ordering semantics that are explicit and test-covered.

This spec does not mandate the final scoring formula. The plan should choose
the smallest formula that preserves current behavior when rewrite is not
triggered and gives enriched candidates a clear, observable source trail when
rewrite is triggered.

## Layer Boundaries

### API Layer

No API schema change is required for the first implementation.

`POST /queries` should continue to accept the existing request shape and route
only by `mode`.

### Query Router

`QueryModeRouter` should remain a mode dispatcher. It should not learn
retrieval rewrite policy.

### MiniRAG Retrieval Layer

`MiniGraphFirstRetriever` is the preferred owner of the feature because it
already coordinates grounding, graph evidence lookup, auxiliary retrieval, and
final selection.

The enriched retrieval behavior should stay inside this layer: CoT grounding
may enrich graph lookup inputs and auxiliary chunk retrieval inputs, but it
should not create a separate planner above `MiniGraphFirstRetriever`.

If the implementation needs new ports, prefer a wrapper or sibling component
around `QueryGrounder` rather than forcing gate, retry, and cache semantics into
the existing basic `QueryGrounder.ground(query)` contract.

### DiscoRAG Layer

`DiscoRAGQueryService` should receive the final MiniRAG-selected retrieval
result after the rewrite decision has already been resolved.

It should not initiate CoT rewrite, rerun MiniRAG, or own rewrite failure
fallback.

The existing DiscoRAG degraded fallback for exhausted structurer attempts is
separate from this feature. This feature's fallback is retrieval-level fallback
to `InitialCandidateSnapshot`.

### Answerer Layer

Answerers should not need to know the CoT grounding text. They may receive
metadata that explains rewrite status, but the answer contract should not depend
on the rewrite internals.

There is one answer-facing exception: when CoT rewrite succeeds but the
post-rewrite assessment still fails the deterministic gate, the answerer must
receive a degraded retrieval notice. The notice should be delivered through a
dedicated metadata or instruction path, not by mixing the CoT solution steps into
the answer prompt.

This may require a dedicated prompt fragment or answerer instruction used only
for this condition. The fragment should require the final answer to explicitly
tell the user that retrieval rewrite already ran but the retrieved evidence is
still likely insufficient, and that likely causes are missing knowledge-base
documents or an ambiguous query.

## Observability

The feature should expose enough metadata to debug the path taken without
requiring prompt logs.

At minimum:

```text
retrieval_rewrite.enabled
retrieval_rewrite.triggered
retrieval_rewrite.strategy
retrieval_rewrite.status
retrieval_rewrite.gate_reason
retrieval_rewrite.attempts
retrieval_rewrite.failure_reason
retrieval_rewrite.fallback_source
retrieval_rewrite.initial_candidate_count
retrieval_rewrite.enriched_candidate_count
retrieval_rewrite.post_rewrite_gate_passed
retrieval_rewrite.post_rewrite_gate_reason
retrieval_rewrite.answer_notice_required
```

Successful triggered rewrite should record that final candidates may contain
initial-only, enriched-only, and shared sources.

Triggered rewrite followed by failed post-rewrite assessment should record that
rewrite already ran, no second rewrite was attempted, and an answer-facing
degraded retrieval notice is required.

Failed triggered rewrite should record that downstream processing used the
initial candidate snapshot.

## Risks

### Scope Drift

The main risk is turning `cot_grounding` into a full multi-query planner. The
first implementation must stop at gated grounding enhancement.

### Over-Triggering

If the gate is too eager, simple queries may become slower and less precise.
The first gate should be conservative, observable, and deterministic. It must
not rely on prompt wording such as "strict" to tune rewrite frequency.

### Candidate Merge Drift

The new path adds candidate sources. The final window prevents unbounded final
context growth, but merge, dedupe, ordering, and metadata propagation still
need focused tests.

### Output Boundary Drift

The LLM may produce verbose reasoning text. The runtime contract should accept
only structured `solution_steps`, not arbitrary prose as a hidden decision
source and not direct entity, relation, or answer-type extraction.

### Fallback Ambiguity

Rewrite failure fallback and DiscoRAG structurer fallback are separate. Metadata
must make it clear which fallback happened.

### Recursive Rewrite Drift

The rewrite path must not recurse. A successful rewrite may be followed by a
post-rewrite assessment, but that assessment is only for observability and
answer-facing warning behavior. It must not trigger another CoT rewrite.

## Validation Requirements

Implementation should add focused tests before changing behavior.

Required coverage:

- gate not triggered keeps current MiniRAG output behavior;
- gate is deterministic and does not call an LLM judge;
- gate triggers when selected answer candidates are fewer than
  `ceil(requested_top_n / 2)`;
- gate candidate-count logic uses final answer candidates, not internal graph,
  path, auxiliary, or discourse-only candidates;
- gate triggered snapshots initial candidates before CoT rewrite;
- successful CoT rewrite uses raw query plus `solution_steps`;
- successful CoT rewrite calls the grounding layer with an input containing both
  the original query and `solution_steps`;
- successful CoT rewrite never calls the grounding layer with only
  `solution_steps`;
- empty `solution_steps` or mismatched `CoTGroundingResult.original_query` is
  treated as rewrite failure, not success;
- grounding layer, not CoT rewrite, extracts entity/relation/answer-type
  retrieval parameters;
- enriched and initial candidates are deduped and remain final-window bounded;
- post-rewrite assessment can mark the result degraded but never triggers a
  second rewrite;
- post-rewrite gate failure still sends enriched MiniRAG chunks into DiscoRAG;
- post-rewrite gate failure adds answer-facing metadata or instructions that
  require the final answer to tell the user rewrite already ran but evidence
  remains insufficient;
- failed first CoT attempt retries once;
- exhausted CoT attempts record failure metadata;
- exhausted CoT attempts continue with cached initial candidates;
- exhausted CoT attempts do not rerun raw-query MiniRAG retrieval;
- `DiscoRAGQueryService` receives a resolved retrieval result and does not own
  rewrite decisions;
- `/queries` request schema and mode routing stay unchanged.

Likely test files:

- `tests/unit/application/test_mini_graph_first_retriever.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/domain/test_minirag_topology_models.py`
- `tests/unit/infrastructure/test_deepseek_query_grounder.py`
- `tests/unit/infrastructure/test_openai_query_grounder.py`
- `tests/unit/api/test_v0_routes.py`

Provider wiring may also require:

- `tests/unit/api/test_providers.py`

## Open Questions For Plan

The implementation plan should decide:

1. Whether `InitialCandidateSnapshot`, `GroundingGateDecision`, and
   `CoTGroundingResult` become typed domain models or structured metadata first.
2. Whether CoT grounding is implemented as a wrapper around `QueryGrounder` or a
   sibling port.
3. The exact candidate merge ordering rule.
4. The exact metadata path used to surface rewrite observability.
5. The exact answerer metadata or instruction path for post-rewrite degraded
   retrieval notices.
