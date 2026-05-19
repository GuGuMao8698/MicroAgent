# DiscoRAG Structurer Retry, Timeout, And Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded timeout retry, validation-error repair, and explicit MiniRAG direct-answer fallback for exhausted DiscoRAG structurer attempts without restoring deterministic runtime fallback.

**Architecture:** Keep strict parsers as the source of truth. Add message-based DeepSeek JSON calls, then let each structurer builder retry validation failures by appending a short repair turn to the existing conversation. Timeout retries start a fresh original attempt and stale attempts must not be consumed. If a structurer stage exhausts attempts, `DiscoRAGQueryService` explicitly degrades to MiniRAG-selected top_n chunks and returns user-visible error metadata.

**Tech Stack:** Python 3.13, pytest, DeepSeek Chat Completions via OpenAI-compatible SDK, existing `ProcessingError`, existing DiscoRAG graph/blueprint/RST builders.

---

Date: 2026-05-10
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-10-discorag-structurer-retry-timeout-repair.md](../specs/2026-05-10-discorag-structurer-retry-timeout-repair.md)

## File Structure

Files to modify:

- `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
  - Add message-based completion methods and request timeout support.
  - Keep existing `complete()` / `complete_json()` behavior as wrappers.
- `src/ragflow_lite/config/settings.py`
  - Add explicit structurer retry and timeout settings.
- `src/ragflow_lite/config/__init__.py`
  - Export new config fields if the project exports settings types there.
- `src/ragflow_lite/api/deps/providers.py`
  - Pass structurer retry/timeout config into RST, graph, and blueprint builders.
- `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
  - Create a small shared helper for attempt metadata and repair message assembly.
  - Keep it provider-neutral and schema-neutral.
- `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
  - Add bounded validation repair and timeout retry around RST extraction.
- `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
  - Add bounded validation repair and timeout retry around graph construction.
- `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
  - Add bounded validation repair and timeout retry around blueprint planning.
- `src/ragflow_lite/application/services/discorag_query_service.py`
  - Catch exhausted structurer failures and answer with MiniRAG-selected final
    contexts plus explicit degraded-fallback metadata.
- `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
  - Update after behavior and tests land.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Document the explicit MiniRAG direct-answer fallback boundary.

Tests to modify or create:

- `tests/unit/infrastructure/test_deepseek_chat.py`
- `tests/unit/infrastructure/test_structurer_retry.py`
- `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`
- `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
- `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/application/test_discorag_local_smoke.py`
- `tests/unit/api/test_providers.py`

## Task 0: Baseline Reconnaissance

Purpose: confirm the current code shape before adding retry behavior.

- [ ] **Step 1: Inspect current DeepSeek client symbols**

Run:

```bash
cx overview src/ragflow_lite/infrastructure/llms/deepseek_chat.py
cx definition --name DeepSeekChatCompletionsClient --from src/ragflow_lite/infrastructure/llms/deepseek_chat.py
```

Expected:

- `complete()` and `complete_json()` exist.
- They delegate to a synchronous `_complete()` call.
- `_complete()` builds a two-message request.

- [ ] **Step 2: Inspect current structurer builders**

Run:

```bash
cx definition --name DeepSeekChatIntraChunkDiscourseExtractor --from src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py
cx definition --name LLMInterChunkDiscourseGraphBuilder --from src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py
cx definition --name LLMDiscoRAGAnswerBlueprintBuilder --from src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py
```

Expected:

- Each builder has one LLM call and one parse/validation pass.
- No validation repair loop exists yet.

- [ ] **Step 3: Run current focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: existing tests pass before changes.

## Task 1: Add Message-Based DeepSeek JSON Calls

Purpose: let structurer builders express multi-turn validation repair while
preserving the current two-string convenience API.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add failing tests for message-based JSON calls**

Add tests like:

```python
def test_deepseek_complete_messages_json_sends_messages_and_json_mode() -> None:
    client = _FakeOpenAIClient(content='{"ok": true}')
    llm = DeepSeekChatCompletionsClient(
        api_key="key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    result = llm.complete_messages_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Build graph."},
            {"role": "assistant", "content": '{"relations": []}'},
            {
                "role": "user",
                "content": "Previous JSON was invalid. Regenerate complete JSON.",
            },
        ],
        timeout_seconds=90,
    )

    assert result == '{"ok": true}'
    request = client.chat.completions.calls[0]
    assert request["messages"][2]["role"] == "assistant"
    assert request["response_format"] == {"type": "json_object"}
    assert request["timeout"] == 90
