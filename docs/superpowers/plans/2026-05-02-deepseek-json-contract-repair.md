# DeepSeek JSON Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the DeepSeek migration review findings by centralizing JSON Output rules, adding deepeval schema prompting, restoring retry behavior, and strengthening tests.

**Architecture:** Keep the existing DeepSeek Chat Completions adapters and tighten their provider boundary. Runtime JSON callers use a shared `complete_json(...)` contract; deepeval schema calls wrap opaque deepeval prompts with a local JSON/schema instruction; retries live in the shared DeepSeek helper.

**Tech Stack:** Python, OpenAI Python SDK Chat Completions, Pydantic schemas, pytest fake-backed unit tests, existing `ProcessingError` domain errors.

---

## Scope Notes

This plan implements `docs/superpowers/specs/2026-05-02-deepseek-json-contract-repair-design.md`.

Do not regenerate deepeval goldens. Do not run live DeepSeek or live deepeval until fake-backed unit tests are green and the user explicitly asks for live validation. Do not change Ark embedding.

## File Structure

- Modify `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`: add JSON prompt guard, `max_tokens`, and retry/backoff.
- Modify `tests/unit/infrastructure/test_deepseek_chat.py`: strengthen helper tests for JSON contract and retry.
- Modify `tests/unit/infrastructure/test_deepseek_query_grounder.py`: assert the caller still sends a task-specific JSON example through the helper.
- Modify `tests/unit/infrastructure/test_deepseek_evidence_extractor.py`: assert the caller still sends a task-specific JSON example through the helper.
- Modify `tests/evals/eval_models.py`: add DeepSeek schema prompt wrapping and sync/async JSON validation behavior.
- Modify `tests/unit/test_eval_artifact_scripts.py`: strengthen deepeval model tests for schema prompt, plain generation, sync, and async.

### Task 1: DeepSeek JSON Output Guard

**Files:**
- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Modify: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add failing test for JSON instruction injection**

Add this test to `tests/unit/infrastructure/test_deepseek_chat.py`:

```python
def test_deepseek_chat_json_mode_injects_required_json_instruction() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )

    client.complete_json("Return a boolean object.", "{}")

    request = completions.requests[0]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 2048
    system_message = request["messages"][0]["content"]
    assert "json" in system_message.lower()
    assert "Return only one JSON object" in system_message
```

- [ ] **Step 2: Add failing test that existing JSON instructions are preserved**

Add this test:

```python
def test_deepseek_chat_json_mode_preserves_existing_json_example() -> None:
    completions = _FakeCompletions('{"ok": true}')
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    instructions = 'Return exactly one JSON object like {"ok": true}.'

    client.complete_json(instructions, "{}")

    system_message = completions.requests[0]["messages"][0]["content"]
    assert system_message == instructions
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/infrastructure/test_deepseek_chat.py
```

Expected: the new tests fail because `max_tokens` and JSON instruction injection are not implemented.

- [ ] **Step 4: Implement JSON instruction guard**

In `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`, add constants near the top:

```python
_DEFAULT_JSON_MAX_TOKENS = 2048
_DEEPSEEK_JSON_INSTRUCTION = (
    "Return only one JSON object. Do not include markdown or prose outside the JSON."
)
```

Change `complete_json(...)` to pass `max_tokens`:

```python
def complete_json(
    self,
    instructions: str,
    input_text: str,
    *,
    max_tokens: int = _DEFAULT_JSON_MAX_TOKENS,
) -> str:
    return self._complete(
        _ensure_json_instruction(instructions),
        input_text,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
```

Change `complete(...)` and `_complete(...)` signatures:

```python
def complete(self, instructions: str, input_text: str) -> str:
    return self._complete(
        instructions,
        input_text,
        response_format=None,
        max_tokens=None,
    )

def _complete(
    self,
    instructions: str,
    input_text: str,
    response_format: dict[str, str] | None,
    max_tokens: int | None,
) -> str:
```

Inside `_complete(...)`, add:

```python
if max_tokens is not None:
    request["max_tokens"] = max_tokens
```

Add helper:

```python
def _ensure_json_instruction(instructions: str) -> str:
    if "json" in instructions.lower():
        return instructions
    return f"{instructions.rstrip()}\n\n{_DEEPSEEK_JSON_INSTRUCTION}"
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/infrastructure/test_deepseek_chat.py
```

Expected: helper tests pass.

### Task 2: DeepSeek Retry and Backoff

**Files:**
- Modify: `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`
- Modify: `tests/unit/infrastructure/test_deepseek_chat.py`

- [ ] **Step 1: Add fake completion support for sequential failures**

Update `_FakeCompletions` in `tests/unit/infrastructure/test_deepseek_chat.py`:

```python
class _FakeCompletions:
    def __init__(
        self,
        content: str | None = "ok",
        *,
        failures: list[Exception] | None = None,
    ) -> None:
        self.content = content
        self.failures = list(failures or [])
        self.requests: list[dict] = []

    def create(self, **request):
        self.requests.append(request)
        if self.failures:
            raise self.failures.pop(0)
        message = SimpleNamespace(content=self.content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])
```

