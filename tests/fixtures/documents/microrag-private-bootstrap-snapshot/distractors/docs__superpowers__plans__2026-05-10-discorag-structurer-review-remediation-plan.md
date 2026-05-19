# DiscoRAG Structurer Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reviewed gaps in the committed DiscoRAG structurer retry / timeout / fallback slice, then simplify leftover scaffolding without changing the accepted architecture.

**Architecture:** Keep strict parsers and LLM repair. Add structured exhausted-attempt signaling so only exhausted structurer failures degrade to MiniRAG direct answer. Make structurer timeout ownership explicit by disabling low-level DeepSeek retries for structurer calls, wire retry settings through providers, harden RST validation, and finish with small behavior-preserving simplifications.

**Tech Stack:** Python 3.13, pytest, DeepSeek Chat Completions through OpenAI-compatible SDK, existing `ProcessingError`, existing `DiscoRAGQueryService`, existing RST / graph / blueprint structurer builders.

---

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-structurer-review-remediation.md](../specs/2026-05-10-discorag-structurer-review-remediation.md)

## File Structure

Files to modify:

- `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
  - Add `timeout_seconds` to `complete_json()`.
  - Add `max_retries` override to message/string completion methods.
  - Preserve existing retry defaults for non-structurer callers.
- `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
  - Add `StructurerAttemptsExhaustedError`.
  - Make `StructurerAttemptState` produce structured exhausted errors or trim it to the used shape.
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
  - Validate constructor retry settings.
  - Reject missing and duplicate chunk structures.
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
  - Disable low-level retries for structurer calls.
  - Raise structured exhausted errors.
  - Remove unused `all_items` local in the simplification task.
- `src/ragflow_lite/api/deps/providers.py`
  - Pass structurer retry config into RST, graph, and blueprint builders.
- `src/ragflow_lite/application/services/discorag_query_service.py`
  - Catch only `StructurerAttemptsExhaustedError` for MiniRAG fallback.
  - Remove regex parsing of free-form error messages.
  - Record success observability for degraded fallback.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Promote final fallback boundary after code and tests pass.
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
  - Promote final retry/timeout/exhaustion boundary after code and tests pass.

Tests to modify:

- `tests/unit/infrastructure/test_deepseek_chat.py`
- `tests/unit/infrastructure/test_structurer_retry.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`

## Task 0: Baseline And Failing-Test Confirmation

Purpose: prove the reviewed issues are real before patching.

- [ ] **Step 1: Verify current unpushed range**

Run:

```bash
rtk git status --short --branch
rtk git log --oneline --max-count=12
```

Expected:

- branch is ahead of `origin/main`;
- no unrelated working-tree edits are mixed into this remediation task.

- [ ] **Step 2: Reproduce the `complete_json(timeout_seconds=...)` signature failure**

Run:

```bash
rtk .venv/bin/python - <<'PY'
from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

class _Completions:
    def create(self, **request):
        raise AssertionError("SDK should not be reached before signature is accepted")

class _Chat:
    completions = _Completions()

class _Client:
    chat = _Chat()

client = DeepSeekChatCompletionsClient(
    api_key="k",
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
    reasoning_effort="high",
    client=_Client(),
)
try:
    client.complete_json("Return JSON.", "{}", timeout_seconds=90)
except TypeError as exc:
    print(type(exc).__name__)
    print(exc)
PY
```

Expected before Task 1: prints `TypeError` with `unexpected keyword argument 'timeout_seconds'`.

- [ ] **Step 3: Run focused baseline tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/api/test_providers.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: current tests may pass despite the signature failure. Record the result in the handoff.

## Task 1: Fix DeepSeek Timeout API And Disable Low-Level Retry For Structurers

Purpose: make one structurer attempt equal one SDK request while preserving default DeepSeek retry behavior for non-structurer calls.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add failing test for `complete_json(timeout_seconds=...)`**

Add:

```python
def test_complete_json_passes_timeout_through() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    result = client.complete_json("Return JSON.", "{}", timeout_seconds=90)

    assert result == '{"ok": true}'
    assert completions.requests[0]["timeout"] == 90
```

- [ ] **Step 2: Add failing test for disabling low-level retry**

Add:

```python
class _TimeoutLikeError(Exception):
    pass


def test_complete_json_can_disable_low_level_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        '{"ok": true}',
        failures=[_TimeoutLikeError("request timeout")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep",
        sleeps.append,
    )

    with pytest.raises(_TimeoutLikeError):
        client.complete_json(
            "Return JSON.",
            "{}",
            timeout_seconds=90,
            max_retries=0,
        )

    assert len(completions.requests) == 1
    assert sleeps == []
```

- [ ] **Step 3: Add control test that default retry still works**

Add:

```python
def test_complete_json_keeps_default_low_level_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        '{"ok": true}',
        failures=[_TimeoutLikeError("request timeout")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep",
        sleeps.append,
    )

    result = client.complete_json("Return JSON.", "{}", timeout_seconds=90)

    assert result == '{"ok": true}'
    assert len(completions.requests) == 2
    assert sleeps == [0.5]
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_passes_timeout_through \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_can_disable_low_level_retry \
  tests/unit/infrastructure/test_deepseek_chat.py::test_complete_json_keeps_default_low_level_retry -q
```

Expected before implementation: at least the first two tests fail.

- [ ] **Step 5: Implement `timeout_seconds` and `max_retries` passthrough**

Change method signatures:

```python
def complete(
    self,
    instructions: str,
    input_text: str,
    *,
    max_retries: int | None = None,
) -> str:
    ...

def complete_json(
    self,
    instructions: str,
    input_text: str,
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...

def complete_messages(
    self,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...

def complete_messages_json(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
) -> str:
    ...
```

Thread `max_retries` into `_complete_messages()`:

```python
def _complete_messages(
    self,
    messages: list[dict[str, str]],
    response_format: dict[str, str] | None,
    max_tokens: int | None,
    timeout_seconds: float | None,
    max_retries: int | None,
) -> str:
    retry_limit = _MAX_DEEPSEEK_RETRIES if max_retries is None else max_retries
    if retry_limit < 0:
        raise ProcessingError("DeepSeek max_retries must be non-negative.")

    ...

    for attempt in range(retry_limit + 1):
        ...
        if attempt >= retry_limit or not _should_retry_error(exc):
            raise
```

Ensure `complete_json()` passes both values:

```python
return self.complete_messages_json(
    [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
    ],
    max_tokens=max_tokens,
    timeout_seconds=timeout_seconds,
    max_retries=max_retries,
)
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/llms/deepseek_chat.py tests/unit/infrastructure/test_deepseek_chat.py
rtk git commit -m "fix(deepseek): bound structurer timeout attempts"
```

## Task 2: Add Structured Exhausted-Attempt Exception

Purpose: replace regex-based fallback detection with an explicit exception type.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: `tests/unit/infrastructure/test_structurer_retry.py`

- [ ] **Step 1: Add tests for structured exhausted exception**

Add:

```python
def test_structurer_attempt_state_builds_exhausted_error() -> None:
    state = StructurerAttemptState(stage="blueprint", max_attempts=2)
    state.record_failure("validation_error", "missing role")
    state.record_failure("validation_error", "still missing role")

    error = state.exhausted_error()

    assert isinstance(error, StructurerAttemptsExhaustedError)
    assert error.stage == "blueprint"
    assert error.failure_type == "validation_error"
    assert error.attempts == 2
    assert error.max_attempts == 2
    assert "still missing role" in error.message
    assert "failed after 2 attempts" in str(error)
```

Add:

```python
def test_structurer_exhausted_error_safe_metadata() -> None:
    error = StructurerAttemptsExhaustedError(
        stage="inter_chunk_graph",
        failure_type="timeout",
        attempts=2,
        max_attempts=2,
        message="timeout",
    )

    assert error.safe_metadata() == {
        "stage": "inter_chunk_graph",
        "error_type": "StructurerAttemptsExhaustedError",
        "failure_type": "timeout",
        "attempts": 2,
        "max_attempts": 2,
        "message": "timeout",
        "user_visible": True,
    }
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: FAIL because the exception and `max_attempts` state are not implemented yet.

- [ ] **Step 3: Implement structured exception and state integration**

Add:

```python
from ragflow_lite.domain.errors import ProcessingError


class StructurerAttemptsExhaustedError(ProcessingError):
    def __init__(
        self,
        *,
        stage: str,
        failure_type: str,
        attempts: int,
        max_attempts: int,
        message: str,
    ) -> None:
        self.stage = stage
        self.failure_type = failure_type
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.message = message
        super().__init__(
            f"{stage} structurer failed after {attempts} attempts: {message}"
        )

    def safe_metadata(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "error_type": type(self).__name__,
            "failure_type": self.failure_type,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "message": self.message,
            "user_visible": True,
        }
```

Update `StructurerAttemptState`:

```python
@dataclass
class StructurerAttemptState:
    stage: str
    max_attempts: int
    attempts: int = 0
    repair_count: int = 0
    timeout_count: int = 0
    last_failure_type: str | None = None
    failure_summaries: list[str] = field(default_factory=list)

    def exhausted_error(self) -> StructurerAttemptsExhaustedError:
        failure_type = self.last_failure_type or "validation_error"
        message = self.failure_summaries[-1] if self.failure_summaries else "unknown"
        return StructurerAttemptsExhaustedError(
            stage=self.stage,
            failure_type=failure_type,
            attempts=self.attempts,
            max_attempts=self.max_attempts,
            message=message,
        )
```

- [ ] **Step 4: Update older state tests**

Where tests construct `StructurerAttemptState(stage="blueprint")`, pass
`max_attempts=2`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/evidence/structurer_retry.py tests/unit/infrastructure/test_structurer_retry.py
rtk git commit -m "feat(discorag): add structured structurer exhaustion error"
```

## Task 3: Wire Structured Exhaustion And No Low-Level Retry Into Structurers

Purpose: make RST, graph, and blueprint builders use the same explicit exhaustion semantics.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- Test: `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

- [ ] **Step 1: Add tests that structurer fresh attempts disable low-level retry**

In each builder test file, assert the first fresh call records `max_retries=0`.

Example for graph:

```python
def test_graph_builder_disables_low_level_retry_for_structurer_attempts() -> None:
    client = _FakeClient(outputs=['{"relations": []}'])
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(_make_discourse_package())

    assert client.calls[0]["max_retries"] == 0
```

Use the local fixture names in each file.

- [ ] **Step 2: Add tests that exhausted builders raise `StructurerAttemptsExhaustedError`**

Example for blueprint:

```python
def test_blueprint_builder_raises_structured_exhaustion_after_validation_failures() -> None:
    client = _FakeClient(outputs=["{}", "{}"])
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=2)

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        builder.build(_make_discourse_package(), graph=_make_graph())

    assert exc_info.value.stage == "blueprint"
    assert exc_info.value.failure_type == "validation_error"
    assert exc_info.value.attempts == 2
    assert exc_info.value.max_attempts == 2
```

Add equivalent tests for:

- RST stage: `stage == "rst_extraction"`
- graph stage: `stage == "inter_chunk_graph"`

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: FAIL until builders pass `max_retries=0` and raise the structured exception.

- [ ] **Step 4: Implement state usage in RST extractor**

Import:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptState,
    build_validation_repair_messages,
    is_timeout_error,
)
```

Add constructor guards:

```python
if timeout_seconds <= 0:
    raise ValueError("timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("max_attempts must be at least 1")
```

Inside `extract()`:

```python
attempt_state = StructurerAttemptState(
    stage="rst_extraction",
    max_attempts=self.max_attempts,
)
```

For fresh and repair calls:

```python
raw_json = client.complete_json(
    instructions=instructions,
    input_text=input_text,
    timeout_seconds=self.timeout_seconds,
    max_retries=0,
)
```

```python
raw_json = client.complete_messages_json(
    repair_messages,
    timeout_seconds=self.timeout_seconds,
    max_retries=0,
)
```

On timeout:

```python
attempt_state.record_failure("timeout", str(exc) or "timeout")
if attempt_index >= self.max_attempts - 1:
    raise attempt_state.exhausted_error() from exc
repair_messages = None
continue
```

On validation error:

```python
attempt_state.record_failure("validation_error", str(exc))
if attempt_index >= self.max_attempts - 1:
    raise attempt_state.exhausted_error() from exc
```

On success:

```python
attempt_state.record_success_attempt()
```

Do not catch non-timeout call errors as exhausted. Continue wrapping them in
plain `ProcessingError("... call failed ...")`.

- [ ] **Step 5: Implement equivalent state usage in graph builder**

Use:

```python
attempt_state = StructurerAttemptState(
    stage="inter_chunk_graph",
    max_attempts=self.max_attempts,
)
```

Pass `max_retries=0` to both `complete_json()` and `complete_messages_json()`.

Raise `attempt_state.exhausted_error()` only after timeout or validation
attempt exhaustion.

- [ ] **Step 6: Implement equivalent state usage in blueprint builder**

Use:

```python
attempt_state = StructurerAttemptState(
    stage="blueprint",
    max_attempts=self.max_attempts,
)
```

Pass `max_retries=0` to both `complete_json()` and `complete_messages_json()`.

Raise `attempt_state.exhausted_error()` only after timeout or validation
attempt exhaustion.

- [ ] **Step 7: Run focused builder tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py \
  src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py \
  src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py
rtk git commit -m "fix(discorag): use structured structurer exhaustion"
```

## Task 4: Wire Structurer Retry Config Through Providers

Purpose: make settings overrides real at runtime.

**Files:**

- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`

- [ ] **Step 1: Add provider test for retry config wiring**

Extend `test_build_services_non_live_structurer_boundary`:

```python
settings.discorag_structurer_timeout_seconds = 12.5
settings.discorag_structurer_max_attempts = 3
```

Then assert:

```python
assert de.timeout_seconds == 12.5
assert de.max_attempts == 3
assert gb.timeout_seconds == 12.5
assert gb.max_attempts == 3
assert bb.timeout_seconds == 12.5
assert bb.max_attempts == 3
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py::test_build_services_non_live_structurer_boundary -q
```

Expected: FAIL because providers do not forward the values.

- [ ] **Step 3: Pass config into the three constructors**

In `build_services()`, update RST:

```python
discourse_extractor = DeepSeekChatIntraChunkDiscourseExtractor(
    api_key=structurer_runtime_config.api_key,
    base_url=structurer_runtime_config.base_url,
    model=structurer_runtime_config.model,
    reasoning_effort=structurer_runtime_config.reasoning_effort,
    timeout_seconds=structurer_runtime_config.timeout_seconds,
    max_attempts=structurer_runtime_config.max_attempts,
)
```

Update graph and blueprint builder constructors the same way.

- [ ] **Step 4: Run provider tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py -q
```

Expected: pass. If live Infinity tests are gated separately, do not claim live coverage from this command.

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_providers.py
rtk git commit -m "fix(providers): wire structurer retry settings"
```

## Task 5: Harden RST Structure Coverage

Purpose: make RST validation strict enough to trigger repair for incomplete or duplicate model output.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add missing-selected-chunk test**

Add:

```python
def test_discourse_extractor_rejects_missing_selected_chunk_structure() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            [
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                },
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                },
            ]
        ),
        max_attempts=2,
    )

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        extractor.extract(_make_evidence_package_with_two_selected_chunks())

    assert exc_info.value.stage == "rst_extraction"
    assert "missing" in exc_info.value.message.lower()
```