```

If the fake client currently stores calls in a different attribute, adapt only
the assertion plumbing, not the behavior under test.

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py::test_deepseek_complete_messages_json_sends_messages_and_json_mode -q
```

Expected: FAIL because `complete_messages_json()` does not exist.

- [ ] **Step 3: Implement message-based methods**

In `DeepSeekChatCompletionsClient`, add:

```python
def complete_messages(
    self,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float | None = None,
) -> str:
    return self._complete_messages(
        messages,
        response_format=None,
        max_tokens=None,
        timeout_seconds=timeout_seconds,
    )

def complete_messages_json(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
    timeout_seconds: float | None = None,
) -> str:
    return self._complete_messages(
        _ensure_messages_json_instruction(messages),
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
```

Add helper:

```python
def _ensure_messages_json_instruction(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    result = [dict(message) for message in messages]
    for message in result:
        if message.get("role") == "system":
            message["content"] = _ensure_json_instruction(message.get("content", ""))
            return result
    return [{"role": "system", "content": _DEEPSEEK_JSON_INSTRUCTION}, *result]
```

Make existing `complete()` and `complete_json()` delegate through the new
message methods:

```python
def complete(self, instructions: str, input_text: str) -> str:
    return self.complete_messages(
        [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ]
    )

def complete_json(...):
    return self.complete_messages_json(
        [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ],
        max_tokens=max_tokens,
    )
```

Implement `_complete_messages()` by moving the current request construction out
of `_complete()`:

```python
def _complete_messages(
    self,
    messages: list[dict[str, str]],
    response_format: dict[str, str] | None,
    max_tokens: int | None,
    timeout_seconds: float | None,
) -> str:
    request: dict[str, Any] = {
        "model": self.model,
        "messages": _validate_messages(messages),
        "reasoning_effort": self.reasoning_effort,
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    if response_format is not None:
        request["response_format"] = response_format
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    if timeout_seconds is not None:
        request["timeout"] = timeout_seconds
    ...
```

Add `_validate_messages()`:

```python
def _validate_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not messages:
        raise ProcessingError("DeepSeek messages must not be empty.")
    validated: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ProcessingError(f"Invalid DeepSeek message role: {role!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ProcessingError("DeepSeek message content must be non-empty text.")
        validated.append({"role": role, "content": content})
    return validated
```

- [ ] **Step 4: Run DeepSeek client tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_chat.py -q
```

Expected: all tests pass.

## Task 2: Add Structurer Retry Configuration

Purpose: expose timeout and attempt count explicitly on the structurer config
surface.

**Files:**

- Modify: `src/ragflow_lite/config/settings.py`
- Modify: `src/ragflow_lite/config/__init__.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`

- [ ] **Step 1: Add failing settings/provider tests**

Add tests asserting:

```python
def test_discorag_structurer_retry_defaults_are_bounded() -> None:
    settings = Settings()
    assert settings.discorag_structurer_timeout_seconds == 90
    assert settings.discorag_structurer_max_attempts == 2
```

Add provider wiring assertions where existing provider tests inspect graph and
blueprint builders:

```python
assert services.discorag_query_service.inter_chunk_graph_builder.timeout_seconds == 90
assert services.discorag_query_service.inter_chunk_graph_builder.max_attempts == 2
assert services.discorag_query_service.blueprint_builder.timeout_seconds == 90
assert services.discorag_query_service.blueprint_builder.max_attempts == 2
```

If `DiscoRAGQueryService` stores collaborators under different names, use those
existing attributes rather than adding new public accessors just for tests.

- [ ] **Step 2: Run provider tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py -q
```

Expected: FAIL because retry settings or builder attributes do not exist.

- [ ] **Step 3: Add settings fields**

In `Settings`, add:

```python
discorag_structurer_timeout_seconds: float = 90.0
discorag_structurer_max_attempts: int = 2
```

If the project has a `DiscoRAGStructurerRuntimeConfig`, add matching fields:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Keep validation simple:

```python
if timeout_seconds <= 0:
    raise ValueError("discorag_structurer_timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("discorag_structurer_max_attempts must be at least 1")
```

- [ ] **Step 4: Pass config into builders**

Update provider construction so all three structurer components receive:

```python
timeout_seconds=structurer_config.timeout_seconds
max_attempts=structurer_config.max_attempts
```