- [ ] **Step 2: Add failing retry success test**

Add:

```python
class _RetryableStatusError(Exception):
    status_code = 500


def test_deepseek_chat_retries_transient_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions("answer", failures=[_RetryableStatusError("boom")])
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr("ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep", sleeps.append)

    result = client.complete("System", "User")

    assert result == "answer"
    assert len(completions.requests) == 2
    assert sleeps == [0.5]
```

- [ ] **Step 3: Add failing non-retryable test**

Add:

```python
class _NonRetryableStatusError(Exception):
    status_code = 400


def test_deepseek_chat_does_not_retry_non_retryable_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    completions = _FakeCompletions(
        "answer",
        failures=[_NonRetryableStatusError("bad request")],
    )
    client = DeepSeekChatCompletionsClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=_FakeClient(completions),
    )
    monkeypatch.setattr("ragflow_lite.infrastructure.llms.deepseek_chat.time.sleep", sleeps.append)

    with pytest.raises(_NonRetryableStatusError):
        client.complete("System", "User")

    assert len(completions.requests) == 1
    assert sleeps == []
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/infrastructure/test_deepseek_chat.py
```

Expected: retry tests fail because `_complete(...)` does not retry.

- [ ] **Step 5: Implement retry policy**

In `src/ragflow_lite/infrastructure/llms/deepseek_chat.py`, import `time` and add:

```python
_MAX_DEEPSEEK_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5
```

Wrap the provider call in `_complete(...)`:

```python
for attempt in range(_MAX_DEEPSEEK_RETRIES + 1):
    try:
        response = self.client.chat.completions.create(**request)
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ProcessingError("DeepSeek returned no content.")
        return content.strip()
    except Exception as exc:
        if isinstance(exc, ProcessingError):
            raise
        if attempt >= _MAX_DEEPSEEK_RETRIES or not _should_retry_error(exc):
            raise
        time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
raise AssertionError("unreachable")
```

Add:

```python
def _should_retry_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code == 429 or status_code >= 500

    name = exc.__class__.__name__.lower()
    return (
        "ratelimit" in name
        or "rate_limit" in name
        or "timeout" in name
        or "connection" in name
    )
```

- [ ] **Step 6: Run helper tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/infrastructure/test_deepseek_chat.py
```

Expected: helper tests pass.

### Task 3: Strengthen Runtime JSON Caller Tests

**Files:**
- Modify: `tests/unit/infrastructure/test_deepseek_query_grounder.py`
- Modify: `tests/unit/infrastructure/test_deepseek_evidence_extractor.py`

- [ ] **Step 1: Add query-grounder instruction contract assertion**

In `test_deepseek_query_grounder_normalizes_json_output`, add after `result` assertions:

```python
instructions = grounder.client.calls[0]["instructions"]
assert "JSON object" in instructions
assert "answer_type_keywords" in instructions
assert "entities_from_query" in instructions
assert '"answer_type_keywords"' in instructions
```

- [ ] **Step 2: Add evidence-extractor instruction contract assertion**

In `test_deepseek_evidence_extractor_normalizes_json_output`, add after `batch` assertions:

```python
instructions = client.calls[0]["instructions"]
assert "JSON object" in instructions
assert '"entities"' in instructions
assert '"relations"' in instructions
assert '"source_chunk_ids"' in instructions
```

- [ ] **Step 3: Run runtime caller tests**

Run:

```bash
./.venv/bin/python -m pytest -q \
  tests/unit/infrastructure/test_deepseek_query_grounder.py \
  tests/unit/infrastructure/test_deepseek_evidence_extractor.py
```

Expected: tests pass if existing task-specific prompts still include examples.

### Task 4: Deepeval Schema Prompt Contract

**Files:**
- Modify: `tests/evals/eval_models.py`
- Modify: `tests/unit/test_eval_artifact_scripts.py`

- [ ] **Step 1: Add failing sync schema prompt test**

Replace the existing `test_deepseek_deepeval_model_validates_schema_output` assertions with the stricter version below:

```python
def test_deepseek_deepeval_model_validates_schema_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result(BaseModel):
        answer: str

    class FakeMessage:
        content = '{"answer": "ok"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    result = model.generate("Score the answer.", schema=Result)

    assert result == Result(answer="ok")
    request = captured["create_kwargs"]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 2048
    prompt = request["messages"][0]["content"]
    assert "Score the answer." in prompt
    assert "Return only one JSON object" in prompt
    assert "json" in prompt.lower()
    assert '"answer"' in prompt
```

- [ ] **Step 2: Add failing plain generation no-json test**

Add:

```python
def test_deepseek_deepeval_plain_generation_does_not_request_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = "plain response"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    assert model.generate("hello") == "plain response"
    assert "response_format" not in captured["create_kwargs"]
    assert "max_tokens" not in captured["create_kwargs"]
