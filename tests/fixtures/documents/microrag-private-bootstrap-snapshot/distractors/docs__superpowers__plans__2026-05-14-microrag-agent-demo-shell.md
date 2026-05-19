# MicroRAG Agent Demo Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage MicroRAG agent demo shell: a MicroRAG-owned UI/backend surface that talks to an ACP-backed external agent runtime and lets Claude Code-managed skills call `mcrag retrieve` / `mcrag answer`.

**Architecture:** Keep the existing `/api/v0/queries` answer-producing path intact. Add a retrieval-only application boundary before `Answerer.answer()`, serialize clean model-facing JSON for `mcrag retrieve`, preserve `mcrag answer` for answer-included flows and RAG evaluation, then add a minimal ACP session adapter plus Python-served demo shell with strict runtime redaction.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, stdlib `argparse`, stdlib `json`, stdlib `sqlite3`, pytest, existing MicroRAG application/domain/infrastructure services, external Claude Code ACP stdio runtime.

---

Date: 2026-05-14
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-14-microrag-agent-demo-shell.md](../specs/2026-05-14-microrag-agent-demo-shell.md)

## File Structure

Files to create:

- `src/ragflow_lite/application/services/model_facing_retrieval.py`
  - Shared retrieval-only result models, context ordering helpers, blueprint serialization, and model-facing JSON payload construction.
- `src/ragflow_lite/application/services/agent_retrieval_service.py`
  - New retrieval-only service that supports `standard` and `discorag` without calling `Answerer.answer()`.
- `src/ragflow_lite/cli/__init__.py`
  - CLI package marker.
- `src/ragflow_lite/cli/mcrag.py`
  - `mcrag retrieve` and `mcrag answer` command implementation.
- `.claude/skills/microrag-search/SKILL.md`
  - Claude Code-managed skill instructions for using the deterministic local `mcrag` CLI.
- `src/ragflow_lite/infrastructure/agent/acp_client.py`
  - ACP stdio subprocess adapter with redaction boundaries and testable process hooks.
- `src/ragflow_lite/infrastructure/agent/session_store.py`
  - Local SQLite-backed UI session metadata index. Claude Code transcripts remain the source of truth.
- `src/ragflow_lite/infrastructure/agent/__init__.py`
  - Agent infrastructure exports.
- `src/ragflow_lite/api/schemas/agent.py`
  - Pydantic request/response models for first-stage agent sessions and messages.
- `src/ragflow_lite/api/routes/agent.py`
  - MicroRAG-owned agent session/message endpoints.
- `src/ragflow_lite/api/routes/ui.py`
  - Minimal Python-served demo shell route.
- `src/ragflow_lite/static/agent-shell.css`
  - Minimal demo shell styling.
- `src/ragflow_lite/static/agent-shell.js`
  - Minimal demo shell behavior using MicroRAG endpoints only.
- `tests/unit/application/test_model_facing_retrieval.py`
  - Ordering and serialization unit tests.
- `tests/unit/application/test_agent_retrieval_service.py`
  - Retrieval-only service tests proving no answerer call.
- `tests/unit/cli/test_mcrag_cli.py`
  - CLI parser/stdout/stderr/setup-error tests.
- `tests/unit/infrastructure/test_agent_session_store.py`
  - SQLite metadata index tests.
- `tests/unit/infrastructure/test_acp_client_redaction.py`
  - ACP event/error redaction tests.
- `tests/unit/api/test_agent_routes.py`
  - Agent endpoint tests.
- `tests/integration/api/test_ui_shell.py`
  - UI shell response and visible text redaction tests.

Files to modify:

- `pyproject.toml`
  - Add `mcrag` console script and package data for static assets if needed.
- `src/ragflow_lite/application/services/query_service.py`
  - Expose an answer-request builder so standard answer and retrieval-only paths share retrieval behavior without duplicating internals.
- `src/ragflow_lite/application/services/discorag_query_service.py`
  - Expose a DiscoRAG answer-request builder that stops before the answerer; preserve existing answer-included fallback behavior.
- `src/ragflow_lite/application/services/__init__.py`
  - Export new application service symbols.
- `src/ragflow_lite/api/deps/providers.py`
  - Add `agent_retrieval_service`, `agent_session_store`, and ACP adapter to `AppServices`.
- `src/ragflow_lite/app.py`
  - Include agent API router and UI shell/static route mounting.
- `src/ragflow_lite/infrastructure/answerers/_input_formatting.py`
  - Remove prompt-facing retrieval rewrite notice behavior or make it return no prompt text.
- `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
  - Use shared ordering policy, place contexts before blueprint, and stop inserting low-quality notice text into prompt input.
- `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
  - Mirror the same prompt/order changes as OpenAI answerer.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Update active application contract after behavior lands.
- `src/ragflow_lite/api/CONTRACTS.md`
  - Add the agent route / UI metadata boundary after route behavior lands.
- `src/ragflow_lite/infrastructure/CONTRACTS.md`
  - Add ACP runtime redaction and local session metadata notes after infrastructure behavior lands.
- `tests/unit/application/test_query_service.py`
  - Cover shared answer-request builder and metadata side-channel preservation.
- `tests/unit/application/test_discorag_query_service.py`
  - Cover DiscoRAG request builder, final top-n context preservation, and explicit blueprint failure/fallback boundaries.
- `tests/unit/infrastructure/test_input_formatting.py`
  - Replace prompt notice expectations with no-prompt-text expectations.
- `tests/unit/infrastructure/test_openai_responses_answerer.py`
  - Update answerer prompt/order assertions.
- `tests/unit/infrastructure/test_deepseek_chat_answerer.py`
  - Update answerer prompt/order assertions.
- `tests/unit/api/test_v0_routes.py`
- `tests/integration/api/test_v0_endpoints.py`
  - Ensure `/api/v0/queries` remains answer-producing.

## Implementation Notes

- Use `rtk` for shell commands in this repo.
- Keep `AGENTS.md` untouched unless the user explicitly asks; it is currently dirty and unrelated.
- `docs/superpowers/` is gitignored. If the plan/spec should be tracked later, use `git add -f`.
- Do not add MCP.
- Do not route `/api/v0/queries` to retrieval-only behavior.
- Do not store full conversation history in MicroRAG SQLite. Store UI metadata only.
- Use SQLite for first-stage UI session metadata because the approved product
  boundary is backend local file / SQLite; do not expand it into a conversation
  database.
- Do not delete `参考项目/claude-code/.git` until the nested Git preflight task has passed.
- Do not expose `Claude Code`, `claude-code`, raw cwd, transcript paths, raw command lines, raw stderr, or raw ACP `agentInfo` to the MicroRAG UI.

## Task 0: Baseline Preflight

Purpose: confirm current repo shape before any behavior changes.

- [ ] **Step 1: Check worktree and ignored planning artifacts**

Run:

```bash
rtk git status --short --branch
rtk git check-ignore -v docs/superpowers/specs/2026-05-14-microrag-agent-demo-shell.md docs/superpowers/plans/2026-05-14-microrag-agent-demo-shell.md || true
```

Expected:

- `AGENTS.md` may be dirty from unrelated user work.
- `docs/superpowers/` is ignored by `.gitignore`.

- [ ] **Step 2: Confirm no existing CLI or frontend app**

Run:

```bash
rtk rg -n "project\\.scripts|console_scripts|entry_points|package.json|vite.config|StaticFiles|Jinja2Templates|app\\.mount" pyproject.toml src tests -g '!**/__pycache__/**'
```

Expected:

- No product CLI entrypoint exists.
- No existing frontend app or static UI mount exists.

- [ ] **Step 3: Run current focused baseline tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_query_service.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/api/test_v0_routes.py -q
```

Expected: selected tests pass before changes. If they fail, stop and record the existing failure before editing.

## Task 1: Add Model-Facing Retrieval Serialization

Purpose: create the shared ordering and serialization layer used by `mcrag retrieve` and answer prompts.

**Files:**

- Create: `src/ragflow_lite/application/services/model_facing_retrieval.py`
- Modify: `src/ragflow_lite/application/services/__init__.py`
- Test: `tests/unit/application/test_model_facing_retrieval.py`

- [ ] **Step 1: Write failing ordering and JSON tests**

Create `tests/unit/application/test_model_facing_retrieval.py`:

```python
from ragflow_lite.application.services.model_facing_retrieval import (
    blueprint_payload,
    model_facing_retrieval_payload,
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
from ragflow_lite.domain.models import AnswerBlueprint, RetrievedChunk


def _chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=f"text {chunk_id}",
        score=score,
        metadata={"kept": chunk_id},
    )


def test_standard_contexts_use_u_shaped_attention_order() -> None:
    contexts = [_chunk("c1", 1.0), _chunk("c2", 0.9), _chunk("c3", 0.8), _chunk("c4", 0.7)]

    ordered = order_standard_contexts_for_model(contexts)

    assert [context.chunk_id for context in ordered] == ["c1", "c3", "c4", "c2"]
    assert {context.chunk_id for context in ordered} == {"c1", "c2", "c3", "c4"}