Do not pass answer-model config into the structurer retry fields.

- [ ] **Step 5: Run provider tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: provider tests pass against live Infinity.

## Task 3: Add Shared Structurer Retry Helpers

Purpose: keep repair message construction and attempt metadata consistent
without hiding schema-specific validation in a generic helper.

**Files:**

- Create: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Test: `tests/unit/infrastructure/test_structurer_retry.py`

- [ ] **Step 1: Write failing helper tests**

Create tests:

```python
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptState,
    build_validation_repair_messages,
)


def test_build_validation_repair_messages_appends_short_feedback_only() -> None:
    messages = build_validation_repair_messages(
        instructions="Return graph JSON.",
        input_text="query: q\n\nCHUNK[1] id=chunk_a\ntext: Alpha",
        invalid_output='{"relations": [{"target_chunk_id": "missing"}]}',
        validation_error='target_chunk_id "missing" is unknown',
    )

    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1]["content"].startswith("query: q")
    assert messages[2]["content"].startswith('{"relations"')
    assert "target_chunk_id" in messages[3]["content"]
    assert "query: q" not in messages[3]["content"]
    assert "Regenerate one complete JSON object" in messages[3]["content"]
    assert "Do not output a patch" in messages[3]["content"]
```

Add attempt state test:

```python
def test_structurer_attempt_state_records_failures() -> None:
    state = StructurerAttemptState(stage="blueprint")
    state.record_failure("validation_error", "missing chunk role")
    assert state.attempts == 1
    assert state.repair_count == 1
    assert state.last_failure_type == "validation_error"
    assert state.safe_metadata()["structurer_repair_count"] == 1
```

- [ ] **Step 2: Run helper tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement helper module**

Create `structurer_retry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StructurerAttemptState:
    stage: str
    attempts: int = 0
    repair_count: int = 0
    timeout_count: int = 0
    last_failure_type: str | None = None
    failure_summaries: list[str] = field(default_factory=list)

    def record_failure(self, failure_type: str, message: str) -> None:
        self.attempts += 1
        self.last_failure_type = failure_type
        self.failure_summaries.append(f"{failure_type}: {message}")
        if failure_type == "validation_error":
            self.repair_count += 1
        elif failure_type == "timeout":
            self.timeout_count += 1

    def record_success_attempt(self) -> None:
        self.attempts += 1

    def safe_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "structurer_attempts": self.attempts,
            "structurer_repair_count": self.repair_count,
            "structurer_timeout_count": self.timeout_count,
        }
        if self.last_failure_type is not None:
            metadata["structurer_last_failure_type"] = self.last_failure_type
        return metadata
```

Add repair builder:

```python
def build_validation_repair_messages(
    *,
    instructions: str,
    input_text: str,
    invalid_output: str,
    validation_error: str,
) -> list[dict[str, str]]:
    feedback = (
        "Your previous JSON is invalid.\n\n"
        f"Validation error:\n- {validation_error}\n\n"
        "Regenerate one complete JSON object. Do not output a patch. "
        "Do not include markdown or prose outside the JSON object."
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
        {"role": "assistant", "content": invalid_output},
        {"role": "user", "content": feedback},
    ]
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_structurer_retry.py -q
```

Expected: PASS.

## Task 4: Add Validation Repair To Blueprint Builder

Purpose: repair the highest-impact structurer stage first.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_discorag_blueprint_builder.py`
- Test: `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`

- [ ] **Step 1: Add failing validation-repair test**

Add a fake client that returns invalid then valid JSON. Example shape:

```python
def test_blueprint_builder_repairs_validation_error_with_multiturn_messages() -> None:
    client = _FakeStructurerClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead", "chunk_b": "support"},
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    blueprint = builder.build(_package_with_two_answer_chunks(), graph=_graph())

    assert blueprint.ordered_chunk_ids == ["chunk_a", "chunk_b"]
    assert len(client.calls) == 2
    repair_call = client.calls[1]
    assert repair_call["messages"][2]["role"] == "assistant"
    assert "chunk_roles" in repair_call["messages"][3]["content"]
    assert "query:" not in repair_call["messages"][3]["content"]
    assert "Do not output a patch" in repair_call["messages"][3]["content"]
```

- [ ] **Step 2: Run the new test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py::test_blueprint_builder_repairs_validation_error_with_multiturn_messages -q
```

Expected: FAIL because the builder does not retry.

