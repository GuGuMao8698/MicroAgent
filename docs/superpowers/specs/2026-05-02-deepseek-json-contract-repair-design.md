# DeepSeek JSON Contract Repair Design

## Goal

Fix the DeepSeek migration review findings without reopening unrelated provider, retrieval, schema, or eval artifact work.

The repair makes DeepSeek JSON Output a first-class local contract, restores transient retry behavior for the new DeepSeek runtime path, and upgrades tests so they prove the DeepSeek contract rather than the copied OpenAI/Ark request shape.

## Source Findings

This design addresses four review findings:

- DeepSeek JSON calls only set `response_format={"type": "json_object"}` and do not centrally guarantee the vendor prompt contract.
- `DeepSeekChatDeepEvalModel` advertises structured-output support but uses raw chat output plus local schema validation without a DeepSeek-specific schema prompt contract.
- The new `DeepSeekChatAnswerer` path dropped the retry/backoff behavior that existed in the old `OpenAIResponsesAnswerer`.
- New tests mostly assert the copied request shape or feed perfect JSON, so they can pass while the real provider contract is still wrong.

## DeepSeek Docs Contract

The local DeepSeek docs under `网页/deepseek` are the source of truth for this repair. Any follow-up doc reading must parse local HTML with `defuddle`.

The relevant JSON Output contract is:

- Use Chat Completions with the OpenAI-compatible DeepSeek base URL `https://api.deepseek.com`.
- Send `response_format={"type": "json_object"}` for JSON Output calls.
- Ensure the system or user prompt includes the word `json`.
- Include an example output shape or schema in the prompt.
- Set a bounded `max_tokens` to reduce truncation risk.
- Treat empty `content` as an expected provider failure mode and raise a clear local error.

This project already uses `deepseek-v4-flash`, `reasoning_effort="high"`, and `extra_body={"thinking": {"type": "enabled"}}`; this repair keeps those defaults.

## Scope

In scope:

- A centralized DeepSeek JSON prompt guard in `DeepSeekChatCompletionsClient.complete_json(...)`.
- A `max_tokens` option for DeepSeek Chat Completions calls, with a sane default for JSON calls.
- A local schema prompt builder for `DeepSeekChatDeepEvalModel.generate(..., schema=...)` and `a_generate(..., schema=...)`.
- Local Pydantic validation for DeepSeek deepeval schema outputs.
- Optional JSON text normalization only for small provider wrappers, such as fenced ```json blocks, if tests make the policy explicit.
- Retry/backoff for transient DeepSeek Chat Completions failures.
- Focused fake-backed unit tests proving prompt, request, retry, and schema behavior.
- Small AGENTS/docs updates only if the implementation changes the local workflow contract.

Out of scope:

- Regenerating `tests/fixtures/evals/synthetic_goldens.json`.
- Running long live deepeval jobs as part of the repair implementation.
- Changing embedding providers or Ark embedding envs.
- Removing legacy OpenAI Responses or Ark deepeval adapters.
- Changing public API schemas, domain models, storage schemas, retrieval ranking, or graph evidence storage.
- Adding a production dependency.

## Architecture

Keep the existing DeepSeek adapter shape and tighten the boundary where provider-specific rules belong.

`DeepSeekChatCompletionsClient` remains the shared low-level adapter for runtime answer, query grounding, graph evidence extraction, and any future DeepSeek chat calls. It becomes responsible for the vendor JSON Output invariants when callers use `complete_json(...)`.

`DeepSeekChatQueryGrounder` and `DeepSeekChatEvidenceExtractor` keep their domain-specific validation. They should not each duplicate generic vendor rules, but their instruction constants should still include concrete example JSON objects because the examples are semantically meaningful for each task.

`DeepSeekChatDeepEvalModel` owns deepeval schema prompting because deepeval passes an opaque prompt string and a Pydantic schema. The adapter should wrap the incoming prompt with a compact JSON instruction derived from the schema before sending the request. It should keep plain text generation unchanged.

Retry behavior belongs in `DeepSeekChatCompletionsClient`, not in each runtime adapter. That restores resilience for answer generation, query grounding, evidence extraction, and any other caller using the helper.

## Component Contracts

### DeepSeek Chat Helper

`DeepSeekChatCompletionsClient.complete(...)`:

- Sends normal Chat Completions messages.
- Sends `reasoning_effort`.
- Sends `extra_body={"thinking": {"type": "enabled"}}`.
- Does not send Responses-only fields such as `instructions`, `input`, `text`, `store`, or `reasoning={"effort": ...}`.
- Returns stripped non-empty `choices[0].message.content`.
- Retries transient failures before raising.

`DeepSeekChatCompletionsClient.complete_json(...)`:

- Sends `response_format={"type": "json_object"}`.
- Ensures at least one message contains the lowercase token `json`.
- Adds a concise JSON Output instruction when the caller instructions do not already satisfy the token requirement.
- Preserves caller-provided domain examples instead of replacing them.
- Sends a bounded `max_tokens` default.
- Raises `ProcessingError("DeepSeek returned no content.")` for empty provider content.

### Deepeval DeepSeek Adapter

Plain generation:

- Keeps the current chat completion request shape.
- Returns stripped text.

Schema generation:

- Builds a prompt that includes:
  - The original deepeval prompt.
  - A clear instruction to return only one JSON object.
  - A schema/example derived from `schema.model_json_schema()`.
  - The word `json`.
- Sends `response_format={"type": "json_object"}`.
- Sends a bounded `max_tokens` default.
- Validates the returned content with `schema.model_validate_json(...)`.
- Raises a clear `RuntimeError` when content is empty or validation fails.

`supports_structured_outputs()` may remain `True` only because the adapter does local schema validation after JSON Output. If implementation chooses not to add schema prompt wrapping, this method must return `False`.

### Retry Policy

DeepSeek Chat Completions should retry provider failures that match the old answerer behavior:

- rate limit errors,
- API connection errors,
- timeout errors,
- API status errors with status code `>= 500`.

Keep the retry count and backoff small and deterministic for unit tests. Tests should patch sleep or inject retry settings so they do not wait.

Do not retry local validation errors such as invalid JSON, missing expected fields, unknown chunk IDs, or empty user input.

## Test Contract

Tests must prove behavior at the adapter boundary, not only happy-path downstream parsing.

Required tests:

- `complete_json(...)` sends `response_format={"type": "json_object"}` and `max_tokens`.
- `complete_json(...)` injects a DeepSeek JSON instruction when caller instructions do not contain `json`.
- `complete_json(...)` does not duplicate the instruction when caller instructions already contain `json` and an example.
- Runtime JSON callers still include domain examples for query grounding and evidence extraction.
- Empty provider content raises the existing clear error.
- A transient provider error is retried and then succeeds.
- A non-retryable provider error is raised without retry.
- Deepeval schema generation sends `response_format`, includes a JSON/schema instruction, validates the Pydantic output, and supports both sync and async paths.
- Deepeval plain generation does not add `response_format`.
- Tests that previously only asserted `response_format` are strengthened or replaced.

Validation commands stay focused:

```bash
./.venv/bin/python -m pytest -q \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_deepseek_query_grounder.py \
  tests/unit/infrastructure/test_deepseek_evidence_extractor.py \
  tests/unit/test_eval_artifact_scripts.py
```

Run provider wiring tests if the repair touches config or assembly:

```bash
./.venv/bin/python -m pytest -q tests/unit/api/test_providers.py
```

Live DeepSeek and live deepeval runs remain explicit follow-up validation because they require exported secrets and can be slow.

## Acceptance Criteria

- Every review finding is mapped to a code change and at least one focused test.
- JSON Output behavior is guaranteed in the DeepSeek adapter, not left to each caller by convention.
- Deepeval schema calls have a DeepSeek-specific schema prompt and local validation.
- DeepSeek answer/query/evidence paths recover from one retryable transient failure in tests.
- Existing domain validation remains strict for query grounding and evidence extraction.
- Ark embedding remains unchanged.
- No new production dependency is added.
- The final report distinguishes fake-backed validation from any live provider validation that was not run.

## Risks

The main risk is over-normalizing malformed JSON and hiding real provider failures. Keep normalization narrow and tested, or skip it and fail clearly.

The second risk is adding a schema prompt that conflicts with deepeval's own prompt. Keep the wrapper small and append it as output-format instructions rather than rewriting the task.

The third risk is retrying errors that should fail fast. Only retry recognizable transient provider exceptions or 5xx status failures.

The fourth risk is test brittleness around Pydantic JSON schema text. Tests should assert stable substrings and request fields rather than exact full prompt bodies.