Use existing fixture names rather than introducing a second fixture style.

- [ ] **Step 2: Add duplicate-selected-chunk test**

Add:

```python
def test_discourse_extractor_rejects_duplicate_chunk_structure() -> None:
    payload = {
        "chunks": [
            {
                "canonical_chunk_id": "chunk_doc_alpha_0",
                "units": [{"text": "MiniRAG retrieves chunks.", "role": "claim"}],
                "relations": [],
                "main_unit_indexes": [0],
                "supporting_unit_indexes": [],
            },
            {
                "canonical_chunk_id": "chunk_doc_alpha_0",
                "units": [{"text": "Duplicate structure.", "role": "claim"}],
                "relations": [],
                "main_unit_indexes": [0],
                "supporting_unit_indexes": [],
            },
        ]
    }
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient([payload, payload]),
        max_attempts=2,
    )

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        extractor.extract(_make_evidence_package())

    assert "duplicate" in exc_info.value.message.lower()
```

- [ ] **Step 3: Add constructor guard tests**

Add:

```python
def test_discourse_extractor_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        DeepSeekChatIntraChunkDiscourseExtractor(timeout_seconds=0)


def test_discourse_extractor_rejects_zero_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        DeepSeekChatIntraChunkDiscourseExtractor(max_attempts=0)
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: new tests fail before implementation.

- [ ] **Step 5: Implement exact coverage validation**

Inside `_load_structures()`:

```python
items_by_id = {item.canonical_chunk_id: item for item in items}
expected_ids = set(items_by_id)
seen_ids: set[str] = set()
structures_by_id: dict[str, ChunkDiscourseStructure] = {}

for raw in payload["chunks"]:
    ...
    if canonical_chunk_id in seen_ids:
        raise ProcessingError(
            "Discourse extractor returned duplicate canonical_chunk_id "
            f"{canonical_chunk_id!r}."
        )
    seen_ids.add(canonical_chunk_id)
    ...

missing_ids = expected_ids - seen_ids
if missing_ids:
    raise ProcessingError(
        "Discourse extractor missing structures for selected chunks: "
        f"{sorted(missing_ids)!r}."
    )

extra_ids = seen_ids - expected_ids
if extra_ids:
    raise ProcessingError(
        "Discourse extractor returned unknown canonical_chunk_id values: "
        f"{sorted(extra_ids)!r}."
    )
```

Return in selected item order after validation.

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py tests/unit/infrastructure/test_deepseek_discourse_extractor.py
rtk git commit -m "fix(discorag): validate RST chunk coverage"
```

## Task 6: Narrow QueryService Fallback To Structured Exhaustion

Purpose: prevent runtime bugs and plain `ProcessingError`s from being hidden by MiniRAG fallback.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_local_smoke.py`

- [ ] **Step 1: Change existing plain ProcessingError test expectation**

Update `test_discorag_query_service_propagates_blueprint_processing_error` to:

```python
def test_discorag_query_service_propagates_blueprint_processing_error() -> None:
    answerer = RecordingAnswerer()
    error = ProcessingError("corrupt discourse plan")
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=FailingBlueprintBuilder(error=error),
        answerer=answerer,
    )

    with pytest.raises(ProcessingError) as exc_info:
        service.query("q", top_k=1)

    assert exc_info.value is error
    assert answerer.last_request is None
```

- [ ] **Step 2: Update exhausted fallback stubs to raise structured errors**

Change `_ExhaustedBlueprintBuilder`, `_ExhaustedDiscourseExtractor`, and
`_ExhaustedGraphBuilder` to raise:

```python
StructurerAttemptsExhaustedError(
    stage="blueprint",
    failure_type="validation_error",
    attempts=2,
    max_attempts=2,
    message="chunk_roles keys must exactly match final_answer_chunk_ids.",
)
```

Use the corresponding stage names for RST and graph.

- [ ] **Step 3: Add metadata test without regex dependency**

Add:

```python
def test_discorag_query_service_fallback_metadata_uses_structured_error() -> None:
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    result = service.query("q", top_k=1)

    error = result.metadata["discorag_error"]
    assert error["stage"] == "blueprint"
    assert error["error_type"] == "StructurerAttemptsExhaustedError"
    assert error["failure_type"] == "validation_error"
    assert error["attempts"] == 2
    assert error["max_attempts"] == 2
    assert error["user_visible"] is True
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: FAIL until QueryService catches the structured exception only.