- [ ] **Step 3: Add builder constructor fields**

Extend `LLMDiscoRAGAnswerBlueprintBuilder.__init__`:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Validate:

```python
if timeout_seconds <= 0:
    raise ValueError("timeout_seconds must be positive")
if max_attempts < 1:
    raise ValueError("max_attempts must be at least 1")
```

- [ ] **Step 4: Implement blueprint attempt loop**

Refactor `build()` so it constructs the original `input_text` once and calls a
private helper:

```python
raw_json = self._complete_and_repair_json(
    client=client,
    instructions=_BLUEPRINT_INSTRUCTIONS,
    input_text=input_text,
    parse=lambda candidate: parse_llm_discorag_blueprint(
        candidate,
        answer_chunk_ids=answer_chunk_ids,
        supplemental_chunk_ids=supplemental_chunk_ids,
        known_relation_ids=known_relation_ids,
        known_rst_unit_ids=known_rst_unit_ids,
        top_k=top_k,
        llm_metadata=self._provenance_metadata(),
    ),
)
```

The helper should:

```python
messages = [
    {"role": "system", "content": instructions},
    {"role": "user", "content": input_text},
]
last_error: ProcessingError | None = None
for attempt_index in range(self.max_attempts):
    raw_json = (
        client.complete_json(..., timeout_seconds=self.timeout_seconds)
        if attempt_index == 0
        else client.complete_messages_json(messages, timeout_seconds=self.timeout_seconds)
    )
    try:
        return parse(raw_json)
    except ProcessingError as exc:
        last_error = exc
        if attempt_index >= self.max_attempts - 1:
            break
        messages = build_validation_repair_messages(
            instructions=instructions,
            input_text=input_text,
            invalid_output=raw_json,
            validation_error=str(exc),
        )
raise ProcessingError(f"LLM DiscoRAG blueprint builder failed after ...") from last_error
```

Keep the repair turn short; do not append full original input to the repair user
turn.

- [ ] **Step 5: Add exhausted attempts test**

Add:

```python
def test_blueprint_builder_raises_after_repair_attempts_exhausted() -> None:
    client = _FakeStructurerClient(
        responses=[
            '{"final_answer_chunk_ids": ["chunk_a"], "chunk_roles": {}, "promotions": []}',
            '{"final_answer_chunk_ids": ["chunk_a"], "chunk_roles": {}, "promotions": []}',
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=2)

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(_package_with_two_answer_chunks(), graph=_graph())
```

- [ ] **Step 6: Run blueprint builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py -q
```

Expected: PASS.

## Task 5: Add Validation Repair To Inter-Chunk Graph Builder

Purpose: repair graph schema failures without deterministic graph fallback.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/llm_inter_chunk_graph_builder.py`
- Test: `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`

- [ ] **Step 1: Add failing graph repair test**

Add:

```python
def test_graph_builder_repairs_unknown_target_with_multiturn_messages() -> None:
    client = _FakeStructurerClient(
        responses=[
            json.dumps(
                {
                    "relations": [
                        {
                            "source_chunk_id": "chunk_a",
                            "target_chunk_id": "missing",
                            "relation_type": "supports",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "relations": [
                        {
                            "source_chunk_id": "chunk_a",
                            "target_chunk_id": "chunk_b",
                            "relation_type": "supports",
                            "confidence": 0.8,
                        }
                    ]
                }
            ),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    graph = builder.build(_package_with_two_discourse_chunks())

    assert [rel.target_chunk_id for rel in graph.relations] == ["chunk_b"]
    assert len(client.calls) == 2
    assert "missing" in client.calls[1]["messages"][3]["content"]
    assert "query:" not in client.calls[1]["messages"][3]["content"]
```

- [ ] **Step 2: Run graph test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py::test_graph_builder_repairs_unknown_target_with_multiturn_messages -q
```

Expected: FAIL before implementation.

- [ ] **Step 3: Add constructor fields and attempt loop**

Mirror the blueprint builder fields:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Use the same repair helper:

```python
messages = build_validation_repair_messages(
    instructions=_INTER_CHUNK_INSTRUCTIONS,
    input_text=input_text,
    invalid_output=raw_json,
    validation_error=str(exc),
)
```

On success, parse with:

```python
parse_llm_inter_chunk_graph(
    raw_json,
    chunk_ids=chunk_ids,
    query=package.query,
    llm_metadata=self._provenance_metadata(),
)
```

- [ ] **Step 4: Add exhausted attempts test**

Add a test where both attempts contain an unknown target and assert:

```python
with pytest.raises(ProcessingError, match="failed after 2 attempts"):
    builder.build(package)