def test_standard_contexts_with_two_items_preserve_score_order() -> None:
    contexts = [_chunk("c2", 0.2), _chunk("c1", 0.9)]

    ordered = order_standard_contexts_for_model(contexts)

    assert [context.chunk_id for context in ordered] == ["c1", "c2"]


def test_discorag_contexts_are_score_descending() -> None:
    contexts = [_chunk("weak", 0.1), _chunk("strong", 1.0), _chunk("middle", 0.5)]

    ordered = order_discorag_contexts_for_model(contexts)

    assert [context.chunk_id for context in ordered] == ["strong", "middle", "weak"]


def test_blueprint_payload_field_order_puts_ordered_ids_last() -> None:
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["c1", "c2"],
        chunk_roles={"c1": "claim"},
        answer_constraints=["avoid unsupported claims"],
        plan_steps=["compare evidence"],
        metadata={"internal": "not-model-facing"},
    )

    payload = blueprint_payload(blueprint)

    assert list(payload.keys()) == [
        "chunk_roles",
        "answer_constraints",
        "plan_steps",
        "ordered_chunk_ids",
    ]
    assert "metadata" not in payload


def test_standard_payload_omits_mode_metadata_and_blueprint() -> None:
    payload = model_facing_retrieval_payload(
        query="What is MicroRAG?",
        contexts=[_chunk("c1", 1.0), _chunk("c2", 0.8)],
        blueprint=None,
    )

    assert list(payload.keys()) == ["query", "contexts"]
    assert "mode" not in payload
    assert "metadata" not in payload
    assert "blueprint" not in payload
    assert payload["contexts"][0]["metadata"] == {"kept": "c1"}


def test_discorag_payload_places_blueprint_after_contexts() -> None:
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["c1"],
        chunk_roles={"c1": "claim"},
        answer_constraints=[],
        plan_steps=["answer from c1"],
    )

    payload = model_facing_retrieval_payload(
        query="Question",
        contexts=[_chunk("c1", 0.7)],
        blueprint=blueprint,
    )

    assert list(payload.keys()) == ["query", "contexts", "blueprint"]
    assert list(payload["blueprint"].keys())[-1] == "ordered_chunk_ids"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_model_facing_retrieval.py -q
```

Expected: FAIL because `model_facing_retrieval.py` does not exist.

- [ ] **Step 3: Implement the serializer**

Create `src/ragflow_lite/application/services/model_facing_retrieval.py`:

```python
from __future__ import annotations

from typing import Any

from ragflow_lite.domain.models import AnswerBlueprint, RetrievedChunk


def _score_desc(contexts: list[RetrievedChunk]) -> list[RetrievedChunk]:
    return sorted(contexts, key=lambda context: context.score, reverse=True)


