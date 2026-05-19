# DiscoRAG Structurer Review Remediation

Date: 2026-05-10
Status: Draft remediation spec
Parent spec:
[2026-05-10-discorag-structurer-retry-timeout-repair.md](2026-05-10-discorag-structurer-retry-timeout-repair.md)

This document specifies the follow-up fixes required after reviewing the
committed-but-unpushed DiscoRAG structurer retry / timeout / repair slice.
It is planning material, not an active runtime contract. Active contracts
remain in `src/ragflow_lite/**/CONTRACTS.md` and should be updated only after
source-backed behavior lands.

## Problem Statement

The current implementation adds the intended high-level behavior:

```text
RST structurer -> graph structurer -> blueprint structurer
  with validation repair + timeout retry
  then explicit MiniRAG fallback after exhausted attempts
```

The review found several issues that weaken the runtime contract:

- fresh structurer attempts pass `timeout_seconds` into
  `DeepSeekChatCompletionsClient.complete_json()`, but the real method does not
  accept that parameter;
- the low-level DeepSeek client can retry timeout-like errors internally, which
  multiplies the structurer timeout budget;
- new structurer retry settings are read into config but not forwarded through
  provider wiring;
- `DiscoRAGQueryService` falls back on every structurer `ProcessingError`,
  rather than only on exhausted structurer attempts;
- exhausted fallback metadata is parsed from free-form error text;
- degraded fallback answers bypass success observability;
- RST extraction accepts missing or duplicate chunk structures silently;
- RST constructor validation is weaker than graph/blueprint constructor
  validation;
- a small unused blueprint local and an unused attempt-state helper create
  avoidable code noise.

## Decision

Use structured exhausted-attempt signaling instead of string parsing.

The structurer builders should raise a dedicated exception only when their
bounded attempt loop is exhausted:

```python
StructurerAttemptsExhaustedError(
    stage="blueprint",
    failure_type="validation_error",
    attempts=2,
    max_attempts=2,
    message="chunk_roles keys must exactly match final_answer_chunk_ids",
)
```

`DiscoRAGQueryService` must only degrade to MiniRAG direct answer when it catches
that dedicated exhausted-attempt exception from one of the three structurer
stages:

- `rst_extraction`
- `inter_chunk_graph`
- `blueprint`

Plain `ProcessingError` from those collaborators must remain a hard failure.
This keeps runtime bugs visible instead of turning them into MiniRAG fallback.

## DeepSeek Timeout And Retry Semantics

Structurer-level timeout ownership must be explicit.

Current risk:

```text
DeepSeek client internal retry: _MAX_DEEPSEEK_RETRIES = 2
Structurer max attempts:       discorag_structurer_max_attempts = 2
Timeout per SDK request:       discorag_structurer_timeout_seconds = 90

Worst case per stage:
90s * 3 low-level SDK attempts * 2 structurer attempts = 540s
```

That violates the intended small-task bound:

```text
90s * 2 structurer attempts = 180s max per structurer stage
```

Required behavior:

- normal non-structurer LLM calls may keep low-level transient retry by default;
- DiscoRAG structurer calls must disable low-level DeepSeek retry;
- each structurer attempt must correspond to one SDK request;
- timeout retry remains owned by the structurer builder;
- timeout metadata must reflect structurer attempts, not hidden transport
  retries.

Recommended API:

```python
complete_json(
    instructions: str,
    input_text: str,
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str

complete_messages_json(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str
```

`max_retries=None` preserves the existing default. Structurer builders pass
`max_retries=0`.

## Config Wiring

`DiscoRAGStructurerRuntimeConfig` already exposes:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Provider wiring must pass these values into:

- `DeepSeekChatIntraChunkDiscourseExtractor`
- `LLMInterChunkDiscourseGraphBuilder`
- `LLMDiscoRAGAnswerBlueprintBuilder`

This makes `DISCORAG_STRUCTURER_TIMEOUT_SECONDS` and
`DISCORAG_STRUCTURER_MAX_ATTEMPTS` real operator controls, not dead settings.

## RST Strictness

`DeepSeekChatIntraChunkDiscourseExtractor._load_structures()` must require exact
coverage of the selected evidence chunks.

Invalid outputs:

- missing structure for a selected chunk;
- duplicate `canonical_chunk_id`;
- unknown `canonical_chunk_id`.

All invalid outputs should raise `ProcessingError` inside the builder attempt
loop, triggering validation repair when attempts remain.

The extractor constructor must also reject:

- `timeout_seconds <= 0`
- `max_attempts < 1`

matching graph and blueprint builder behavior.

## Query Fallback Boundary

Fallback is allowed only for exhausted structurer attempts:

```text
StructurerAttemptsExhaustedError
  -> DiscoRAGQueryService catches it
  -> answerer receives retrieval_result.chunks
  -> mode="standard"
  -> blueprint=None
  -> metadata exposes explicit degraded DiscoRAG error
```

Fallback is not allowed for:

- plain `ProcessingError` from a structurer collaborator;
- promotion application errors;
- answer-facing blueprint filtering errors;
- answerer failures;
- retrieval failures;
- service-local invariant bugs.

## Fallback Metadata

Fallback metadata must be structured and user-visible:

```json
{
  "mode": "discorag",
  "answer_mode": "minirag_fallback",
  "discorag_degraded": true,
  "discorag_error": {
    "stage": "blueprint",
    "error_type": "StructurerAttemptsExhaustedError",
    "failure_type": "validation_error",
    "attempts": 2,
    "max_attempts": 2,
    "message": "...",
    "user_visible": true
  }
}
```

This metadata must not be reconstructed by regex-parsing free-form exception
strings.

## Observability

A degraded MiniRAG fallback is still a successful user-facing answer.

Required behavior:

- normal DiscoRAG success records success;
- degraded MiniRAG fallback records success too;
- degraded path remains distinguishable via metadata and, if logging supports
  it, a `degraded=true` field or event.

Hard failures still record failure.

## Simplification Boundary

After the correctness fixes land:

- remove the unused `all_items` local from
  `LLMDiscoRAGAnswerBlueprintBuilder.build()`;
- make `StructurerAttemptState` runtime-useful by using it to produce
  `StructurerAttemptsExhaustedError`, or delete unused state fields if the
  implementation does not need them;
- do not introduce a large generic retry framework unless it removes real
  duplication without obscuring stage-specific parsing.

## Non-Goals

- Do not restore deterministic graph or blueprint fallback.
- Do not add compact repair mode.
- Do not change MiniRAG retrieval behavior.
- Do not change answer budget semantics.
- Do not change Infinity fake-client policy.
- Do not convert the structurer path to async in this slice.

## Acceptance Criteria

- `DeepSeekChatCompletionsClient.complete_json(..., timeout_seconds=90)` works
  and forwards `timeout` to the SDK request.
- Structurer calls disable low-level DeepSeek retry so one structurer attempt is
  one SDK request.
- Provider wiring passes `timeout_seconds` and `max_attempts` to all three
  structurer components.
- Exhausted attempts raise `StructurerAttemptsExhaustedError` with structured
  stage, failure type, attempts, max attempts, and message.
- `DiscoRAGQueryService` falls back only on
  `StructurerAttemptsExhaustedError`.
- Plain `ProcessingError` from a structurer collaborator propagates.
- Fallback metadata is structured and user-visible without regex parsing.
- Degraded fallback records success observability.
- RST extraction rejects missing and duplicate selected chunk structures.
- Focused tests and full unit tests pass.
- Simplification removes or wires previously unused scaffolding.