```

- [ ] **Step 5: Run graph builder tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py -q
```

Expected: PASS.

## Task 6: Add Validation Repair To RST Extractor

Purpose: repair malformed intra-chunk RST output without partial success.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/deepseek_discourse_extractor.py`
- Test: `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add failing RST repair test**

Add:

```python
def test_deepseek_discourse_extractor_repairs_unknown_chunk_id() -> None:
    client = _FakeDeepSeekClient(
        responses=[
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "missing",
                            "units": [{"text": "Bad.", "role": "main"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [{"text": "Good.", "role": "main"}],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            ),
        ]
    )
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    package = extractor.extract(_package())

    assert package.structures[0].canonical_chunk_id == "chunk_doc_alpha_0"
    assert len(client.calls) == 2
    assert "unknown canonical_chunk_id" in client.calls[1]["messages"][3]["content"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" not in client.calls[1]["messages"][3]["content"]
```

If the existing fake client accepts a single response string, update it to
accept a response list and record calls.

- [ ] **Step 2: Run RST repair test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py::test_deepseek_discourse_extractor_repairs_unknown_chunk_id -q
```

Expected: FAIL before implementation.

- [ ] **Step 3: Add extractor constructor fields**

Add:

```python
timeout_seconds: float = 90.0
max_attempts: int = 2
```

Keep `enabled=False` behavior unchanged: disabled extractor should return empty
structures without calling the client.

- [ ] **Step 4: Implement RST attempt loop**

The extractor should build the original input once, then:

```python
for attempt_index in range(self.max_attempts):
    raw_json = (
        client.complete_json(
            instructions=DISCOURSE_INSTRUCTIONS,
            input_text=input_text,
            timeout_seconds=self.timeout_seconds,
        )
        if attempt_index == 0
        else client.complete_messages_json(
            messages,
            timeout_seconds=self.timeout_seconds,
        )
    )
    try:
        payload = _load_payload(raw_json)
        return self._load_structures(payload, selected_items)
    except ProcessingError as exc:
        if attempt_index >= self.max_attempts - 1:
            raise ProcessingError("DeepSeek discourse extractor failed after ...") from exc
        messages = build_validation_repair_messages(
            instructions=DISCOURSE_INSTRUCTIONS,
            input_text=input_text,
            invalid_output=raw_json,
            validation_error=str(exc),
        )
```

Do not restore silent dropping of unknown chunk ids.

- [ ] **Step 5: Run RST extractor tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: PASS.

## Task 7: Add Timeout Retry Coverage

Purpose: prove timeout retries are fresh attempts and validation repair remains
separate from timeout behavior.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/structurer_retry.py`
- Modify: the three builder/extractor files if needed
- Test:
  - `tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py`
  - `tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py`
  - `tests/unit/infrastructure/test_deepseek_discourse_extractor.py`

- [ ] **Step 1: Add fake timeout exception**

In each relevant test file or shared test helper, define:

```python
class FakeTimeoutError(TimeoutError):
    pass
```

The fake client should raise it on the first call and return valid JSON on the
second call.

- [ ] **Step 2: Add blueprint timeout retry test**

```python
def test_blueprint_builder_retries_timeout_with_fresh_original_request() -> None:
    client = _FakeStructurerClient(
        responses=[
            FakeTimeoutError("request timed out"),
            _valid_blueprint_json(),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    blueprint = builder.build(_package_with_two_answer_chunks(), graph=_graph())

    assert blueprint.ordered_chunk_ids
    assert len(client.calls) == 2
    assert "messages" not in client.calls[1] or len(client.calls[1]["messages"]) == 2
```

The second attempt should be a fresh original request, not a validation repair
conversation containing an assistant invalid output.

- [ ] **Step 3: Add graph and RST timeout retry tests**

Use the same pattern:

```python
responses=[FakeTimeoutError("request timed out"), valid_json]
```

Assert the second call is not a repair conversation.

- [ ] **Step 4: Implement timeout handling if needed**

In each builder/extractor attempt loop:

```python
except Exception as exc:
    if _is_timeout_error(exc):
        if attempt_index >= self.max_attempts - 1:
            raise ProcessingError("... timed out after ...") from exc
        messages = original_messages
        continue
    raise ProcessingError("... call failed: ...") from exc
```