- [ ] **Step 5: Implement structured catch**

Import:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptsExhaustedError,
)
```

Change catches from:

```python
except ProcessingError as exc:
```

to:

```python
except StructurerAttemptsExhaustedError as exc:
```

Delete `_parse_structurer_failure()` and remove the `re` import.

Change fallback metadata construction:

```python
def _discorag_fallback_metadata(
    *, exc: StructurerAttemptsExhaustedError, source_selection: object
) -> dict[str, object]:
    return {
        "mode": "discorag",
        "answer_mode": "minirag_fallback",
        "discorag_degraded": True,
        "source_selection": source_selection,
        "discorag_error": exc.safe_metadata(),
    }
```

Change `_answer_with_minirag_fallback()` to take only `exc`, not a separate
`stage`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: pass after smoke stubs are updated to structured exhausted errors.

- [ ] **Step 7: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/application/services/discorag_query_service.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py
rtk git commit -m "fix(discorag): fallback only on exhausted structurer attempts"
```

## Task 7: Record Degraded Fallback As Successful Outcome

Purpose: make observability match user-facing behavior.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`

- [ ] **Step 1: Add failing metric/log test for fallback success**

Add:

```python
def test_discorag_query_service_records_success_for_minirag_fallback(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []
    monkeypatch.setattr(discorag_module, "record_query_outcome", outcomes.append)
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=_ExhaustedBlueprintBuilder(),
        answerer=RecordingAnswerer(),
    )

    with caplog.at_level(logging.INFO, logger=QUERY_LOGGER):
        result = service.query("q", top_k=1)

    assert result.metadata["discorag_degraded"] is True
    assert "query_succeeded" in _event_names(caplog)
    assert outcomes == ["succeeded"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_records_success_for_minirag_fallback -q
```

Expected: FAIL because fallback returns before success accounting.

- [ ] **Step 3: Factor success recording**

Add helper:

```python
def _record_success(self, query: str, top_k: int, result: AnswerResult) -> None:
    log_query_event(
        logger,
        logging.INFO,
        "query_succeeded",
        query,
        top_k,
        outcome="succeeded",
        context_count=len(result.contexts),
        degraded=result.metadata.get("discorag_degraded") is True,
    )
    record_query_outcome("succeeded")
```

Use it in normal path:

```python
self._record_success(query, top_k, result)
return result
```

Pass `top_k` into `_answer_with_minirag_fallback()` and call the helper before
returning:

```python
result.metadata.update(metadata)
self._record_success(query, top_k, result)
return result
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
rtk git add src/ragflow_lite/application/services/discorag_query_service.py tests/unit/application/test_discorag_query_service.py
rtk git commit -m "fix(discorag): record degraded fallback success"
```

## Task 8: Simplify After Correctness Fixes

Purpose: remove leftover scaffolding and unused code once behavior is correct.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: focused tests from prior tasks

- [ ] **Step 1: Remove unused blueprint local**

Delete:

```python
all_items = _dedupe_items(answer_items + supplemental_items)
```

If `_dedupe_items()` has no remaining references, delete `_dedupe_items()` too.

Verify:

```bash
rtk rg -n "_dedupe_items|all_items" src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py
```

Expected: no unused `all_items`; `_dedupe_items` remains only if still used.

- [ ] **Step 2: Simplify `StructurerAttemptState` only after it is runtime-used**

Inspect:

```bash
rtk rg -n "StructurerAttemptState|safe_metadata|failure_summaries" src/ragflow_lite tests
```

If `safe_metadata()` is no longer used after structured errors are introduced,
delete it and its tests. Keep only fields used by the builders and
`exhausted_error()`.

Do not remove `StructurerAttemptsExhaustedError`.

- [ ] **Step 3: Run simplification-focused tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/application/test_discorag_query_service.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add \
  src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py \
  src/ragflow_lite/infrastructure/evidence/structurer_retry.py \
  tests/unit/infrastructure/test_structurer_retry.py
rtk git commit -m "refactor(discorag): simplify structurer retry scaffolding"
```

## Task 9: Contract Promotion

Purpose: update active contracts after behavior is proven.

**Files:**

- Modify: `src/ragflow_lite/application/CONTRACTS.md`
- Modify: `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`

- [ ] **Step 1: Update infrastructure evidence contract**

Ensure the contract says:

- RST, graph, and blueprint are structurer stages.
- Validation repair is LLM-based, not deterministic.
- Timeout retry is structurer-owned.
- Structurer calls disable low-level DeepSeek retry.
- Exhausted attempts raise `StructurerAttemptsExhaustedError`.
- Plain parser `ProcessingError` inside an attempt triggers repair when attempts remain.

- [ ] **Step 2: Update application contract**

Ensure the contract says:

- `DiscoRAGQueryService` catches only `StructurerAttemptsExhaustedError` for
  MiniRAG fallback.
- Fallback contexts are exactly `retrieval_result.chunks`.
- Supplemental discourse chunks do not append to fallback contexts.
- Runtime invariant `ProcessingError`s remain hard failures.
- Fallback metadata is user-visible.

- [ ] **Step 3: Run contract residue scan**

Run:

```bash
rtk rg -n "regex|failed after \\(\\d\\+\\)|all ProcessingError|any ProcessingError|deterministic fallback|append supplemental" \
  src/ragflow_lite/application/CONTRACTS.md \
  src/ragflow_lite/infrastructure/evidence/CONTRACTS.md \
  docs/superpowers/specs/2026-05-10-discorag-structurer-review-remediation.md \
  docs/superpowers/plans/2026-05-10-discorag-structurer-review-remediation-plan.md
```

Expected: no stale wording that says fallback catches all `ProcessingError`s or
that supplemental chunks append to answer contexts.

- [ ] **Step 4: Commit**

Run:

```bash
rtk git add src/ragflow_lite/application/CONTRACTS.md src/ragflow_lite/infrastructure/evidence/CONTRACTS.md
rtk git commit -m "docs(contracts): promote structurer exhaustion boundary"
```

## Task 10: Final Verification Gate

Purpose: prove the remediation is ready to push.

- [ ] **Step 1: Run focused remediation gate**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/api/test_providers.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: pass.

- [ ] **Step 2: Run live Infinity provider gate**

Run only if local Infinity is running:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: pass. If Infinity is unavailable, report this as unverified instead
of claiming live provider coverage.

- [ ] **Step 3: Run full unit suite**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit -q
```

Expected: pass.

- [ ] **Step 4: Run diff hygiene checks**

Run:

```bash
rtk git diff --check
rtk git diff --cached --check
```

Expected: both pass.

- [ ] **Step 5: Review final commit range**

Run:

```bash
rtk git log --oneline --max-count=20
rtk git status --short --branch
```

Expected:

- remediation commits sit on top of the current unpushed DiscoRAG commits;
- no accidental unstaged runtime edits remain unless intentionally left for the
  user.

## Implementation Notes

- Prefer `StructurerAttemptsExhaustedError` over string predicates. A string
  predicate is acceptable only as an emergency stopgap and should not survive
  the final plan.
- Do not catch `ProcessingError` broadly in `DiscoRAGQueryService` for fallback.
- Do not re-enable deterministic graph or blueprint fallback.
- Do not change the answerer fallback behavior in this slice except as required
  by tests that observe MiniRAG fallback metadata.
- Keep commits task-sized so review can bisect easily.