```

- [ ] **Step 3: Add failing async schema prompt test**

Add:

```python
def test_deepseek_deepeval_model_validates_async_schema_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result(BaseModel):
        answer: str

    class FakeMessage:
        content = '{"answer": "async ok"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        async def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    result = asyncio.run(model.a_generate("Score async.", schema=Result))

    assert result == Result(answer="async ok")
    request = captured["create_kwargs"]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 2048
    prompt = request["messages"][0]["content"]
    assert "Score async." in prompt
    assert "Return only one JSON object" in prompt
    assert '"answer"' in prompt
```

- [ ] **Step 4: Run tests to verify failure**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/test_eval_artifact_scripts.py -k "deepseek_deepeval"
```

Expected: schema prompt tests fail because schema mode only forwards the raw prompt.

- [ ] **Step 5: Implement schema prompt builder**

In `tests/evals/eval_models.py`, add constants near `_LLM_CALL_TIMEOUT`:

```python
_DEFAULT_JSON_MAX_TOKENS = 2048
_SCHEMA_JSON_INSTRUCTION = (
    "Return only one JSON object that conforms to this JSON schema. "
    "Do not include markdown or prose outside the JSON."
)
```

Add helper:

```python
def _schema_prompt(prompt: str, schema: type[BaseModel]) -> str:
    schema_json = schema.model_json_schema()
    return "\n\n".join(
        [
            prompt.strip(),
            _SCHEMA_JSON_INSTRUCTION,
            "JSON schema:",
            json.dumps(schema_json, ensure_ascii=False, sort_keys=True),
        ]
    )
```

Add `import json` at the top.

- [ ] **Step 6: Use schema prompt in sync generation**

In `DeepSeekChatDeepEvalModel.generate(...)`, build `prompt_text`:

```python
prompt_text = _schema_prompt(prompt, schema) if schema is not None else prompt
request: dict[str, Any] = {
    "model": self.name,
    "messages": [{"role": "user", "content": prompt_text}],
    "reasoning_effort": self.reasoning_effort,
    "extra_body": {"thinking": {"type": "enabled"}},
}
if schema is not None:
    request["response_format"] = {"type": "json_object"}
    request["max_tokens"] = _DEFAULT_JSON_MAX_TOKENS
```

Keep:

```python
return schema.model_validate_json(content.strip())
```

- [ ] **Step 7: Use schema prompt in async generation**

Apply the same `prompt_text`, `response_format`, and `max_tokens` changes in `a_generate(...)`.

- [ ] **Step 8: Run deepeval adapter tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/unit/test_eval_artifact_scripts.py -k "deepseek_deepeval"
```

Expected: selected tests pass.

### Task 5: Focused Verification and Review

**Files:**
- No production files unless earlier tasks reveal a narrow necessary fix.

- [ ] **Step 1: Run DeepSeek repair unit surface**

Run:

```bash
./.venv/bin/python -m pytest -q \
  tests/unit/infrastructure/test_deepseek_chat.py \
  tests/unit/infrastructure/test_deepseek_query_grounder.py \
  tests/unit/infrastructure/test_deepseek_evidence_extractor.py \
  tests/unit/test_eval_artifact_scripts.py -k "deepseek_deepeval or build_synthesizer_model or context_construction"
```

Expected: all selected tests pass.

- [ ] **Step 2: Run provider wiring tests if touched**

If `src/ragflow_lite/config/settings.py` or `src/ragflow_lite/api/deps/providers.py` changed during repair, run:

```bash
./.venv/bin/python -m pytest -q tests/unit/api/test_providers.py
```

Expected: pass, except only documented pre-existing failures if the broader branch already has them.

- [ ] **Step 3: Run legacy adapter tests if retry/helper changes touched shared imports**

Run:

```bash
./.venv/bin/python -m pytest -q \
  tests/unit/infrastructure/test_openai_responses_answerer.py \
  tests/unit/infrastructure/test_openai_query_grounder.py \
  tests/unit/infrastructure/test_openai_evidence_extractor.py
```

Expected: legacy adapter tests pass. If a file does not exist in the current branch, report that it was not applicable.

- [ ] **Step 4: Request code review**

Use `superpowers:requesting-code-review` with:

- What was implemented: DeepSeek JSON Output contract repair, deepeval schema prompt repair, DeepSeek retry restoration, test strengthening.
- Requirements: `docs/superpowers/specs/2026-05-02-deepseek-json-contract-repair-design.md`.
- Base SHA: `HEAD` before implementation or the current branch base.
- Head SHA: implementation commit or current worktree head.

- [ ] **Step 5: Final report**

Report:

- Files changed.
- Which review findings are closed.
- Exact commands run and pass/fail results.
- Any tests not run.
- Whether live DeepSeek/deepeval validation was skipped.
- Any remaining pre-existing branch failures.