Add a local helper in `structurer_retry.py`:

```python
def is_timeout_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "timedout" in name
```

If the DeepSeek client already retries timeout-like exceptions internally, keep
the builder-level timeout retry focused on timeout exceptions that escape the
client.

- [ ] **Step 5: Run timeout-focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py -q
```

Expected: PASS.

## Task 8: Add Explicit MiniRAG Fallback For Exhausted Structurer Attempts

Purpose: when DiscoRAG structuring still fails after bounded retry, answer with
MiniRAG-selected `top_n` chunks and make the degraded state obvious to callers.

**Files:**

- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`

- [ ] **Step 1: Add failing query-service fallback test for blueprint exhaustion**

Add a test that makes `blueprint_builder.build()` raise `ProcessingError` after
its own retry loop has already exhausted attempts:

```python
class ExhaustedBlueprintBuilder:
    def build(self, package: IntraChunkDiscoursePackage, *, graph: InterChunkDiscourseGraph | None = None) -> AnswerBlueprint:
        raise ProcessingError(
            "LLM DiscoRAG blueprint builder failed after 2 attempts: "
            "chunk_roles keys must exactly match final_answer_chunk_ids."
        )


def test_discorag_query_service_falls_back_to_minirag_contexts_when_blueprint_exhausts() -> None:
    answer_chunks = [_chunk("chunk_a"), _chunk("chunk_b")]
    supplemental_chunk = _chunk("chunk_supplemental")
    supplemental_chunk.metadata["selected_for_answer"] = False
    supplemental_chunk.metadata["selected_for_discourse"] = True
    retrieval_result = _retrieval_result(chunks=answer_chunks)
    retrieval_result.metadata["supplemental_discourse_chunks"] = {
        "chunk_supplemental": supplemental_chunk
    }
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=retrieval_result),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=ExhaustedBlueprintBuilder(),
        answerer=answerer,
    )

    result = service.query("How does MiniRAG organize evidence?", top_k=2)

    assert answerer.last_request is not None
    assert answerer.last_request.mode == "standard"
    assert answerer.last_request.blueprint is None
    assert [chunk.chunk_id for chunk in answerer.last_request.contexts] == [
        "chunk_a",
        "chunk_b",
    ]
    assert "chunk_supplemental" not in [
        chunk.chunk_id for chunk in answerer.last_request.contexts
    ]
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    error = result.metadata["discorag_error"]
    assert error["stage"] == "blueprint"
    assert error["attempts"] == 2
    assert error["max_attempts"] == 2
    assert error["user_visible"] is True
    assert "chunk_roles" in error["message"]
```

If the existing test fakes use different names, keep the same assertions and
adapt only the fixture wiring.

- [ ] **Step 2: Add failing tests for RST and graph exhaustion stages**

Add two smaller tests:

```python
class ExhaustedDiscourseExtractor:
    def extract(self, package: EvidencePackage) -> IntraChunkDiscoursePackage:
        raise ProcessingError(
            "DeepSeek discourse extractor failed after 2 attempts: "
            "unknown canonical_chunk_id 'missing'."
        )


def test_discorag_query_service_fallback_metadata_identifies_rst_stage() -> None:
    ...
    result = service.query("q", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["discorag_error"]["stage"] == "rst_extraction"
    assert "canonical_chunk_id" in result.metadata["discorag_error"]["message"]
```

```python
class ExhaustedGraphBuilder:
    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        raise ProcessingError(
            "LLM inter-chunk graph builder failed after 2 attempts: "
            "target_chunk_id 'missing' is unknown."
        )


def test_discorag_query_service_fallback_metadata_identifies_graph_stage() -> None:
    ...
    result = service.query("q", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["discorag_error"]["stage"] == "inter_chunk_graph"
    assert "target_chunk_id" in result.metadata["discorag_error"]["message"]
```

- [ ] **Step 3: Run the new fallback tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_falls_back_to_minirag_contexts_when_blueprint_exhausts \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_fallback_metadata_identifies_rst_stage \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_fallback_metadata_identifies_graph_stage -q
```

Expected: FAIL because the service currently raises `ProcessingError`.

- [ ] **Step 4: Add stage-specific exhausted failure handling**

In `DiscoRAGQueryService.query()`, keep retrieval first. Then catch
`ProcessingError` around each structurer stage separately so the service knows
which business step failed:

```python
try:
    discourse_package = self.discourse_extractor.extract(evidence_package)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="rst_extraction",
        exc=exc,
        top_k=top_k,
    )

