# DiscoRAG Structurer Retry, Timeout, And Repair

Date: 2026-05-10
Status: Draft implementation spec
Parent specs:
[2026-05-08-discorag-repo-native-stabilization.md](2026-05-08-discorag-repo-native-stabilization.md),
[2026-05-10-discorag-review-findings-remediation.md](2026-05-10-discorag-review-findings-remediation.md)

This document specifies bounded retry and repair behavior for DiscoRAG
structurer LLM calls. It is planning material, not an active runtime contract.
Active contracts remain in `src/ragflow_lite/**/CONTRACTS.md` and should be
updated only after source-backed behavior lands.

## Decision

DiscoRAG structural validation remains strict, but the first invalid or timed
out structurer attempt should not immediately fail the user-facing query.

The structural path should become:

```text
MiniRAG retrieval
→ LLM intra-chunk RST extraction
→ strict validation, with bounded LLM repair on validation failure
→ LLM inter-chunk discourse graph
→ strict validation, with bounded LLM repair on validation failure
→ LLM DiscoRAG blueprint planner
→ strict validation, with bounded LLM repair on validation failure
→ bounded promotion application
→ answerer
```

Runtime code must still not mechanically repair invalid structure. Validation
failure recovery belongs to the structurer LLM attempt loop, not to
`DiscoRAGQueryService` or answerers.

Required boundaries:

- validation errors trigger bounded LLM repair;
- small structurer tasks time out after 90 seconds by default;
- timeout retries create a fresh attempt;
- validation repair uses multi-turn messages and appends a short validation
  feedback turn;
- validation repair does not repeat the full original task in the repair turn;
- no `compact` repair mode is introduced in this slice;
- no deterministic graph or blueprint fallback is introduced;
- exhausted structurer attempts trigger an explicit DiscoRAG degraded fallback
  to MiniRAG-selected final answer chunks;
- the degraded fallback must be user-visible in answer metadata;
- contracts are promoted only after implementation and tests land.

## Current Implementation Facts

Current local investigation found:

- `DeepSeekChatCompletionsClient.complete()` and `complete_json()` are
  synchronous wrappers around `client.chat.completions.create(...)`.
- The public DeepSeek client contract accepts only `instructions` and
  `input_text`.
- The DeepSeek transport currently sends two messages: one `system` message and
  one `user` message.
- Low-level transport retry exists for retryable API/connection/timeout-like
  exceptions, but there is no schema validation repair loop.
- `DeepSeekChatIntraChunkDiscourseExtractor`,
  `LLMInterChunkDiscourseGraphBuilder`, and
  `LLMDiscoRAGAnswerBlueprintBuilder` each call the LLM once and then parse once.
- No request id, cancellation token, or server-side close mechanism exists in
  the current code.

DeepSeek Chat Completions supports a `messages` array for multi-turn
conversation, but the API is stateless. The caller must send the conversation
history needed for each attempt.

## Retry Types

### Transport Retry

Transport retry covers transient call failures, such as rate limits,
connection errors, provider timeouts, and 5xx responses.

Transport retry is already partially handled by `DeepSeekChatCompletionsClient`.
This spec does not remove that behavior. It adds explicit structurer-level
timeouts and validation repair.

### Timeout Retry

Timeout retry handles an attempt that does not return within the structurer
timeout budget.

Default policy:

```text
discorag_structurer_timeout_seconds = 90
```

Timeout behavior:

```text
attempt-1 starts
→ attempt-1 does not return within 90 seconds
→ attempt-1 is marked expired
→ attempt-2 starts with a fresh original request
→ any late attempt-1 result is ignored
```

Timeout retry must not reuse a partially available answer from the timed-out
attempt. A timeout attempt has no trustworthy assistant message for repair.

If the underlying SDK supports a request timeout, the client should pass the
timeout to the SDK request. If the SDK does not provide true server-side
cancellation, the local runtime must still treat the attempt as expired and
prevent any late result from being consumed.

This spec does not require a full async rewrite. Prefer the smallest correct
implementation that gives the structurer call a bounded request timeout and
clear retry behavior.

### Validation Repair

Validation repair handles an LLM response that returns within the timeout
budget but fails parser or schema validation.

Validation repair must not patch JSON in code. It must ask the structurer LLM
to generate a new complete JSON object, then run the same parser and validator
again.

Validation repair uses multi-turn messages:

```text
system: original structurer instructions
user: original structurer input
assistant: previous invalid JSON output
user: short validation feedback and regeneration instruction
```

The repair user turn should be short. It should include:

- that the previous JSON is invalid;
- the validation error summary;
- only the minimum constraints needed to correct the error;
- an instruction to regenerate one complete JSON object;
- an instruction not to output a patch, markdown, or prose.

The repair user turn must not repeat the complete original task or full
evidence text. The original task is already present in the message history.

The assistant message can contain the previous invalid JSON because it is the
actual previous model output in the conversation history. The repair user turn
should not duplicate that output.

## Attempt Limits

Suggested first implementation:

```text
initial attempt + 1 validation repair attempt
initial attempt + 1 timeout retry attempt
```

The configuration may expose:

```text
discorag_structurer_max_attempts = 2
discorag_structurer_timeout_seconds = 90
```

`max_attempts` counts complete attempts, including the first attempt.

Examples:

```text
max_attempts = 2

validation path:
  attempt 1 returns invalid JSON
  attempt 2 sends multi-turn repair
  attempt 2 valid → success

timeout path:
  attempt 1 times out
  attempt 2 sends fresh original request
  attempt 2 valid → success

exhausted path:
  attempt 1 invalid
  attempt 2 invalid
  raise ProcessingError with both attempt failures summarized
  DiscoRAGQueryService catches the exhausted structurer failure
  answerer receives MiniRAG-selected top_n chunks without a DiscoRAG blueprint
  AnswerResult.metadata exposes the DiscoRAG failure and degraded fallback
```

## Message API Contract

The DeepSeek client should retain existing convenience methods:

```python
complete(instructions: str, input_text: str) -> str
complete_json(instructions: str, input_text: str, *, max_tokens: int = ...) -> str
```

Add message-based methods for structurer repair:

```python
complete_messages(messages: list[dict[str, str]], *, timeout_seconds: float | None = None) -> str
complete_messages_json(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = ...,
    timeout_seconds: float | None = None,
) -> str
```

The existing methods should delegate to the message-based methods by building:

```python
[
    {"role": "system", "content": instructions},
    {"role": "user", "content": input_text},
]
```

JSON methods must continue to set `response_format={"type": "json_object"}` and
must continue to include the JSON-only instruction when needed.

## Attempt Metadata And Observability

Structurer retries should be observable without exposing secrets or full
private prompt bodies.

Each final graph, blueprint, or RST package metadata should include safe
attempt information where appropriate:

```json
{
  "structurer_attempts": 2,
  "structurer_repair_count": 1,
  "structurer_timeout_count": 0,
  "structurer_last_failure_type": "validation_error"
}
```

Do not log API keys, full raw evidence, or full model outputs in metadata.
Tests can inspect fake-client calls directly, but runtime metadata should remain
safe.

## Stage Ownership

### Client Layer

The DeepSeek client owns:

- raw SDK invocation;
- JSON response format;
- low-level retry for transport failures;
- request timeout forwarding when supported by the SDK;
- message-based completion API.

The client does not own schema-specific validation repair prompts.

### Builder Layer

Each structurer builder owns:

- original prompt construction;
- parser invocation;
- validation repair prompt construction;
- bounded repair attempts;
- stage-specific attempt metadata.

The three affected stages are:

- `DeepSeekChatIntraChunkDiscourseExtractor`;
- `LLMInterChunkDiscourseGraphBuilder`;
- `LLMDiscoRAGAnswerBlueprintBuilder`.

### Service And Answerer Layers

`DiscoRAGQueryService` and answerers remain strict consumers:

- do not append missing blueprint ordering;
- do not patch promotion metadata;
- do not invent graph edges or RST units;
- do not downgrade to deterministic planning.

If a builder exhausts its attempts and raises `ProcessingError`, the service
should not silently fail the query. It should degrade to MiniRAG direct answer
mode with explicit error metadata.

## Exhausted Structurer Fallback

When RST extraction, inter-chunk graph construction, or blueprint planning
exhausts `discorag_structurer_max_attempts`, DiscoRAG should stop the DiscoRAG
structural path and answer with the MiniRAG-selected final answer chunks.

Fallback input:

```text
retrieval_result.chunks
```

These are the `top_n` final answer contexts selected by the MiniRAG retriever.
Supplemental discourse chunks must not be appended during fallback.

Fallback answer request:

```text
query = original query
contexts = retrieval_result.chunks
mode = "standard" or an equivalent non-blueprint answer mode
blueprint = None
metadata includes explicit DiscoRAG degraded-fallback error
```

The fallback must be visible to the caller. Because `/queries` already returns
`AnswerResult.metadata`, the answer result must include a user-facing metadata
block such as:

```json
{
  "mode": "discorag",
  "answer_mode": "minirag_fallback",
  "discorag_degraded": true,
  "discorag_error": {
    "stage": "blueprint",
    "error_type": "ProcessingError",
    "failure_type": "validation_error",
    "attempts": 2,
    "max_attempts": 2,
    "message": "LLM DiscoRAG blueprint builder failed after 2 attempts: chunk_roles keys must exactly match final_answer_chunk_ids.",
    "user_visible": true
  }
}
```

The exact key names may follow existing metadata conventions, but the data must
make these facts obvious:

- the user requested DiscoRAG;
- DiscoRAG degraded to MiniRAG direct answer;
- which DiscoRAG stage failed:
  - `rst_extraction`;
  - `inter_chunk_graph`;
  - `blueprint`;
- why it failed:
  - `validation_error`;
  - `timeout`;
  - `transport_error`;
- how many attempts were made;
- what maximum attempt limit was reached;
- a concise, user-visible error message suitable for a future frontend.

This is a fallback from the DiscoRAG structural path to MiniRAG direct answer,
not a deterministic DiscoRAG repair. The service must not create a graph,
blueprint, promotion, or ordering after the structurer stage has failed.

Runtime invariant failures after a supposedly valid blueprint, such as
promotion metadata becoming inconsistent during answer-facing filtering, remain
hard `ProcessingError` failures unless they are explicitly classified as
structurer-exhaustion errors. This prevents the fallback from hiding local
runtime bugs.

## Stage-Specific Repair Guidance

### RST Extractor

Repair feedback should cover:

- unknown `canonical_chunk_id`;
- malformed `chunks` array;
- invalid or missing `units`;
- invalid unit indexes;
- invalid span fields;
- mixed valid and unknown chunk ids.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- canonical_chunk_id "chunk_x" is not one of the provided evidence items.

Regenerate one complete JSON object using only canonical_chunk_id values from
the original evidence. Do not output a patch. Do not include markdown or prose.
```

### Inter-Chunk Graph Builder

Repair feedback should cover:

- unknown source or target chunk id;
- self-referential edge;
- invalid relation label;
- malformed relation object;
- invalid `relations` type.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- relation[0].target_chunk_id "chunk_missing" is not in the provided chunk ids.

Regenerate one complete JSON object. Use only the valid relation labels and
exact chunk ids from the original prompt. Do not output a patch. Do not include
markdown or prose.
```

### Blueprint Builder

Repair feedback should cover:

- missing final chunk ids in `ordered_chunk_ids`;
- `chunk_roles` not exactly covering `final_answer_chunk_ids`;
- append-style promotion;
- stale or invalid promotion pairs;
- unknown relation ids;
- unknown RST unit ids;
- source references to unknown chunks.

Repair message example:

```text
Your previous JSON is invalid.

Validation error:
- chunk_roles keys must exactly match final_answer_chunk_ids.
- missing role for chunk_id "chunk_b".

Regenerate one complete JSON object. Do not output a patch. Promotions must be
replacement-only: the replaced answer chunk must be absent from
final_answer_chunk_ids and the supplemental chunk must be present.
```

## Non-Goals

- Do not add `compact` repair mode in this slice.
- Do not introduce a new small-model provider.
- Do not optimize p99 latency beyond bounded timeout behavior.
- Do not convert the whole LLM stack to async unless required by a verified SDK
  limitation.
- Do not promise server-side request cancellation if DeepSeek does not provide
  it.
- Do not add deterministic graph, RST, or blueprint fallback.
- Do not change Infinity fake-client policy.
- Do not change MiniRAG retrieval behavior.
- Do not silently fallback to MiniRAG without user-visible error metadata.

## Acceptance Criteria

The implementation is complete when:

- DeepSeek client can send message-based JSON calls while preserving existing
  `complete_json()` behavior.
- Structurer calls have a configurable timeout defaulting to 90 seconds.
- Timeout failure can retry with a fresh original request.
- Validation failure can retry with a multi-turn repair message that does not
  repeat the full original task in the repair turn.
- Repair attempts regenerate complete JSON and re-enter the same strict parser.
- Exhausted structurer attempts degrade to MiniRAG-selected final answer chunks
  and expose a user-visible DiscoRAG error in `AnswerResult.metadata`.
- Blueprint, graph, and RST builders each have focused retry tests.
- Full-chain DiscoRAG smoke proves a validation repair can succeed without
  runtime deterministic repair.
- Full-chain DiscoRAG smoke proves exhausted structurer attempts fallback to
  MiniRAG direct answer with explicit error metadata.
- Existing live Infinity provider tests still pass.