def order_standard_contexts_for_model(
    contexts: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    ordered = _score_desc(contexts)
    if len(ordered) < 3:
        return ordered
    return [ordered[0], *ordered[2:], ordered[1]]


def order_discorag_contexts_for_model(
    contexts: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    return _score_desc(contexts)


def context_payload(context: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": context.chunk_id,
        "document_id": context.document_id,
        "text": context.text,
        "score": context.score,
        "metadata": dict(context.metadata),
    }


def blueprint_payload(blueprint: AnswerBlueprint) -> dict[str, Any]:
    return {
        "chunk_roles": dict(blueprint.chunk_roles),
        "answer_constraints": list(blueprint.answer_constraints),
        "plan_steps": list(blueprint.plan_steps),
        "ordered_chunk_ids": list(blueprint.ordered_chunk_ids),
    }


def model_facing_retrieval_payload(
    *,
    query: str,
    contexts: list[RetrievedChunk],
    blueprint: AnswerBlueprint | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "contexts": [context_payload(context) for context in contexts],
    }
    if blueprint is not None:
        payload["blueprint"] = blueprint_payload(blueprint)
    return payload
```

Update `src/ragflow_lite/application/services/__init__.py`:

```python
from ragflow_lite.application.services.model_facing_retrieval import (
    blueprint_payload,
    context_payload,
    model_facing_retrieval_payload,
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
```

Add these names to `__all__`.

- [ ] **Step 4: Verify tests pass**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_model_facing_retrieval.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/ragflow_lite/application/services/model_facing_retrieval.py src/ragflow_lite/application/services/__init__.py tests/unit/application/test_model_facing_retrieval.py
rtk git commit -m "feat: add model-facing retrieval serialization"
```

## Task 2: Extract Answer Request Builders Without Changing `/queries`

Purpose: make standard and DiscoRAG orchestration reusable before the answerer boundary.

**Files:**

- Modify: `src/ragflow_lite/application/services/query_service.py`
- Modify: `src/ragflow_lite/application/services/discorag_query_service.py`
- Test: `tests/unit/application/test_query_service.py`
- Test: `tests/unit/application/test_discorag_query_service.py`

- [ ] **Step 1: Add failing standard request-builder test**

Add to `tests/unit/application/test_query_service.py`:

```python
def test_build_answer_request_retrieves_contexts_without_calling_answerer() -> None:
    chunk = _chunk("topology context")
    answerer = FakeAnswerer()
    service = QueryService(
        retriever=FakeTopologyRetriever(
            results=[chunk],
            retrieval_metadata={
                "retrieval_rewrite": {"answer_notice_required": True}
            },
        ),
        answerer=answerer,
    )

    request = service.build_answer_request("q", top_k=5)

    assert request == AnswerRequest(
        query="q",
        contexts=[chunk],
        metadata={"retrieval_rewrite": {"answer_notice_required": True}},
    )
    assert answerer.last_request is None
```

- [ ] **Step 2: Add failing DiscoRAG request-builder tests**

Add to `tests/unit/application/test_discorag_query_service.py`:

```python
def _build_request_builder_service(
    *,
    contexts: list[RetrievedChunk],
    blueprint: AnswerBlueprint,
) -> tuple[DiscoRAGQueryService, RecordingAnswerer]:
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=FakeTopologyRetriever(result=_retrieval_result(chunks=contexts)),
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=RecordingDiscourseExtractor(),
        inter_chunk_graph_builder=RecordingGraphBuilder(),
        blueprint_builder=RecordingBlueprintBuilder(blueprint=blueprint),
        answerer=answerer,
    )
    return service, answerer


def test_build_answer_request_returns_discorag_request_before_answerer() -> None:
    service, answerer = _build_request_builder_service(
        contexts=[
            RetrievedChunk("c1", "doc1", "strong", 0.9),
            RetrievedChunk("c2", "doc2", "weak", 0.2),
        ],
        blueprint=AnswerBlueprint(
            ordered_chunk_ids=["c1", "c2"],
            chunk_roles={"c1": "claim", "c2": "support"},
            answer_constraints=["cite evidence"],
            plan_steps=["use c1 then c2"],
        ),
    )

    request = service.build_answer_request("q", 2)

    assert request.mode == "discorag"
    assert request.blueprint is not None
    assert request.blueprint.ordered_chunk_ids == ["c1", "c2"]
    assert [context.chunk_id for context in request.contexts] == ["c1", "c2"]
    assert answerer.last_request is None


def test_build_answer_request_raises_when_blueprint_missing_final_context() -> None:
    service, _answerer = _build_request_builder_service(
        contexts=[
            RetrievedChunk("c1", "doc1", "strong", 0.9),
            RetrievedChunk("c2", "doc2", "weak", 0.2),
        ],
        blueprint=AnswerBlueprint(
            ordered_chunk_ids=["c1"],
            chunk_roles={"c1": "claim"},
            answer_constraints=[],
            plan_steps=[],
        ),
    )

    with pytest.raises(ProcessingError, match="missing final context ids"):
        service.build_answer_request("q", 2)
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_query_service.py::test_build_answer_request_retrieves_contexts_without_calling_answerer \
  tests/unit/application/test_discorag_query_service.py::test_build_answer_request_returns_discorag_request_before_answerer \
  tests/unit/application/test_discorag_query_service.py::test_build_answer_request_raises_when_blueprint_missing_final_context -q
```

Expected: FAIL because `build_answer_request()` does not exist.

- [ ] **Step 4: Implement standard request builder**

In `src/ragflow_lite/application/services/query_service.py`, add:

```python
    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        contexts, request_metadata = self._retrieve_contexts_and_metadata(query, top_k)
        return AnswerRequest(
            query=query,
            contexts=contexts,
            metadata=request_metadata,
        )
```

Then change `query()` to:

```python
            request = self.build_answer_request(query, top_k)
            result = self.answerer.answer(request)
```

- [ ] **Step 5: Implement DiscoRAG request builder**

In `src/ragflow_lite/application/services/discorag_query_service.py`, add a private helper that builds an answer request from an already retrieved result:

```python
    def _build_answer_request_from_retrieval(
        self,
        query: str,
        retrieval_result: TopologyRetrievalResult,
    ) -> AnswerRequest:
        evidence_package = self.evidence_package_builder.build(retrieval_result)
        discourse_package = self.discourse_extractor.extract(evidence_package)
        inter_chunk_graph = self.inter_chunk_graph_builder.build(discourse_package)
        blueprint = self.blueprint_builder.build(
            discourse_package,
            graph=inter_chunk_graph,
        )
        answer_contexts = _contexts_with_bounded_promotion(
            retrieval_result.chunks,
            retrieval_result,
            blueprint,
        )
        answer_blueprint = _blueprint_for_contexts(blueprint, answer_contexts)
        answer_metadata: dict[str, object] = {
            "source_selection": retrieval_result.metadata.get("source_selection"),
        }
        if "retrieval_rewrite" in retrieval_result.metadata:
            answer_metadata["retrieval_rewrite"] = retrieval_result.metadata[
                "retrieval_rewrite"
            ]
        request = AnswerRequest(
            query=query,
            contexts=answer_contexts,
            mode="discorag",
            blueprint=answer_blueprint,
            metadata=answer_metadata,
        )
        return request

    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        retrieval_result = self.retriever.retrieve_context(query, top_k)
        return self._build_answer_request_from_retrieval(
            query,
            retrieval_result,
        )
```

Change the successful body of `query()` so retrieval happens before the structurer-stage `try`. This preserves the existing MiniRAG fallback behavior because `retrieval_result` is always defined before any `StructurerAttemptsExhaustedError` can be raised:

```python
            retrieval_result = self.retriever.retrieve_context(query, top_k)
            try:
                request = self._build_answer_request_from_retrieval(
                    query,
                    retrieval_result,
                )
            except StructurerAttemptsExhaustedError as exc:
                return self._answer_with_minirag_fallback(
                    query=query,
                    top_k=top_k,
                    retrieval_result=retrieval_result,
                    exc=exc,
                )
            result = self.answerer.answer(request)
```

The observable contract is: `build_answer_request()` stops before the answerer and raises structurer/processing errors explicitly; `query()` keeps existing answer-included fallback behavior without retrieving twice on a structurer fallback.

- [ ] **Step 6: Verify request-builder tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_query_service.py tests/unit/application/test_discorag_query_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add src/ragflow_lite/application/services/query_service.py src/ragflow_lite/application/services/discorag_query_service.py tests/unit/application/test_query_service.py tests/unit/application/test_discorag_query_service.py
rtk git commit -m "refactor: expose answer request builders"
```

## Task 3: Add Retrieval-Only Agent Service

Purpose: provide `standard` and `discorag` retrieval evidence without generating an answer.

**Files:**

- Create: `src/ragflow_lite/application/services/agent_retrieval_service.py`
- Modify: `src/ragflow_lite/application/services/__init__.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/application/test_agent_retrieval_service.py`

- [ ] **Step 1: Write failing retrieval-only tests**

Create `tests/unit/application/test_agent_retrieval_service.py`:

```python
import pytest

from ragflow_lite.application.services.agent_retrieval_service import (
    AgentRetrievalService,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerBlueprint, AnswerRequest, RetrievedChunk


class FakeAnswerRequestPath:
    def __init__(self, request: AnswerRequest) -> None:
        self.request = request
        self.calls: list[tuple[str, int]] = []

    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        self.calls.append((query, top_k))
        return self.request


def test_retrieve_standard_returns_clean_payload() -> None:
    service = AgentRetrievalService(
        standard_service=FakeAnswerRequestPath(
            AnswerRequest(
                query="q",
                contexts=[
                    RetrievedChunk("c1", "d1", "one", 1.0),
                    RetrievedChunk("c2", "d2", "two", 0.9),
                    RetrievedChunk("c3", "d3", "three", 0.8),
                ],
                metadata={"retrieval_rewrite": {"answer_notice_required": True}},
            )
        ),
        discorag_service=FakeAnswerRequestPath(
            AnswerRequest(query="unused", contexts=[])
        ),
    )

    result = service.retrieve("q", 3, mode="standard")

    assert list(result.payload.keys()) == ["query", "contexts"]
    assert [context["chunk_id"] for context in result.payload["contexts"]] == [
        "c1",
        "c3",
        "c2",
    ]
    assert result.runtime_metadata["retrieval_rewrite"] == {
        "answer_notice_required": True
    }
    assert "metadata" not in result.payload
    assert "mode" not in result.payload


def test_retrieve_discorag_returns_contexts_then_blueprint() -> None:
    blueprint = AnswerBlueprint(
        ordered_chunk_ids=["c2", "c1"],
        chunk_roles={"c1": "support", "c2": "claim"},
        answer_constraints=["ground claims"],
        plan_steps=["start from c2"],
    )
    service = AgentRetrievalService(
        standard_service=FakeAnswerRequestPath(AnswerRequest(query="unused", contexts=[])),
        discorag_service=FakeAnswerRequestPath(
            AnswerRequest(
                query="q",
                contexts=[
                    RetrievedChunk("c1", "d1", "one", 0.2),
                    RetrievedChunk("c2", "d2", "two", 0.9),
                ],
                mode="discorag",
                blueprint=blueprint,
                metadata={"source_selection": {"internal": True}},
            )
        ),
    )

    result = service.retrieve("q", 2, mode="discorag")

    assert list(result.payload.keys()) == ["query", "contexts", "blueprint"]
    assert [context["chunk_id"] for context in result.payload["contexts"]] == ["c2", "c1"]
    assert list(result.payload["blueprint"].keys()) == [
        "chunk_roles",
        "answer_constraints",
        "plan_steps",
        "ordered_chunk_ids",
    ]
    assert "source_selection" not in result.payload
    assert result.runtime_metadata == {"source_selection": {"internal": True}}


def test_retrieve_discorag_requires_blueprint() -> None:
    service = AgentRetrievalService(
        standard_service=FakeAnswerRequestPath(AnswerRequest(query="unused", contexts=[])),
        discorag_service=FakeAnswerRequestPath(
            AnswerRequest(query="q", contexts=[], mode="discorag", blueprint=None)
        ),
    )

    with pytest.raises(ProcessingError, match="DiscoRAG retrieval requires a blueprint"):
        service.retrieve("q", 2, mode="discorag")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_agent_retrieval_service.py -q
```

Expected: FAIL because `agent_retrieval_service.py` does not exist.

- [ ] **Step 3: Implement service**

Create `src/ragflow_lite/application/services/agent_retrieval_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ragflow_lite.application.services.model_facing_retrieval import (
    model_facing_retrieval_payload,
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerRequest

RetrievalMode = Literal["standard", "discorag"]


class AnswerRequestBuilder(Protocol):
    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest: ...


@dataclass(slots=True)
class AgentRetrievalResult:
    payload: dict[str, object]
    runtime_metadata: dict[str, object] = field(default_factory=dict)


class AgentRetrievalService:
    def __init__(
        self,
        *,
        standard_service: AnswerRequestBuilder,
        discorag_service: AnswerRequestBuilder,
    ) -> None:
        self.standard_service = standard_service
        self.discorag_service = discorag_service

    def retrieve(
        self,
        query: str,
        top_k: int,
        *,
        mode: RetrievalMode = "standard",
    ) -> AgentRetrievalResult:
        if mode == "standard":
            request = self.standard_service.build_answer_request(query, top_k)
            contexts = order_standard_contexts_for_model(request.contexts)
            return AgentRetrievalResult(
                payload=model_facing_retrieval_payload(
                    query=request.query,
                    contexts=contexts,
                    blueprint=None,
                ),
                runtime_metadata=dict(request.metadata),
            )

        if mode == "discorag":
            request = self.discorag_service.build_answer_request(query, top_k)
            if request.blueprint is None:
                raise ProcessingError("DiscoRAG retrieval requires a blueprint.")
            contexts = order_discorag_contexts_for_model(request.contexts)
            return AgentRetrievalResult(
                payload=model_facing_retrieval_payload(
                    query=request.query,
                    contexts=contexts,
                    blueprint=request.blueprint,
                ),
                runtime_metadata=dict(request.metadata),
            )

        raise ProcessingError(f"Unsupported retrieval mode: {mode!r}.")
```

Update `src/ragflow_lite/application/services/__init__.py` exports.

Update `src/ragflow_lite/api/deps/providers.py`:

```python
from ragflow_lite.application.services import AgentRetrievalService


@dataclass(slots=True)
class AppServices:
    ...
    agent_retrieval_service: AgentRetrievalService | None = None
```

When returning `AppServices`, pass:

```python
        agent_retrieval_service=AgentRetrievalService(
            standard_service=query_service,
            discorag_service=discorag_query_service,
        ),
```

- [ ] **Step 4: Verify service tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/application/test_agent_retrieval_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify current query route still answers**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/integration/api/test_v0_endpoints.py::test_query_endpoint_defaults_to_standard_mode \
  tests/integration/api/test_v0_endpoints.py::test_query_endpoint_accepts_discorag_mode -q
```

Expected: PASS. The lightweight integration route tests confirm `/api/v0/queries` still returns an answer-producing `QueryResponse` and still dispatches `standard` / `discorag` through `QueryModeRouter`.

- [ ] **Step 6: Commit**

```bash
rtk git add src/ragflow_lite/application/services/agent_retrieval_service.py src/ragflow_lite/application/services/__init__.py src/ragflow_lite/api/deps/providers.py tests/unit/application/test_agent_retrieval_service.py tests/integration/api/test_v0_endpoints.py
rtk git commit -m "feat: add retrieval-only agent service"
```

## Task 4: Align Answer Prompts With Model-Facing Evidence Policy

Purpose: remove low-quality retrieval notice prompt injection and align context/blueprint order for answer-included paths.

**Files:**

- Modify: `src/ragflow_lite/infrastructure/answerers/_input_formatting.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
- Test: `tests/unit/infrastructure/test_input_formatting.py`
- Test: `tests/unit/infrastructure/test_openai_responses_answerer.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat_answerer.py`

- [ ] **Step 1: Replace retrieval rewrite notice test**

In `tests/unit/infrastructure/test_input_formatting.py`, replace prompt-notice expectations with:

```python
from ragflow_lite.infrastructure.answerers._input_formatting import (
    format_retrieval_rewrite_notice,
)


def test_retrieval_rewrite_notice_is_not_prompt_text() -> None:
    lines = format_retrieval_rewrite_notice(
        {
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        }
    )

    assert lines == []
```

- [ ] **Step 2: Add answerer prompt-order assertions**

In both answerer test files, add or update assertions so captured prompt text satisfies:

```python
assert "Retrieval rewrite notice:" not in prompt
assert prompt.index("Contexts:") < prompt.index("Blueprint:")
assert prompt.rindex("ordered_chunk_ids") > prompt.rindex("plan_steps")
```

For standard-mode prompt tests, assert U-shaped context order by checking the text offsets:

```python
assert prompt.index("text c1") < prompt.index("text c3") < prompt.index("text c2")
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_input_formatting.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py -q
```

Expected: FAIL because answerers still insert the notice and currently place `Blueprint:` before `Contexts:`.

- [ ] **Step 4: Remove prompt notice output**

In `src/ragflow_lite/infrastructure/answerers/_input_formatting.py`, make the function deterministic no-op prompt text:

```python
from __future__ import annotations

from typing import Any


def format_retrieval_rewrite_notice(metadata: dict[str, Any]) -> list[str]:
    return []
```

Keep the function for compatibility with existing imports during this change.

- [ ] **Step 5: Update answerer ordering**

In both `openai_responses.py` and `deepseek_chat.py`:

- Import shared helpers:

```python
from ragflow_lite.application.services.model_facing_retrieval import (
    order_discorag_contexts_for_model,
    order_standard_contexts_for_model,
)
```

- Change `_order_contexts()` behavior:

```python
if request.mode == "discorag":
    return order_discorag_contexts_for_model(request.contexts)
return order_standard_contexts_for_model(request.contexts)
```

Preserve existing metadata fields such as `answer_mode`, `blueprint_applied`, and explicit blueprint fallback reason if tests depend on them. The context list must not drop chunks.

- [ ] **Step 6: Update prompt section order and blueprint field order**

In both answerers' `_build_input()`:

- Build prompt in this order:

```text
Question:
Contexts:
Blueprint:
```

- Do not insert `format_retrieval_rewrite_notice()` output into prompt text.
- Serialize blueprint fields in this order:

```text
chunk_roles
answer_constraints
plan_steps
ordered_chunk_ids
```

- [ ] **Step 7: Verify answerer tests**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/infrastructure/test_input_formatting.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
rtk git add src/ragflow_lite/infrastructure/answerers/_input_formatting.py src/ragflow_lite/infrastructure/answerers/openai_responses.py src/ragflow_lite/infrastructure/answerers/deepseek_chat.py tests/unit/infrastructure/test_input_formatting.py tests/unit/infrastructure/test_openai_responses_answerer.py tests/unit/infrastructure/test_deepseek_chat_answerer.py
rtk git commit -m "fix: keep retrieval quality notices out of answer prompts"
```

## Task 5: Add `mcrag` CLI

Purpose: expose deterministic local commands for Claude Code-managed skills.

**Files:**

- Modify: `pyproject.toml`
- Create: `src/ragflow_lite/cli/__init__.py`
- Create: `src/ragflow_lite/cli/mcrag.py`
- Test: `tests/unit/cli/test_mcrag_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/unit/cli/test_mcrag_cli.py`:

```python
import json

from ragflow_lite.cli import mcrag
from ragflow_lite.domain.models import AnswerResult, RetrievedChunk


class FakeAgentRetrievalService:
    def retrieve(self, query: str, top_k: int, *, mode: str):
        return type(
            "Result",
            (),
            {
                "payload": {
                    "query": query,
                    "contexts": [
                        {
                            "chunk_id": "c1",
                            "document_id": "d1",
                            "text": "evidence",
                            "score": 1.0,
                            "metadata": {},
                        }
                    ],
                },
                "runtime_metadata": {"retrieval_rewrite": {"answer_notice_required": True}},
            },
        )()


class FakeQueryRouter:
    def query(self, query: str, top_k: int, mode: str):
        return AnswerResult(
            answer=f"answer: {query}",
            contexts=[RetrievedChunk("c1", "d1", "text", 0.7)],
            metadata={"mode": mode},
        )


class FakeServices:
    agent_retrieval_service = FakeAgentRetrievalService()
    query_router = FakeQueryRouter()


def test_retrieve_writes_model_json_to_stdout_only(capsys) -> None:
    exit_code = mcrag.main(
        ["retrieve", "--query", "hello", "--mode", "standard", "--top-n", "2", "--json"],
        services_factory=lambda: FakeServices(),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert list(payload.keys()) == ["query", "contexts"]
    assert "retrieval_rewrite" not in payload
    assert "mode" not in payload


def test_answer_uses_answer_included_path(capsys) -> None:
    exit_code = mcrag.main(
        ["answer", "--query", "hello", "--mode", "discorag", "--top-n", "2", "--json"],
        services_factory=lambda: FakeServices(),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["answer"] == "answer: hello"
    assert payload["metadata"] == {"mode": "discorag"}


def test_setup_error_goes_to_stderr(capsys) -> None:
    def broken_factory():
        raise RuntimeError("missing provider config")

    exit_code = mcrag.main(
        ["retrieve", "--query", "hello", "--mode", "standard", "--top-n", "2", "--json"],
        services_factory=broken_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "setup error:" in captured.err
    assert "missing provider config" in captured.err
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/cli/test_mcrag_cli.py -q
```

Expected: FAIL because CLI package does not exist.

- [ ] **Step 3: Add console script**

Modify `pyproject.toml`:

```toml
[project.scripts]
mcrag = "ragflow_lite.cli.mcrag:main"
```

- [ ] **Step 4: Implement CLI**

Create `src/ragflow_lite/cli/__init__.py`:

```python
"""Command-line interfaces for MicroRAG."""
```

Create `src/ragflow_lite/cli/mcrag.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Sequence

from ragflow_lite.api.deps.providers import AppServices, build_services
from ragflow_lite.config import Settings
from ragflow_lite.domain.models import AnswerResult


def _services_factory() -> AppServices:
    settings = Settings.default()
    settings.ensure_directories()
    return build_services(settings)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcrag")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("retrieve", "answer"):
        command = subparsers.add_parser(name)
        command.add_argument("--query", required=True)
        command.add_argument("--mode", choices=("standard", "discorag"), default="standard")
        command.add_argument("--top-n", type=int, default=6)
        command.add_argument("--json", action="store_true", required=True)
    return parser


def _answer_payload(result: AnswerResult) -> dict[str, object]:
    return {
        "answer": result.answer,
        "contexts": [
            {
                "chunk_id": context.chunk_id,
                "document_id": context.document_id,
                "text": context.text,
                "score": context.score,
                "metadata": dict(context.metadata),
            }
            for context in result.contexts
        ],
        "metadata": dict(result.metadata),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    services_factory: Callable[[], AppServices] = _services_factory,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        services = services_factory()
        if args.command == "retrieve":
            if services.agent_retrieval_service is None:
                raise RuntimeError("agent retrieval service is not configured")
            result = services.agent_retrieval_service.retrieve(
                args.query,
                args.top_n,
                mode=args.mode,
            )
            print(json.dumps(result.payload, ensure_ascii=False), flush=True)
            return 0
        if args.command == "answer":
            answer_result = services.query_router.query(
                args.query,
                args.top_n,
                mode=args.mode,
            )
            print(json.dumps(_answer_payload(answer_result), ensure_ascii=False), flush=True)
            return 0
        parser.error(f"unsupported command: {args.command}")
        return 2
    except RuntimeError as exc:
        print(f"setup error: {exc}", file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        print(f"mcrag error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify CLI tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/cli/test_mcrag_cli.py -q
```

Expected: PASS.

- [ ] **Step 6: Verify installed-module invocation**

Run:

```bash
rtk .venv/bin/python -m ragflow_lite.cli.mcrag --help
```

Expected: output contains `retrieve` and `answer`.

- [ ] **Step 7: Commit**

```bash
rtk git add pyproject.toml src/ragflow_lite/cli tests/unit/cli/test_mcrag_cli.py
rtk git commit -m "feat: add mcrag cli"
```

## Task 6: Add Claude Code-Managed MicroRAG Skill

Purpose: give the external agent deterministic instructions for using `mcrag` without MicroRAG reimplementing skill storage.

**Files:**

- Create: `.claude/skills/microrag-search/SKILL.md`

- [ ] **Step 1: Create skill file**

Create `.claude/skills/microrag-search/SKILL.md`:

```markdown
---
name: microrag-search
description: Use MicroRAG local retrieval evidence when answering questions about indexed local documents or when the user asks to search MicroRAG.
---

# MicroRAG Search

Use the local `mcrag` command to retrieve evidence from MicroRAG.

For normal retrieval:

```bash
mcrag retrieve --query "<question>" --mode standard --top-n 6 --json
```

For DiscoRAG retrieval when the user asks for deeper evidence organization, multi-step reasoning over retrieved chunks, or comparison across evidence:

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

The command prints model-facing JSON to stdout. Use `query`, `contexts`, and optional `blueprint` as evidence. Do not treat stderr diagnostics as evidence.

If `mcrag retrieve` fails with `setup error:`, tell the user MicroRAG is not ready and report the setup error in product terms. Do not invent evidence.

Use `mcrag answer` only when the user explicitly asks for MicroRAG's direct grounded answer or when debugging the MicroRAG answer path:

```bash
mcrag answer --query "<question>" --mode standard --top-n 6 --json
mcrag answer --query "<question>" --mode discorag --top-n 6 --json
```
```

- [ ] **Step 2: Verify skill path shape**

Run:

```bash
rtk sed -n '1,120p' .claude/skills/microrag-search/SKILL.md
```

Expected:

- File exists at `skill-name/SKILL.md`.
- Text references `mcrag retrieve` and `mcrag answer`.
- Text does not mention MCP.

- [ ] **Step 3: Commit**

```bash
rtk git add .claude/skills/microrag-search/SKILL.md
rtk git commit -m "feat: add MicroRAG search skill"
```

## Task 7: Add Local Agent Session Metadata Store

Purpose: persist UI-facing session metadata while keeping Claude Code JSONL transcripts authoritative.

**Files:**

- Create: `src/ragflow_lite/infrastructure/agent/__init__.py`
- Create: `src/ragflow_lite/infrastructure/agent/session_store.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/infrastructure/test_agent_session_store.py`

- [ ] **Step 1: Write failing session store tests**

Create `tests/unit/infrastructure/test_agent_session_store.py`:

```python
from pathlib import Path

from ragflow_lite.infrastructure.agent.session_store import AgentSessionStore


def test_session_store_creates_and_lists_metadata(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")

    session = store.create_session(
        title="New chat",
        claude_session_id="claude-1",
        transcript_path="/internal/transcript.jsonl",
        runtime_cwd="/internal/cwd",
    )

    sessions = store.list_sessions()

    assert sessions[0].id == session.id
    assert sessions[0].title == "New chat"
    assert sessions[0].claude_session_id == "claude-1"
    assert sessions[0].transcript_path == "/internal/transcript.jsonl"
    assert sessions[0].runtime_cwd == "/internal/cwd"


def test_session_store_does_not_store_messages(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "agent_sessions.sqlite3")
    store.create_session(
        title="New chat",
        claude_session_id="claude-1",
        transcript_path="/internal/transcript.jsonl",
        runtime_cwd="/internal/cwd",
    )

    columns = store.debug_columns("agent_sessions")

    assert "messages" not in columns
    assert "conversation" not in columns
    assert "transcript_json" not in columns
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_agent_session_store.py -q
```

Expected: FAIL because session store does not exist.

- [ ] **Step 3: Implement SQLite metadata store**

Create `src/ragflow_lite/infrastructure/agent/session_store.py`:

```python
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class AgentSessionMetadata:
    id: str
    title: str
    claude_session_id: str
    transcript_path: str
    runtime_cwd: str
    created_at: str
    updated_at: str
    last_error: str | None
    ui_metadata_json: str


class AgentSessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    claude_session_id TEXT NOT NULL,
                    transcript_path TEXT NOT NULL,
                    runtime_cwd TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT,
                    ui_metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

    def create_session(
        self,
        *,
        title: str,
        claude_session_id: str,
        transcript_path: str,
        runtime_cwd: str,
    ) -> AgentSessionMetadata:
        timestamp = _now()
        session = AgentSessionMetadata(
            id=str(uuid.uuid4()),
            title=title,
            claude_session_id=claude_session_id,
            transcript_path=transcript_path,
            runtime_cwd=runtime_cwd,
            created_at=timestamp,
            updated_at=timestamp,
            last_error=None,
            ui_metadata_json="{}",
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_sessions (
                    id, title, claude_session_id, transcript_path, runtime_cwd,
                    created_at, updated_at, last_error, ui_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.title,
                    session.claude_session_id,
                    session.transcript_path,
                    session.runtime_cwd,
                    session.created_at,
                    session.updated_at,
                    session.last_error,
                    session.ui_metadata_json,
                ),
            )
        return session

    def list_sessions(self) -> list[AgentSessionMetadata]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [AgentSessionMetadata(**dict(row)) for row in rows]

    def get_session(self, session_id: str) -> AgentSessionMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentSessionMetadata(**dict(row))

    def mark_error(self, session_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent_sessions
                SET last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, _now(), session_id),
            )

    def debug_columns(self, table: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        return [str(row["name"]) for row in rows]
```

Create `src/ragflow_lite/infrastructure/agent/__init__.py`:

```python
from ragflow_lite.infrastructure.agent.session_store import (
    AgentSessionMetadata,
    AgentSessionStore,
)

__all__ = ["AgentSessionMetadata", "AgentSessionStore"]
```

Wire `AgentSessionStore(settings.local_index_dir / "agent_sessions.sqlite3")` into `AppServices`.

- [ ] **Step 4: Verify tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_agent_session_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/ragflow_lite/infrastructure/agent src/ragflow_lite/api/deps/providers.py tests/unit/infrastructure/test_agent_session_store.py
rtk git commit -m "feat: add local agent session metadata store"
```

## Task 8: Add ACP Client Protocol And Redaction Boundary

Purpose: start an ACP stdio process, exchange minimal JSON-RPC/NDJSON messages, and keep raw runtime fields backend-only before any UI route consumes them.

**Files:**

- Create: `src/ragflow_lite/infrastructure/agent/acp_client.py`
- Modify: `src/ragflow_lite/infrastructure/agent/__init__.py`
- Test: `tests/unit/infrastructure/test_acp_client_redaction.py`

- [ ] **Step 1: Write failing protocol and redaction tests**

Create `tests/unit/infrastructure/test_acp_client_redaction.py`:

```python
import io
import json

from ragflow_lite.infrastructure.agent.acp_client import (
    AcpClient,
    AcpRuntimeConfig,
    redact_acp_error,
    redact_acp_event,
)


def test_redact_acp_event_removes_agent_info_and_runtime_fields() -> None:
    event = {
        "agentInfo": {"name": "claude-code", "title": "Claude Code"},
        "cwd": "/home/xia/ragflow-lite/参考项目/claude-code",
        "transcript_path": "/tmp/session.jsonl",
        "_meta": {"claudeCode": {"promptQueueing": True}},
        "message": "ready",
    }

    redacted = redact_acp_event(event)

    assert redacted == {"message": "ready"}


def test_redact_acp_error_rewrites_brand_and_paths() -> None:
    message = "Claude Code failed in /home/xia/ragflow-lite/参考项目/claude-code with claude-code"

    redacted = redact_acp_error(message)

    assert redacted == "MicroRAG agent runtime failed."


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            "\n".join(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {
                                "agentInfo": {
                                    "name": "claude-code",
                                    "title": "Claude Code",
                                },
                                "sessionId": "claude-session-1",
                                "transcript_path": "/internal/transcript.jsonl",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "result": {
                                "sessionId": "claude-session-1",
                                "transcript_path": "/internal/transcript.jsonl",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "result": {"content": "answer"},
                        }
                    ),
                ]
            )
            + "\n"
        )
        self.stderr = io.StringIO("Claude Code stderr")


def test_acp_client_initialize_redacts_agent_info() -> None:
    process = FakeProcess()
    client = AcpClient(
        AcpRuntimeConfig(command="agent", args=["--acp"], cwd="/runtime"),
        process_factory=lambda command, args, cwd: process,
    )
    client.start()

    result = client.initialize()

    assert result == {"sessionId": "claude-session-1"}
    written = process.stdin.getvalue()
    assert '"method": "initialize"' in written
    assert "Claude Code" not in json.dumps(result)


def test_acp_client_send_message_uses_jsonrpc_and_redacts_response() -> None:
    process = FakeProcess()
    client = AcpClient(
        AcpRuntimeConfig(command="agent", args=["--acp"], cwd="/runtime"),
        process_factory=lambda command, args, cwd: process,
    )
    client.start()
    client.initialize()
    client.resume_session("claude-session-1")

    result = client.send_message("claude-session-1", "hello")

    assert result == {"content": "answer"}
    written = process.stdin.getvalue()
    assert '"method": "session/load"' in written
    assert '"method": "session/prompt"' in written
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py -q
```

Expected: FAIL because ACP client module does not exist.

- [ ] **Step 3: Implement redaction helpers and ACP JSON-RPC adapter**

Create `src/ragflow_lite/infrastructure/agent/acp_client.py`:

```python
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

BACKEND_ONLY_KEYS = {
    "agentInfo",
    "cwd",
    "runtime_cwd",
    "command",
    "args",
    "transcript_path",
    "_meta",
    "stderr",
}


def redact_acp_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in event.items()
        if key not in BACKEND_ONLY_KEYS
    }


def redact_acp_error(message: str) -> str:
    if (
        "Claude Code" in message
        or "claude-code" in message
        or "参考项目/claude-code" in message
        or "transcript" in message
    ):
        return "MicroRAG agent runtime failed."
    return message


@dataclass(slots=True)
class AcpRuntimeConfig:
    command: str
    args: list[str]
    cwd: str


ProcessFactory = Callable[[str, list[str], str], object]


def _default_process_factory(command: str, args: list[str], cwd: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [command, *args],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class AcpClient:
    def __init__(
        self,
        config: AcpRuntimeConfig,
        *,
        process_factory: ProcessFactory = _default_process_factory,
    ) -> None:
        self.config = config
        self.process_factory = process_factory
        self.process: object | None = None
        self._next_id = 1

    def start(self) -> None:
        self.process = self.process_factory(
            self.config.command,
            list(self.config.args),
            self.config.cwd,
        )

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.process is None:
            raise RuntimeError("ACP process is not started")
        request_id = self._next_id
        self._next_id += 1
        stdin = getattr(self.process, "stdin")
        stdout = getattr(self.process, "stdout")
        stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        flush = getattr(stdin, "flush", None)
        if callable(flush):
            flush()
        line = stdout.readline()
        if not line:
            raise RuntimeError("ACP runtime closed stdout")
        response = json.loads(line)
        if "error" in response:
            message = response["error"].get("message", "ACP runtime failed")
            raise RuntimeError(redact_acp_error(str(message)))
        result = response.get("result", {})
        if not isinstance(result, dict):
            return {}
        return redact_acp_event(result)

    def initialize(self) -> dict[str, Any]:
        return self._request("initialize", {})

    def resume_session(self, claude_session_id: str) -> dict[str, Any]:
        return self._request("session/load", {"sessionId": claude_session_id})

    def send_message(self, claude_session_id: str, message: str) -> dict[str, Any]:
        return self._request(
            "session/prompt",
            {"sessionId": claude_session_id, "prompt": message},
        )
```

Update `src/ragflow_lite/infrastructure/agent/__init__.py` exports.

- [ ] **Step 4: Verify tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add src/ragflow_lite/infrastructure/agent/acp_client.py src/ragflow_lite/infrastructure/agent/__init__.py tests/unit/infrastructure/test_acp_client_redaction.py
rtk git commit -m "feat: add ACP redaction boundary"
```

## Task 9: Add Agent API Routes

Purpose: provide MicroRAG-owned endpoints for session list, new session, resume metadata, send message, and recoverable runtime errors.

**Files:**

- Create: `src/ragflow_lite/api/schemas/agent.py`
- Create: `src/ragflow_lite/api/routes/agent.py`
- Modify: `src/ragflow_lite/app.py`
- Test: `tests/unit/api/test_agent_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/unit/api/test_agent_routes.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ragflow_lite.api.routes.agent import router


class FakeSession:
    id = "ui-session-1"
    title = "New chat"
    claude_session_id = "claude-session-1"
    transcript_path = "/internal/transcript.jsonl"
    runtime_cwd = "/internal/cwd"
    created_at = "2026-05-14T00:00:00+00:00"
    updated_at = "2026-05-14T00:00:00+00:00"
    last_error = None
    ui_metadata_json = "{}"


class FakeStore:
    def list_sessions(self):
        return [FakeSession()]

    def create_session(self, *, title, claude_session_id, transcript_path, runtime_cwd):
        return FakeSession()

    def get_session(self, session_id):
        if session_id == "ui-session-1":
            return FakeSession()
        return None

    def mark_error(self, session_id, error):
        self.last_marked_error = (session_id, error)


class FakeAcpClient:
    def __init__(self):
        self.started = False
        self.resumed_sessions = []
        self.messages = []

    def start(self):
        self.started = True

    def initialize(self):
        return {"sessionId": "claude-session-1"}

    def resume_session(self, claude_session_id):
        self.resumed_sessions.append(claude_session_id)
        return {"sessionId": claude_session_id}

    def send_message(self, claude_session_id, message):
        self.messages.append((claude_session_id, message))
        return {"content": "assistant answer"}


class FakeServices:
    agent_session_store = FakeStore()
    acp_client = FakeAcpClient()


def _client() -> TestClient:
    app = FastAPI()
    app.state.services = FakeServices()
    app.include_router(router, prefix="/api/v0/agent")
    return TestClient(app)


def test_list_sessions_redacts_backend_only_fields() -> None:
    response = _client().get("/api/v0/agent/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["sessions"][0] == {
        "id": "ui-session-1",
        "title": "New chat",
        "created_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
        "last_error": None,
    }
    rendered = response.text
    assert "Claude Code" not in rendered
    assert "claude-code" not in rendered
    assert "transcript" not in rendered
    assert "/internal/cwd" not in rendered


def test_create_session_returns_ui_metadata_only() -> None:
    response = _client().post("/api/v0/agent/sessions", json={"title": "New chat"})

    assert response.status_code == 200
    assert "claude_session_id" not in response.text
    assert "transcript_path" not in response.text


def test_resume_session_attaches_by_ui_session_id_without_leaking_transcript() -> None:
    response = _client().post("/api/v0/agent/sessions/ui-session-1/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "resumed"
    assert "transcript_path" not in response.text
    assert "Claude Code" not in response.text


def test_send_message_uses_resumed_session_and_returns_redacted_content() -> None:
    response = _client().post(
        "/api/v0/agent/sessions/ui-session-1/messages",
        json={"message": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "ui-session-1",
        "status": "completed",
        "message": "assistant answer",
    }
    assert "claude-session-1" not in response.text
    assert "Claude Code" not in response.text
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_agent_routes.py -q
```

Expected: FAIL because route module does not exist.

- [ ] **Step 3: Implement schemas**

Create `src/ragflow_lite/api/schemas/agent.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentSessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    last_error: str | None = None


class AgentSessionListResponse(BaseModel):
    sessions: list[AgentSessionSummary]


class CreateAgentSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="New chat", min_length=1)


class SendAgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)


class SendAgentMessageResponse(BaseModel):
    session_id: str
    status: str
    message: str | None = None


class ResumeAgentSessionResponse(BaseModel):
    session_id: str
    status: str
    last_error: str | None = None
```

- [ ] **Step 4: Implement routes**

Create `src/ragflow_lite/api/routes/agent.py`:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from ragflow_lite.api.schemas.agent import (
    AgentSessionListResponse,
    AgentSessionSummary,
    CreateAgentSessionRequest,
    ResumeAgentSessionResponse,
    SendAgentMessageRequest,
    SendAgentMessageResponse,
)

router = APIRouter()


def _summary(session: object) -> AgentSessionSummary:
    return AgentSessionSummary(
        id=str(getattr(session, "id")),
        title=str(getattr(session, "title")),
        created_at=str(getattr(session, "created_at")),
        updated_at=str(getattr(session, "updated_at")),
        last_error=getattr(session, "last_error"),
    )


@router.get("/sessions", response_model=AgentSessionListResponse)
def list_agent_sessions(request: Request) -> AgentSessionListResponse:
    sessions = request.app.state.services.agent_session_store.list_sessions()
    return AgentSessionListResponse(sessions=[_summary(session) for session in sessions])


@router.post("/sessions", response_model=AgentSessionSummary)
def create_agent_session(
    request: Request,
    payload: CreateAgentSessionRequest,
) -> AgentSessionSummary:
    acp_client = request.app.state.services.acp_client
    acp_client.start()
    init_result = acp_client.initialize()
    session = request.app.state.services.agent_session_store.create_session(
        title=payload.title,
        claude_session_id=str(init_result.get("sessionId") or uuid.uuid4()),
        transcript_path=str(init_result.get("transcript_path") or "pending"),
        runtime_cwd="pending",
    )
    return _summary(session)


@router.post("/sessions/{session_id}/resume", response_model=ResumeAgentSessionResponse)
def resume_agent_session(
    request: Request,
    session_id: str,
) -> ResumeAgentSessionResponse:
    store = request.app.state.services.agent_session_store
    session = store.get_session(session_id)
    if session is None:
        return ResumeAgentSessionResponse(
            session_id=session_id,
            status="not_found",
            last_error="Session not found.",
        )
    try:
        request.app.state.services.acp_client.resume_session(session.claude_session_id)
    except RuntimeError as exc:
        error = str(exc)
        store.mark_error(session_id, error)
        return ResumeAgentSessionResponse(
            session_id=session_id,
            status="recoverable_error",
            last_error=error,
        )
    return ResumeAgentSessionResponse(session_id=session_id, status="resumed")


@router.post("/sessions/{session_id}/messages", response_model=SendAgentMessageResponse)
def send_agent_message(
    request: Request,
    session_id: str,
    payload: SendAgentMessageRequest,
) -> SendAgentMessageResponse:
    store = request.app.state.services.agent_session_store
    session = store.get_session(session_id)
    if session is None:
        return SendAgentMessageResponse(
            session_id=session_id,
            status="not_found",
            message="Session not found.",
        )
    try:
        request.app.state.services.acp_client.resume_session(session.claude_session_id)
        result = request.app.state.services.acp_client.send_message(
            session.claude_session_id,
            payload.message,
        )
    except RuntimeError as exc:
        error = str(exc)
        store.mark_error(session_id, error)
        return SendAgentMessageResponse(
            session_id=session_id,
            status="recoverable_error",
            message=error,
        )
    return SendAgentMessageResponse(
        session_id=session_id,
        status="completed",
        message=str(result.get("content") or ""),
    )
```

Modify `src/ragflow_lite/app.py`:

```python
from ragflow_lite.api.routes.agent import router as agent_router
...
app.include_router(agent_router, prefix=f"{resolved_settings.api_prefix}/agent")
```

This task intentionally supports a single synchronous send-message round trip. Streaming can be layered on later, but new session, resume, recoverable transcript/session failure, and redacted message response are first-stage requirements.

- [ ] **Step 5: Verify route tests**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_agent_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add src/ragflow_lite/api/schemas/agent.py src/ragflow_lite/api/routes/agent.py src/ragflow_lite/app.py tests/unit/api/test_agent_routes.py
rtk git commit -m "feat: add MicroRAG agent session routes"
```

## Task 10: Add Minimal Python-Served Demo Shell

Purpose: provide first-stage UI without introducing Node/Vite.

**Files:**

- Create: `src/ragflow_lite/api/routes/ui.py`
- Create: `src/ragflow_lite/static/agent-shell.css`
- Create: `src/ragflow_lite/static/agent-shell.js`
- Modify: `src/ragflow_lite/app.py`
- Modify: `pyproject.toml`
- Test: `tests/integration/api/test_ui_shell.py`

- [ ] **Step 1: Write failing UI shell test**

Create `tests/integration/api/test_ui_shell.py`:

```python
from fastapi.testclient import TestClient


def test_agent_shell_does_not_render_runtime_branding(client: TestClient) -> None:
    response = client.get("/agent")

    assert response.status_code == 200
    text = response.text
    assert "MicroRAG" in text
    assert "Claude Code" not in text
    assert "claude-code" not in text
    assert "transcript_path" not in text
    assert "runtime_cwd" not in text
    assert "stderr" not in text
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/integration/api/test_ui_shell.py -q
```

Expected: FAIL because `/agent` does not exist.

- [ ] **Step 3: Implement UI route**

Create `src/ragflow_lite/api/routes/ui.py`:

```python
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/agent", response_class=HTMLResponse)
def agent_shell() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MicroRAG Agent</title>
  <link rel="stylesheet" href="/static/agent-shell.css">
</head>
<body>
  <main class="shell">
    <aside class="sessions">
      <header>
        <h1>MicroRAG</h1>
        <button id="new-session" type="button">New</button>
      </header>
      <div id="session-list"></div>
    </aside>
    <section class="chat" aria-label="MicroRAG agent chat">
      <div id="messages" class="messages"></div>
      <div id="runtime-status" class="status"></div>
      <form id="composer">
        <input id="message-input" name="message" autocomplete="off" required>
        <button type="submit">Send</button>
      </form>
    </section>
  </main>
  <script src="/static/agent-shell.js"></script>
</body>
</html>"""
```

Create `src/ragflow_lite/static/agent-shell.css`:

```css
body {
  margin: 0;
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f7f7f5;
  color: #1f2933;
}

.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(220px, 280px) 1fr;
}

.sessions {
  border-right: 1px solid #d8d8d2;
  padding: 16px;
  background: #ffffff;
}

.sessions header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sessions h1 {
  margin: 0;
  font-size: 20px;
}

.chat {
  display: grid;
  grid-template-rows: 1fr auto auto;
  min-width: 0;
}

.messages {
  padding: 24px;
  overflow: auto;
}

.status {
  min-height: 24px;
  padding: 0 24px 12px;
  color: #52616b;
}

#composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 16px 24px 24px;
}

input,
button {
  font: inherit;
}
```

Create `src/ragflow_lite/static/agent-shell.js`:

```javascript
async function refreshSessions() {
  const response = await fetch("/api/v0/agent/sessions");
  const data = await response.json();
  const list = document.querySelector("#session-list");
  list.textContent = "";
  for (const session of data.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = session.title;
    button.dataset.sessionId = session.id;
    list.append(button);
  }
}

document.querySelector("#new-session").addEventListener("click", async () => {
  await fetch("/api/v0/agent/sessions", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({title: "New chat"})
  });
  await refreshSessions();
});

document.querySelector("#composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#message-input");
  document.querySelector("#runtime-status").textContent = "Sending...";
  input.value = "";
});

refreshSessions().catch(() => {
  document.querySelector("#runtime-status").textContent = "MicroRAG agent is not ready.";
});
```

Modify `src/ragflow_lite/app.py`:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from ragflow_lite.api.routes.ui import router as ui_router
...
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.include_router(ui_router)
```

Modify `pyproject.toml`:

```toml
[tool.setuptools.package-data]
ragflow_lite = ["static/*.css", "static/*.js"]
```

- [ ] **Step 4: Verify UI shell**

Run:

```bash
rtk .venv/bin/python -m pytest tests/integration/api/test_ui_shell.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add pyproject.toml src/ragflow_lite/api/routes/ui.py src/ragflow_lite/static tests/integration/api/test_ui_shell.py src/ragflow_lite/app.py
rtk git commit -m "feat: add minimal MicroRAG agent shell"
```

## Task 11: Verify ACP Session Resume And UI Send Flow

Purpose: prove the route layer uses the ACP client for new sessions, resume, and single-turn send without exposing backend-only runtime fields.

**Files:**

- Modify: `src/ragflow_lite/api/routes/agent.py`
- Test: `tests/unit/api/test_agent_routes.py`

- [ ] **Step 1: Add recoverable resume failure test**

Add to `tests/unit/api/test_agent_routes.py`:

```python
def test_resume_session_reports_recoverable_runtime_error() -> None:
    class FailingAcpClient(FakeAcpClient):
        def resume_session(self, claude_session_id):
            raise RuntimeError("MicroRAG agent runtime failed.")

    class Services(FakeServices):
        acp_client = FailingAcpClient()

    app = FastAPI()
    app.state.services = Services()
    app.include_router(router, prefix="/api/v0/agent")
    client = TestClient(app)

    response = client.post("/api/v0/agent/sessions/ui-session-1/resume")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "ui-session-1",
        "status": "recoverable_error",
        "last_error": "MicroRAG agent runtime failed.",
    }
    assert "Claude Code" not in response.text
    assert "claude-code" not in response.text
```

- [ ] **Step 2: Add route-to-ACP call assertions**

Add to `tests/unit/api/test_agent_routes.py`:

```python
def test_create_session_starts_and_initializes_acp_runtime() -> None:
    client = _client()

    response = client.post("/api/v0/agent/sessions", json={"title": "New chat"})

    assert response.status_code == 200
    assert client.app.state.services.acp_client.started is True
    assert "claude-session-1" not in response.text
    assert "transcript" not in response.text


def test_send_message_resumes_before_prompting_acp_runtime() -> None:
    client = _client()

    response = client.post(
        "/api/v0/agent/sessions/ui-session-1/messages",
        json={"message": "hello"},
    )

    acp_client = client.app.state.services.acp_client
    assert response.status_code == 200
    assert acp_client.resumed_sessions == ["claude-session-1"]
    assert acp_client.messages == [("claude-session-1", "hello")]
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/api/test_agent_routes.py -q
```

Expected: FAIL until Task 9 route implementation calls the ACP client for create/resume/send.

- [ ] **Step 4: Make route behavior match the tests**

Update `src/ragflow_lite/api/routes/agent.py` if Task 9 did not already do so:

- `POST /sessions` calls `acp_client.start()` and `acp_client.initialize()`.
- `POST /sessions/{session_id}/resume` loads UI metadata by `session_id`, calls `acp_client.resume_session(session.claude_session_id)`, and returns `status="resumed"` or `status="recoverable_error"`.
- `POST /sessions/{session_id}/messages` loads UI metadata, resumes the stored Claude session, calls `acp_client.send_message(...)`, and returns only MicroRAG-owned `session_id`, `status`, and assistant `message`.
- All raw `claude_session_id`, `transcript_path`, `runtime_cwd`, raw ACP errors, and external runtime branding stay out of response bodies.

- [ ] **Step 5: Verify adapter and routes**

Run:

```bash
rtk .venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py tests/unit/api/test_agent_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add src/ragflow_lite/api/routes/agent.py tests/unit/api/test_agent_routes.py
rtk git commit -m "feat: wire agent routes to ACP sessions"
```

## Task 12: Nested Git Preflight Before Cleanup

Purpose: verify the vendored reference runtime Git shape before deleting or moving repository metadata.

**Files:**

- No code changes in this task unless the user explicitly approves cleanup after the preflight result.

- [ ] **Step 1: Run nested Git preflight**

Run:

```bash
rtk git -C '参考项目/claude-code' status --short --branch
rtk git -C '参考项目/claude-code' submodule status --recursive
rtk git -C '参考项目/claude-code' ls-files --stage | awk '$1=="160000"'
find '参考项目/claude-code' -name .git -o -name .gitmodules
```

Expected:

- Report whether `参考项目/claude-code/.git` is the only nested Git metadata.
- Report whether submodules or gitlinks exist.
- Use native `find` here because this repo's `rtk find` wrapper does not support
  compound predicates such as `-name .git -o -name .gitmodules`.

- [ ] **Step 2: Stop for user confirmation**

Do not delete `.git`, `.gitmodules`, or gitlink-like paths in this task. Report the preflight result and ask for explicit cleanup approval if cleanup is still desired.

## Task 13: Update Active Contracts

Purpose: update nearest source-of-truth docs only after behavior lands.

**Files:**

- Modify: `src/ragflow_lite/application/CONTRACTS.md`
- Modify: `src/ragflow_lite/api/CONTRACTS.md`
- Modify: `src/ragflow_lite/infrastructure/CONTRACTS.md`

- [ ] **Step 1: Update application contract**

Add concise bullets to `src/ragflow_lite/application/CONTRACTS.md`:

```markdown
- `AgentRetrievalService` is retrieval-only: it builds answer-facing requests for
  `standard` and `discorag`, serializes model-facing evidence, and must not call
  `Answerer.answer()`.
- Standard model-facing contexts use U-shaped score ordering. DiscoRAG
  model-facing contexts use score-descending ordering with the final blueprint at
  the payload tail.
- Retrieval rewrite low-quality state remains runtime/UI metadata and must not be
  inserted into answer prompts.
```

- [ ] **Step 2: Update API contract**

Add concise bullets to `src/ragflow_lite/api/CONTRACTS.md`:

```markdown
- `/api/v0/queries` remains answer-producing.
- `/api/v0/agent/**` exposes MicroRAG-owned session/message UI metadata only.
  Raw ACP fields, transcript paths, runtime cwd, stderr, command lines, and
  external runtime branding are backend-only.
```

- [ ] **Step 3: Update infrastructure contract**

Add concise bullets to `src/ragflow_lite/infrastructure/CONTRACTS.md`:

```markdown
- ACP runtime integration is a process boundary. UI-visible data must pass
  through MicroRAG redaction before leaving infrastructure.
- `AgentSessionStore` stores local UI metadata only. Claude Code JSONL
  transcripts remain the conversation source of truth.
```

- [ ] **Step 4: Verify docs have no placeholders**

Run:

```bash
rtk rg -n "TBD|TODO|Claude Code|claude-code|Retrieval rewrite notice" src/ragflow_lite/application/CONTRACTS.md src/ragflow_lite/api/CONTRACTS.md src/ragflow_lite/infrastructure/CONTRACTS.md
```

Expected:

- No `TBD` or `TODO`.
- Any `Claude Code` mention is either absent or explicitly scoped to backend-only transcript/runtime ownership. If the active contract can avoid the brand name, prefer avoiding it.
- No contract says retrieval rewrite notices are inserted into prompts.

- [ ] **Step 5: Commit**

```bash
rtk git add src/ragflow_lite/application/CONTRACTS.md src/ragflow_lite/api/CONTRACTS.md src/ragflow_lite/infrastructure/CONTRACTS.md
rtk git commit -m "docs: update agent demo shell contracts"
```

## Task 14: Full Focused Verification

Purpose: verify the first-stage demo shell behavior end to end without claiming live provider coverage that was not run.

- [ ] **Step 1: Run focused unit suite**

Run:

```bash
rtk .venv/bin/python -m pytest \
  tests/unit/application/test_model_facing_retrieval.py \
  tests/unit/application/test_agent_retrieval_service.py \
  tests/unit/application/test_query_service.py \
  tests/unit/application/test_discorag_query_service.py \
  tests/unit/infrastructure/test_input_formatting.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_agent_session_store.py \
  tests/unit/infrastructure/test_acp_client_redaction.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/unit/api/test_v0_routes.py \
  tests/unit/api/test_agent_routes.py -q
```

Expected: PASS.

- [ ] **Step 2: Run UI integration smoke**

Run:

```bash
rtk .venv/bin/python -m pytest tests/integration/api/test_ui_shell.py -q
```

Expected: PASS.

- [ ] **Step 3: Run CLI help smoke**

Run:

```bash
rtk .venv/bin/python -m ragflow_lite.cli.mcrag --help
```

Expected: output contains `retrieve` and `answer`.

- [ ] **Step 4: Run visible leak scan**

Run:

```bash
rtk rg -n "Claude Code|claude-code|transcript_path|runtime_cwd|raw stderr|agentInfo" src/ragflow_lite tests .claude/skills/microrag-search/SKILL.md
```

Expected:

- No UI route/static file/test fixture accidentally renders forbidden runtime details.
- Backend-only redaction tests may contain forbidden strings as test inputs.
- The skill file should not mention the underlying runtime brand.

- [ ] **Step 5: Run formatting/static checks if available**

Run:

```bash
rtk .venv/bin/python -m ruff check src tests
rtk .venv/bin/python -m basedpyright
```

Expected: PASS. If existing unrelated type/style failures appear, record them separately and do not claim full static validation.

- [ ] **Step 6: Commit verification fixes**

If verification required fixes:

```bash
rtk git add <changed-files>
rtk git commit -m "test: verify agent demo shell"
```

If no fixes were needed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage:
  - ACP stdio boundary: Tasks 8, 9, 11.
  - Claude Code transcript as source of truth: Tasks 7, 13.
  - resume/session attach and recoverable transcript/session failure: Tasks 9, 11.
  - Skill managed by Claude Code: Task 6.
  - `mcrag retrieve` and `mcrag answer`: Tasks 3, 5.
  - standard and DiscoRAG retrieval JSON: Tasks 1, 3.
  - no MCP: Implementation Notes and Task 6 verification.
  - answer layer preserved: Tasks 2, 4, 5, 14.
  - low-quality retrieval warning outside prompt: Task 4.
  - UI redaction: Tasks 8, 9, 10, 11, 14.
  - nested Git cleanup preflight: Task 12.
- Placeholder scan:
  - No `TBD`, `TODO`, or open-ended implementation placeholders are intentional in this plan.
- Type consistency:
  - `AgentRetrievalService.retrieve(query, top_k, mode=...)` returns `AgentRetrievalResult`.
  - `QueryService.build_answer_request()` and `DiscoRAGQueryService.build_answer_request()` both return `AnswerRequest`.
  - CLI calls `services.agent_retrieval_service.retrieve()` for `retrieve` and `services.query_router.query()` for `answer`.