try:
    inter_chunk_graph = self.inter_chunk_graph_builder.build(discourse_package)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="inter_chunk_graph",
        exc=exc,
        top_k=top_k,
    )

try:
    blueprint = self.blueprint_builder.build(discourse_package, graph=inter_chunk_graph)
except ProcessingError as exc:
    return self._answer_with_minirag_fallback(
        query=query,
        retrieval_result=retrieval_result,
        stage="blueprint",
        exc=exc,
        top_k=top_k,
    )
```

Do not catch `ProcessingError` from `_contexts_with_bounded_promotion()` or
`_blueprint_for_contexts()` in this fallback block. Those failures occur after a
supposedly valid blueprint and should stay hard failures unless explicitly
classified later.

- [ ] **Step 5: Implement fallback answer helper**

Add a private helper:

```python
def _answer_with_minirag_fallback(
    self,
    *,
    query: str,
    retrieval_result: TopologyRetrievalResult,
    stage: str,
    exc: ProcessingError,
    top_k: int,
) -> AnswerResult:
    metadata = _discorag_fallback_metadata(
        stage=stage,
        exc=exc,
        source_selection=retrieval_result.metadata.get("source_selection"),
    )
    result = self.answerer.answer(
        AnswerRequest(
            query=query,
            contexts=retrieval_result.chunks,
            mode="standard",
            blueprint=None,
            metadata=metadata,
        )
    )
    result.metadata.update(metadata)
    log_query_event(
        logger,
        logging.ERROR,
        "query_degraded_to_minirag",
        query,
        top_k,
        outcome="degraded",
        error_type=type(exc).__name__,
    )
    record_query_outcome("degraded")
    return result
```

Use `retrieval_result.chunks` exactly. Do not append
`supplemental_discourse_chunks`.

- [ ] **Step 6: Implement explicit fallback metadata helper**

Add:

```python
def _discorag_fallback_metadata(
    *,
    stage: str,
    exc: ProcessingError,
    source_selection: object,
) -> dict[str, object]:
    attempts, max_attempts, failure_type = _parse_structurer_failure(str(exc))
    return {
        "mode": "discorag",
        "answer_mode": "minirag_fallback",
        "discorag_degraded": True,
        "source_selection": source_selection,
        "discorag_error": {
            "stage": stage,
            "error_type": type(exc).__name__,
            "failure_type": failure_type,
            "attempts": attempts,
            "max_attempts": max_attempts,
            "message": str(exc),
            "user_visible": True,
        },
    }
```

Add a conservative parser:

```python
def _parse_structurer_failure(message: str) -> tuple[int | None, int | None, str]:
    match = re.search(r"failed after (\\d+) attempts", message)
    attempts = int(match.group(1)) if match else None
    failure_type = "timeout" if "timeout" in message.lower() else "validation_error"
    return attempts, attempts, failure_type
```

If later builder exceptions expose structured metadata instead of message text,
replace this parser with structured fields. Do not block this task on a new
exception hierarchy.

- [ ] **Step 7: Run query-service tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py -q
```

Expected: PASS.

## Task 9: Full-Chain Smoke For Repaired Blueprint And Explicit Fallback

Purpose: prove DiscoRAG can recover from one blueprint validation failure
without runtime deterministic repair, and can visibly degrade to MiniRAG direct
answer when structurer attempts are exhausted.

**Files:**

- Modify: `tests/unit/application/test_discorag_local_smoke.py`

- [ ] **Step 1: Add smoke fake that fails blueprint once**

Extend the smoke blueprint fake so the first output misses a role or ordering id,
and the second output is valid.

Example expected behavior:

```python
assert fake_blueprint_client.call_count == 2
assert answerer.last_request.blueprint is not None
assert answerer.last_request.blueprint.metadata["structurer_repair_count"] == 1
assert len(answerer.last_request.contexts) <= top_k
assert "promoted_supplemental_chunk" in final_context_ids
assert "replaced_answer_chunk" not in final_context_ids
```

- [ ] **Step 2: Run the smoke test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: FAIL until builder repair metadata and fake wiring are implemented.

- [ ] **Step 3: Update smoke fixture wiring**

Ensure the smoke uses:

- LLM-backed graph test double;
- LLM-backed blueprint builder or realistic fake client path;
- no deterministic graph builder;
- no deterministic blueprint planner;
- promotion still replacement-only.

- [ ] **Step 4: Run smoke test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Add smoke for exhausted structurer fallback**

Add a smoke case where the blueprint fake fails both attempts and the service
falls back to MiniRAG-selected contexts:

```python
def test_discorag_local_smoke_falls_back_to_minirag_when_blueprint_exhausts() -> None:
    ...
    result = service.query("How should the answer be organized?", top_k=2)
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"
    assert result.metadata["discorag_error"]["user_visible"] is True
    assert [chunk.chunk_id for chunk in result.contexts] == [
        "answer_chunk_a",
        "answer_chunk_b",
    ]
```

The fallback smoke must prove supplemental discourse chunks were not appended
to final answer contexts.

- [ ] **Step 6: Run smoke test again**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_local_smoke.py -q
```

Expected: PASS.

## Task 10: Contract Promotion

Purpose: document only behavior that has landed and passed tests.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/evidence/CONTRACTS.md`
- Modify: `src/ragflow_lite/application/CONTRACTS.md` if the service boundary
  needs an explicit note.

- [ ] **Step 1: Update evidence contract**

Add source-backed wording:

```markdown
## Structurer Retry Boundary

DiscoRAG structurer calls use bounded attempts. Validation failures are repaired
by asking the same structurer model to regenerate a complete JSON object using
multi-turn context and a short validation feedback turn. Timeout retries start a
fresh original attempt. Parsers remain strict; runtime services do not patch
invalid structure.
```

Include current defaults only if they are in code:

```markdown
The default structurer timeout is 90 seconds and the default max attempts is 2.
```

- [ ] **Step 2: Update application contract only if needed**

If `DiscoRAGQueryService` behavior is unchanged, keep this short:

```markdown
`DiscoRAGQueryService` consumes validated structurer outputs. It does not
append missing blueprint chunks or repair invalid promotions. When RST, graph,
or blueprint structurer attempts are exhausted, it visibly degrades to MiniRAG
direct answer with `AnswerResult.metadata["discorag_degraded"] == True` and a
user-visible `discorag_error` block.
```

- [ ] **Step 3: Check contract wording against source**

Run:

```bash
rg "structurer.*timeout|structurer.*attempt|complete_messages_json|ProcessingError" src/ragflow_lite docs/superpowers
```

Expected: contract wording matches actual source behavior.

## Task 11: Final Verification Gate

Purpose: prove the retry/repair slice did not regress the existing DiscoRAG
stabilization work.

- [ ] **Step 1: Run focused structurer tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_structurer_retry.py \
  tests/unit/infrastructure/test_deepseek_discourse_extractor.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_builder.py \
  tests/unit/infrastructure/test_llm_inter_chunk_graph_parser.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_builder.py \
  tests/unit/infrastructure/test_llm_discorag_blueprint_parser.py -q
```

Expected: PASS.

- [ ] **Step 2: Run application DiscoRAG tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/application/test_discorag_local_smoke.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Expected: PASS.

- [ ] **Step 3: Run live provider gate**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_providers.py --run-live-infinity -q
```

Expected: PASS against live Infinity.

- [ ] **Step 4: Run full unit suite**

Run:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Expected: PASS. Existing live-gated tests may be skipped in the non-live full
unit command.

- [ ] **Step 5: Run whitespace checks**

Run:

```bash
git diff --check && git diff --cached --check
```

Expected: no output and exit code 0.

## Self-Review Checklist

- Spec coverage:
  - Message-based DeepSeek calls: Task 1.
  - 90-second timeout config: Task 2 and Task 7.
  - Validation repair with short multi-turn feedback: Task 3, Task 4, Task 5,
    Task 6.
  - Timeout fresh attempt behavior: Task 7.
  - Exhausted structurer fallback to MiniRAG top_n contexts with explicit user
    visible error metadata: Task 8 and Task 9.
  - No `compact` mode: documented as a non-goal in the spec and omitted from
    tasks.
  - No deterministic runtime repair: Task 9 and Task 11 keep the existing
    DiscoRAG checks.
  - Contract promotion: Task 10.
- Placeholder scan:
  - No TBD or open-ended implementation placeholders remain.
  - Test names and commands are concrete.
- Type consistency:
  - `timeout_seconds` and `max_attempts` are used consistently across settings
    and builders.
  - `complete_messages_json()` is the message-based JSON entrypoint used by
    repair attempts.
