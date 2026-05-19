# MiniRAG Gated Retrieval Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic gated CoT grounding enhancement inside MiniRAG retrieval, with cached initial-candidate fallback and explicit observability, without adding public API knobs or a multi-query planner.

**Architecture:** Keep `/queries`, `QueryModeRouter`, `DiscoRAGQueryService`, and answerers mostly unchanged. Add typed domain models plus a narrow `CoTGroundingRewriter` port, implement deterministic gate/rewrite helpers in the application layer, and let `MiniGraphFirstRetriever` orchestrate one optional rewrite cycle. Infrastructure rewriters generate only `solution_steps`; the existing grounding layer remains responsible for extracting MiniRAG entities, relations, and answer-type keywords.

**Tech Stack:** Python 3.13, dataclasses, Protocol ports, pytest, existing DeepSeek Chat and OpenAI Responses clients, existing MiniRAG/DiscoRAG domain models.

---

Date: 2026-05-11
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-11-minirag-gated-retrieval-rewrite.md](../specs/2026-05-11-minirag-gated-retrieval-rewrite.md)

## File Structure

Files to modify:

- `src/ragflow_lite/domain/models/entities.py`
  - Add `InitialCandidateSnapshot`, `GroundingGateDecision`, `CoTGroundingResult`, `EnrichedGroundingInput`, and `PostRewriteAssessment`.
- `src/ragflow_lite/domain/models/__init__.py`
  - Export the new domain models.
- `src/ragflow_lite/domain/ports/interfaces.py`
  - Add a narrow `CoTGroundingRewriter` protocol.
- `src/ragflow_lite/application/services/retrieval_rewrite.py`
  - Create deterministic gate, enriched input rendering, rewrite metadata helpers, post-rewrite assessment, and result-merge helpers.
- `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
  - Add optional `cot_grounding_rewriter`, run the initial pass once, snapshot it, gate it, optionally rewrite once, and merge enriched results.
- `src/ragflow_lite/application/services/__init__.py`
  - Export application helper symbols only if existing package style requires it.
- `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`
  - Create provider-neutral JSON parsing and validation helpers for `solution_steps`.
- `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`
  - Implement DeepSeek-backed `CoTGroundingRewriter`.
- `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`
  - Implement OpenAI Responses-backed `CoTGroundingRewriter`.
- `src/ragflow_lite/infrastructure/retrievers/__init__.py`
  - Export the new rewriters.
- `src/ragflow_lite/api/deps/providers.py`
  - Wire a DeepSeek CoT rewriter into `MiniGraphFirstRetriever` without exposing any public API field.
- `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
  - Add answer-facing degraded retrieval notice rendering from `AnswerRequest.metadata`.
- `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
  - Add the same degraded retrieval notice rendering.
- `src/ragflow_lite/application/CONTRACTS.md`
  - Update only after behavior and tests land.

Tests to modify or create:

- `tests/unit/domain/test_minirag_topology_models.py`
- `tests/unit/application/test_retrieval_rewrite.py`
- `tests/unit/application/test_mini_graph_first_retriever.py`
- `tests/unit/infrastructure/test_cot_grounding.py`
- `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`
- `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`
- `tests/unit/application/test_discorag_query_service.py`
- `tests/unit/infrastructure/test_deepseek_chat_answerer.py`
- `tests/unit/infrastructure/test_openai_responses_answerer.py`
- `tests/unit/api/test_providers.py`
- `tests/unit/api/test_v0_routes.py`

## Task 0: Baseline Reconnaissance

Purpose: confirm the current code shape before writing behavior changes.

- [ ] **Step 1: Inspect current MiniRAG symbols**

Run:

```bash
cx overview src/ragflow_lite/application/services/mini_graph_first_retriever.py
cx definition --name MiniGraphFirstRetriever --from src/ragflow_lite/application/services/mini_graph_first_retriever.py --all
```

Expected:

- `MiniGraphFirstRetriever.retrieve_context(query, top_k)` owns grounding, graph lookup, auxiliary retrieval, scoring, and selection.
- No rewrite gate or CoT rewriter parameter exists yet.

- [ ] **Step 2: Inspect current domain models and ports**

Run:

```bash
cx definition --name GroundedQuery --from src/ragflow_lite/domain/models/entities.py
cx definition --name TopologyRetrievalResult --from src/ragflow_lite/domain/models/entities.py
cx definition --name GraphFirstSourceSelection --from src/ragflow_lite/domain/models/entities.py
cx definition --name QueryGrounder --from src/ragflow_lite/domain/ports/interfaces.py
```

Expected:

- `GroundedQuery` has `query`, `answer_type_keywords`, `entities_from_query`, and `metadata`.
- `TopologyRetrievalResult` has `query`, `grounded_query`, `chunks`, `paths`, `source_selection`, and `metadata`.
- `QueryGrounder.ground(query)` remains a narrow basic grounding port.

- [ ] **Step 3: Run current focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/infrastructure/test_deepseek_query_grounder.py \
  tests/unit/infrastructure/test_openai_query_grounder.py -q
```

Expected: all selected tests pass before changes.

## Task 1: Add Retrieval Rewrite Domain Models And Port

Purpose: define typed contracts before wiring behavior.

**Files:**

- Modify: `src/ragflow_lite/domain/models/entities.py`
- Modify: `src/ragflow_lite/domain/models/__init__.py`
- Modify: `src/ragflow_lite/domain/ports/interfaces.py`
- Test: `tests/unit/domain/test_minirag_topology_models.py`

- [ ] **Step 1: Add failing domain model tests**

Add to `tests/unit/domain/test_minirag_topology_models.py`:

```python
from ragflow_lite.domain.models import (
    CoTGroundingResult,
    EnrichedGroundingInput,
    GraphFirstSourceSelection,
    GroundingGateDecision,
    GroundedQuery,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
    RetrievedChunk,
)
from ragflow_lite.domain.ports.interfaces import CoTGroundingRewriter


def test_retrieval_rewrite_models_preserve_snapshot_and_status() -> None:
    grounded = GroundedQuery(
        query="What improves MiniRAG recall?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
    )
    chunk = RetrievedChunk(
        chunk_id="chunk_a",
        document_id="doc1",
        text="MiniRAG uses graph evidence.",
        score=1.0,
        metadata={"selected_for_answer": True},
    )
    selection = GraphFirstSourceSelection(
        sources=[],
        final_context_k=2,
        discourse_selection_k=4,
        context_token_budget=None,
        omitted_source_count=0,
    )

    snapshot = InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=grounded,
        candidates=[chunk],
        source_selection=selection,
        metadata={"source": "initial"},
    )
    gate = GroundingGateDecision(
        should_rewrite=True,
        route="rewrite",
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )
    rewrite = CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify MiniRAG recall mechanisms."],
        attempts=1,
        failure_reason=None,
    )
    enriched = EnrichedGroundingInput(
        original_query=snapshot.query,
        solution_steps=rewrite.solution_steps,
    )
    assessment = PostRewriteAssessment(
        gate_passed=False,
        reason="selected_answer_candidate_count_below_threshold",
        signals={"selected_answer_candidate_count": 0, "threshold": 1},
    )

    assert snapshot.candidates == [chunk]
    assert gate.route == "rewrite"
    assert rewrite.solution_steps == ["Identify MiniRAG recall mechanisms."]
    assert enriched.original_query == snapshot.query
    assert assessment.gate_passed is False


def test_cot_grounding_rewriter_is_protocol() -> None:
    from typing import Protocol

    assert issubclass(CoTGroundingRewriter, Protocol)
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py::test_retrieval_rewrite_models_preserve_snapshot_and_status \
  tests/unit/domain/test_minirag_topology_models.py::test_cot_grounding_rewriter_is_protocol -q
```

Expected: FAIL because the models and protocol are not defined or exported.

- [ ] **Step 3: Add dataclasses**

Add to `src/ragflow_lite/domain/models/entities.py` near the MiniRAG topology models:

```python
@dataclass
class InitialCandidateSnapshot:
    query: str
    grounded_query: GroundedQuery
    candidates: list[RetrievedChunk]
    source_selection: GraphFirstSourceSelection | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass
class GroundingGateDecision:
    should_rewrite: bool
    route: Literal["accept", "rewrite"]
    reason: str
    signals: Metadata = field(default_factory=dict)


@dataclass
class CoTGroundingResult:
    status: Literal["succeeded", "failed"]
    strategy: Literal["cot_grounding"]
    original_query: str
    solution_steps: list[str]
    attempts: int
    failure_reason: str | None = None


@dataclass
class EnrichedGroundingInput:
    original_query: str
    solution_steps: list[str]


@dataclass
class PostRewriteAssessment:
    gate_passed: bool
    reason: str
    signals: Metadata = field(default_factory=dict)
```

If `Literal` is not already imported, add:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Export the models**

Add the five classes to the import list and `__all__` in `src/ragflow_lite/domain/models/__init__.py`:

```python
CoTGroundingResult,
EnrichedGroundingInput,
GroundingGateDecision,
InitialCandidateSnapshot,
PostRewriteAssessment,
```

and:

```python
"CoTGroundingResult",
"EnrichedGroundingInput",
"GroundingGateDecision",
"InitialCandidateSnapshot",
"PostRewriteAssessment",
```

- [ ] **Step 5: Add the port**

Add to `src/ragflow_lite/domain/ports/interfaces.py`:

```python
class CoTGroundingRewriter(Protocol):
    def rewrite(self, query: str) -> CoTGroundingResult:
        """Return retrieval-facing solution steps for a normalized user query."""
```

Update imports in the same file:

```python
from ragflow_lite.domain.models import CoTGroundingResult
```

- [ ] **Step 6: Run domain tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/domain/test_minirag_topology_models.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add \
  src/ragflow_lite/domain/models/entities.py \
  src/ragflow_lite/domain/models/__init__.py \
  src/ragflow_lite/domain/ports/interfaces.py \
  tests/unit/domain/test_minirag_topology_models.py
git commit -m "feat: add retrieval rewrite domain contracts"
```

Expected: commit succeeds.

## Task 2: Add Deterministic Gate And Metadata Helpers

Purpose: make rewrite triggering local, deterministic, and testable.

**Files:**

- Create: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Test: `tests/unit/application/test_retrieval_rewrite.py`

- [ ] **Step 1: Add failing gate tests**

Create `tests/unit/application/test_retrieval_rewrite.py`:

```python
from __future__ import annotations

from ragflow_lite.application.services.retrieval_rewrite import (
    assess_post_rewrite,
    build_retrieval_rewrite_metadata,
    decide_grounding_gate,
)
from ragflow_lite.domain.models import (
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    InitialCandidateSnapshot,
    RetrievedChunk,
)


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc1",
        text=f"text {chunk_id}",
        score=1.0,
        metadata={},
    )


def _source(chunk_id: str, *, selected_for_answer: bool) -> GraphFirstSource:
    return GraphFirstSource(
        chunk_id=chunk_id,
        rank=0,
        score=1.0,
        score_components={"test": 1.0},
        supporting_entity_ids=[],
        supporting_relation_ids=[],
        supporting_path_ids=[],
        auxiliary_chunk_hit=False,
        selected_for_answer=selected_for_answer,
        selected_for_discourse=selected_for_answer,
        selection_reason="test",
    )


def _snapshot(selected_answer_count: int) -> InitialCandidateSnapshot:
    sources = [
        _source(f"chunk_{index}", selected_for_answer=index < selected_answer_count)
        for index in range(4)
    ]
    return InitialCandidateSnapshot(
        query="What improves MiniRAG recall?",
        grounded_query=GroundedQuery(
            query="What improves MiniRAG recall?",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        candidates=[_chunk(source.chunk_id) for source in sources if source.selected_for_answer],
        source_selection=GraphFirstSourceSelection(
            sources=sources,
            final_context_k=4,
            discourse_selection_k=8,
            context_token_budget=None,
            omitted_source_count=0,
        ),
    )


def test_gate_accepts_when_selected_answer_candidates_meet_threshold() -> None:
    decision = decide_grounding_gate(_snapshot(selected_answer_count=2), requested_top_n=4)

    assert decision.should_rewrite is False
    assert decision.route == "accept"
    assert decision.signals["selected_answer_candidate_count"] == 2
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_rewrites_when_selected_answer_candidates_are_below_threshold() -> None:
    decision = decide_grounding_gate(_snapshot(selected_answer_count=1), requested_top_n=4)

    assert decision.should_rewrite is True
    assert decision.route == "rewrite"
    assert decision.reason == "selected_answer_candidate_count_below_threshold"
    assert decision.signals["selected_answer_candidate_count"] == 1
    assert decision.signals["selected_answer_candidate_threshold"] == 2


def test_gate_uses_ceil_half_top_n_threshold() -> None:
    assert decide_grounding_gate(_snapshot(1), requested_top_n=2).should_rewrite is False
    assert decide_grounding_gate(_snapshot(1), requested_top_n=3).should_rewrite is True
    assert decide_grounding_gate(_snapshot(2), requested_top_n=3).should_rewrite is False
    assert decide_grounding_gate(_snapshot(3), requested_top_n=5).should_rewrite is False
    assert decide_grounding_gate(_snapshot(3), requested_top_n=8).should_rewrite is True


def test_post_rewrite_assessment_does_not_request_recursive_rewrite() -> None:
    assessment = assess_post_rewrite(_snapshot(selected_answer_count=1), requested_top_n=4)

    assert assessment.gate_passed is False
    assert assessment.reason == "selected_answer_candidate_count_below_threshold"


def test_retrieval_rewrite_metadata_records_failed_fallback() -> None:
    metadata = build_retrieval_rewrite_metadata(
        enabled=True,
        triggered=True,
        strategy="cot_grounding",
        status="failed",
        gate_reason="selected_answer_candidate_count_below_threshold",
        attempts=2,
        failure_reason="invalid structured output",
        fallback_source="initial_candidate_snapshot",
        initial_candidate_count=1,
        enriched_candidate_count=0,
        post_rewrite_gate_passed=None,
        post_rewrite_gate_reason=None,
        answer_notice_required=False,
    )

    assert metadata["retrieval_rewrite"]["status"] == "failed"
    assert metadata["retrieval_rewrite"]["fallback_source"] == "initial_candidate_snapshot"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py -q
```

Expected: FAIL because `retrieval_rewrite.py` does not exist.

- [ ] **Step 3: Implement deterministic gate and metadata helpers**

Create `src/ragflow_lite/application/services/retrieval_rewrite.py`:

```python
from __future__ import annotations

from math import ceil
from typing import Any, Literal

from ragflow_lite.domain.models import (
    GroundingGateDecision,
    InitialCandidateSnapshot,
    PostRewriteAssessment,
)

RewriteStatus = Literal["not_triggered", "succeeded", "failed", "degraded"]


def _selected_answer_candidate_count(snapshot: InitialCandidateSnapshot) -> int:
    if snapshot.source_selection is None:
        return len(snapshot.candidates)
    return sum(1 for source in snapshot.source_selection.sources if source.selected_for_answer)


def _threshold(requested_top_n: int) -> int:
    return ceil(requested_top_n / 2)


def decide_grounding_gate(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> GroundingGateDecision:
    selected_count = _selected_answer_candidate_count(snapshot)
    threshold = _threshold(requested_top_n)
    signals: dict[str, Any] = {
        "selected_answer_candidate_count": selected_count,
        "selected_answer_candidate_threshold": threshold,
        "requested_top_n": requested_top_n,
    }
    if selected_count < threshold:
        return GroundingGateDecision(
            should_rewrite=True,
            route="rewrite",
            reason="selected_answer_candidate_count_below_threshold",
            signals=signals,
        )
    return GroundingGateDecision(
        should_rewrite=False,
        route="accept",
        reason="selected_answer_candidate_count_meets_threshold",
        signals=signals,
    )


def assess_post_rewrite(
    snapshot: InitialCandidateSnapshot,
    *,
    requested_top_n: int,
) -> PostRewriteAssessment:
    decision = decide_grounding_gate(snapshot, requested_top_n=requested_top_n)
    return PostRewriteAssessment(
        gate_passed=not decision.should_rewrite,
        reason=decision.reason,
        signals=decision.signals,
    )


def build_retrieval_rewrite_metadata(
    *,
    enabled: bool,
    triggered: bool,
    strategy: str | None,
    status: RewriteStatus,
    gate_reason: str | None,
    attempts: int,
    failure_reason: str | None,
    fallback_source: str | None,
    initial_candidate_count: int,
    enriched_candidate_count: int,
    post_rewrite_gate_passed: bool | None,
    post_rewrite_gate_reason: str | None,
    answer_notice_required: bool,
) -> dict[str, Any]:
    return {
        "retrieval_rewrite": {
            "enabled": enabled,
            "triggered": triggered,
            "strategy": strategy,
            "status": status,
            "gate_reason": gate_reason,
            "attempts": attempts,
            "failure_reason": failure_reason,
            "fallback_source": fallback_source,
            "initial_candidate_count": initial_candidate_count,
            "enriched_candidate_count": enriched_candidate_count,
            "post_rewrite_gate_passed": post_rewrite_gate_passed,
            "post_rewrite_gate_reason": post_rewrite_gate_reason,
            "answer_notice_required": answer_notice_required,
        }
    }
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_retrieval_rewrite.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/ragflow_lite/application/services/retrieval_rewrite.py tests/unit/application/test_retrieval_rewrite.py
git commit -m "feat: add deterministic retrieval rewrite gate"
```

Expected: commit succeeds.

## Task 3: Add CoT Grounding Parser And Rewriters

Purpose: generate only `solution_steps`, validate shape, and retry once at the rewriter layer.

**Files:**

- Create: `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`
- Create: `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`
- Create: `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`
- Modify: `src/ragflow_lite/infrastructure/retrievers/__init__.py`
- Test: `tests/unit/infrastructure/test_cot_grounding.py`
- Test: `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`
- Test: `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`

- [ ] **Step 1: Add parser tests**

Create `tests/unit/infrastructure/test_cot_grounding.py`:

```python
from __future__ import annotations

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    parse_cot_grounding_result,
    render_enriched_grounding_input,
)


def test_parse_cot_grounding_result_accepts_solution_steps_only() -> None:
    result = parse_cot_grounding_result(
        '{"original_query":"What improves MiniRAG recall?",'
        '"solution_steps":["Identify recall failure.", "Map entities and relations."]}',
        expected_query="What improves MiniRAG recall?",
        attempts=1,
    )

    assert result.status == "succeeded"
    assert result.solution_steps == [
        "Identify recall failure.",
        "Map entities and relations.",
    ]
    assert result.original_query == "What improves MiniRAG recall?"


def test_parse_cot_grounding_result_rejects_direct_retrieval_parameters() -> None:
    with pytest.raises(ProcessingError, match="must not include retrieval fields"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["step"],"entities":["MiniRAG"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_mismatched_query() -> None:
    with pytest.raises(ProcessingError, match="original_query does not match"):
        parse_cot_grounding_result(
            '{"original_query":"Different","solution_steps":["step"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_empty_steps() -> None:
    with pytest.raises(ProcessingError, match="solution_steps"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["   "]}',
            expected_query="Q",
            attempts=1,
        )


def test_render_enriched_grounding_input_contains_query_and_steps() -> None:
    rendered = render_enriched_grounding_input(
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify recall failure.", "Map entities and relations."],
    )

    assert "Original query:" in rendered
    assert "What improves MiniRAG recall?" in rendered
    assert "Solution steps:" in rendered
    assert "1. Identify recall failure." in rendered
    assert "2. Map entities and relations." in rendered


def test_cot_grounding_instructions_do_not_request_entities_or_relations() -> None:
    assert "solution_steps" in COT_GROUNDING_INSTRUCTIONS
    assert '"entities"' not in COT_GROUNDING_INSTRUCTIONS
    assert '"relations"' not in COT_GROUNDING_INSTRUCTIONS
    assert "answer_type_keywords" not in COT_GROUNDING_INSTRUCTIONS
```

- [ ] **Step 2: Add DeepSeek rewriter tests**

Create `tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.retrievers import DeepSeekCoTGroundingRewriter


class _FakeDeepSeekClient:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        output = self.outputs.pop(0)
        if output == "__raise__":
            raise RuntimeError("provider failed")
        return output


def test_deepseek_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeDeepSeekClient(
        ['{"original_query":"Q","solution_steps":["Clarify Q."]}']
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    assert len(client.calls) == 1


def test_deepseek_cot_rewriter_retries_once_then_succeeds() -> None:
    client = _FakeDeepSeekClient(
        [
            '{"original_query":"Q","solution_steps":[]}',
            '{"original_query":"Q","solution_steps":["Clarify Q."]}',
        ]
    )
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.attempts == 2
    assert result.solution_steps == ["Clarify Q."]


def test_deepseek_cot_rewriter_returns_failed_after_exhaustion() -> None:
    client = _FakeDeepSeekClient(["not-json", "not-json"])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.strategy == "cot_grounding"
    assert result.solution_steps == []
    assert result.attempts == 2
    assert "invalid JSON" in (result.failure_reason or "")


def test_deepseek_cot_rewriter_rejects_empty_query_without_model_call() -> None:
    client = _FakeDeepSeekClient([])
    rewriter = DeepSeekCoTGroundingRewriter(client=client)

    with pytest.raises(Exception, match="requires a query"):
        rewriter.rewrite("   ")

    assert client.calls == []
```

- [ ] **Step 3: Add OpenAI rewriter tests**

Create `tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from ragflow_lite.infrastructure.retrievers import OpenAIResponsesCoTGroundingRewriter


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self.outputs.pop(0))


class _FakeClient:
    def __init__(self, outputs: list[str]) -> None:
        self.responses = _FakeResponses(outputs)


def test_openai_cot_rewriter_returns_solution_steps() -> None:
    client = _FakeClient(['{"original_query":"Q","solution_steps":["Clarify Q."]}'])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "succeeded"
    assert result.solution_steps == ["Clarify Q."]
    assert result.attempts == 1
    request = client.responses.calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert "solution_steps" in str(request["instructions"])


def test_openai_cot_rewriter_retries_once_then_failed() -> None:
    client = _FakeClient(["not-json", "not-json"])
    rewriter = OpenAIResponsesCoTGroundingRewriter(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
    )

    result = rewriter.rewrite("Q")

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.failure_reason is not None
    assert len(client.responses.calls) == 2
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py -q
```

Expected: FAIL because new modules do not exist.

- [ ] **Step 5: Implement parser helper**

Create `src/ragflow_lite/infrastructure/retrievers/cot_grounding.py`:

```python
from __future__ import annotations

import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult

COT_GROUNDING_INSTRUCTIONS = """Create retrieval-facing solution steps for MiniRAG grounding.

Return exactly one JSON object with this shape:
{
  "original_query": "the exact user query",
  "solution_steps": ["short retrieval-facing step"]
}

Rules:
- Return solution_steps only; do not return entities, relations, keywords, or answer_type_keywords.
- Keep each step short and useful for retrieval grounding.
- Do not output markdown or prose outside the JSON object.
"""

_FORBIDDEN_FIELDS = {
    "entities",
    "relations",
    "keywords",
    "answer_type_keywords",
    "entities_from_query",
}


def parse_cot_grounding_result(
    text: str,
    *,
    expected_query: str,
    attempts: int,
) -> CoTGroundingResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProcessingError("CoT grounding returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProcessingError("CoT grounding must return a JSON object.")
    if _FORBIDDEN_FIELDS.intersection(payload):
        raise ProcessingError("CoT grounding output must not include retrieval fields.")
    original_query = payload.get("original_query")
    if not isinstance(original_query, str) or original_query.strip() != expected_query:
        raise ProcessingError("CoT grounding original_query does not match.")
    raw_steps = payload.get("solution_steps")
    if not isinstance(raw_steps, list):
        raise ProcessingError("CoT grounding output missing solution_steps.")
    steps: list[str] = []
    for step in raw_steps:
        if not isinstance(step, str) or not step.strip():
            raise ProcessingError("CoT grounding solution_steps must contain strings.")
        steps.append(step.strip())
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return CoTGroundingResult(
        status="succeeded",
        strategy="cot_grounding",
        original_query=expected_query,
        solution_steps=steps,
        attempts=attempts,
        failure_reason=None,
    )


def failed_cot_grounding_result(
    *,
    original_query: str,
    attempts: int,
    failure_reason: str,
) -> CoTGroundingResult:
    return CoTGroundingResult(
        status="failed",
        strategy="cot_grounding",
        original_query=original_query,
        solution_steps=[],
        attempts=attempts,
        failure_reason=failure_reason,
    )


def render_enriched_grounding_input(
    *,
    original_query: str,
    solution_steps: list[str],
) -> str:
    lines = ["Original query:", original_query.strip(), "", "Solution steps:"]
    lines.extend(f"{index}. {step.strip()}" for index, step in enumerate(solution_steps, start=1))
    return "\n".join(lines).strip()
```

- [ ] **Step 6: Implement DeepSeek rewriter**

Create `src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class DeepSeekCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = self.client.complete_json(
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input_text=normalized_query,
                )
                return parse_cot_grounding_result(
                    text,
                    expected_query=normalized_query,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
        return failed_cot_grounding_result(
            original_query=normalized_query,
            attempts=self.max_attempts,
            failure_reason=last_error,
        )

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "DeepSeek CoT grounding rewriter requires api_key and base_url when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )
```

- [ ] **Step 7: Implement OpenAI rewriter**

Create `src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py`:

```python
from __future__ import annotations

from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    failed_cot_grounding_result,
    parse_cot_grounding_result,
)


class OpenAIResponsesCoTGroundingRewriter:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        store: bool,
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ProcessingError("CoT grounding max_attempts must be >= 1.")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.max_attempts = max_attempts
        self.client = client or self._build_client(api_key, base_url)

    def rewrite(self, query: str) -> CoTGroundingResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ProcessingError("CoT grounding rewrite requires a query.")
        last_error = "unknown CoT grounding failure"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    instructions=COT_GROUNDING_INSTRUCTIONS,
                    input=normalized_query,
                    reasoning={"effort": self.reasoning_effort},
                    store=self.store,
                )
                return parse_cot_grounding_result(
                    response.output_text,
                    expected_query=normalized_query,
                    attempts=attempt,
                )
            except Exception as exc:
                last_error = str(exc)
        return failed_cot_grounding_result(
            original_query=normalized_query,
            attempts=self.max_attempts,
            failure_reason=last_error,
        )

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)
```

- [ ] **Step 8: Export the new rewriters**

Modify `src/ragflow_lite/infrastructure/retrievers/__init__.py`:

```python
from ragflow_lite.infrastructure.retrievers.deepseek_cot_grounding_rewriter import (
    DeepSeekCoTGroundingRewriter,
)
from ragflow_lite.infrastructure.retrievers.openai_cot_grounding_rewriter import (
    OpenAIResponsesCoTGroundingRewriter,
)
```

Add to `__all__`:

```python
"DeepSeekCoTGroundingRewriter",
"OpenAIResponsesCoTGroundingRewriter",
```

- [ ] **Step 9: Run rewriter tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add \
  src/ragflow_lite/infrastructure/retrievers/cot_grounding.py \
  src/ragflow_lite/infrastructure/retrievers/deepseek_cot_grounding_rewriter.py \
  src/ragflow_lite/infrastructure/retrievers/openai_cot_grounding_rewriter.py \
  src/ragflow_lite/infrastructure/retrievers/__init__.py \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py
git commit -m "feat: add CoT grounding rewriters"
```

Expected: commit succeeds.

## Task 4: Refactor MiniGraphFirstRetriever Into Reusable Retrieval Pass

Purpose: create a local seam so the initial and enriched retrieval passes share the same selection code.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add a no-behavior-change regression test**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
def test_mini_graph_first_retriever_without_rewriter_keeps_existing_metadata() -> None:
    retriever = MiniGraphFirstRetriever(
        query_grounder=RecordingGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=RecordingAuxiliaryRetriever(),
    )

    result = retriever.retrieve_context("How does MiniRAG recover sources?", top_k=2)

    assert result.metadata["retrieval_mode"] == "mini_graph_first"
    assert "retrieval_rewrite" not in result.metadata
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_a", "chunk_b"]
```

- [ ] **Step 2: Run the regression test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_mini_graph_first_retriever_without_rewriter_keeps_existing_metadata -q
```

Expected: PASS before refactor.

- [ ] **Step 3: Extract a private `_retrieve_context_once` helper**

In `MiniGraphFirstRetriever`, keep `retrieve_context()` public and extract the current body after `_require_positive_top_k(top_k)` into a helper shaped like:

```python
def _retrieve_context_once(
    self,
    *,
    original_query: str,
    grounding_query: str,
    auxiliary_query: str,
    top_k: int,
    discourse_selection_n: int,
) -> TopologyRetrievalResult:
    grounded_query = self.query_grounder.ground(grounding_query)
    if (
        not grounded_query.entities_from_query
        and not grounded_query.answer_type_keywords
    ):
        return self._fallback_empty_grounding(
            original_query,
            grounded_query,
            top_k,
            discourse_selection_n,
            auxiliary_query=auxiliary_query,
        )
    query_entities = grounded_query.entities_from_query[: self.query_entity_limit]
    query_entity_n = len(query_entities)
    entity_candidate_n = self.mini_internal_candidate_n
    relationship_candidate_n = max(
        self.mini_internal_candidate_n,
        query_entity_n * self.mini_internal_candidate_n,
    )
    entity_candidates = self.entity_index.query_entities(
        query_entities,
        top_k=entity_candidate_n,
    )
    relationship_candidates = self.relationship_index.query_relationships(
        auxiliary_query,
        grounded_query.answer_type_keywords,
        top_k=relationship_candidate_n,
    )
    relation_paths = self.path_expander.expand_paths(
        seed_entity_ids=_entity_ids(entity_candidates),
        seed_relation_ids=_relation_ids(relationship_candidates),
        max_hops=self.path_hop_limit,
    )
    paths = _merge_trimmed_no_path_candidates(
        entity_candidates,
        relation_paths,
        relationship_candidates,
    )[: self.path_candidate_k]
    auxiliary_chunks = self._retrieve_auxiliary_chunks(auxiliary_query, answer_top_n)
    supports = _score_source_chunks(
        entity_candidates=entity_candidates,
        relationship_candidates=relationship_candidates,
        paths=paths,
        auxiliary_chunks=auxiliary_chunks,
    )
    selection = self._build_source_selection(
        supports,
        answer_top_n,
        discourse_selection_n=discourse_selection_n,
    )
    answer_chunk_ids = [
        source.chunk_id
        for source in selection.sources
        if source.selected_for_answer
    ]
    discourse_only_chunk_ids = [
        source.chunk_id
        for source in selection.sources
        if source.selected_for_discourse and not source.selected_for_answer
    ]
    chunks = self._resolve_chunks_with_selection(
        answer_chunk_ids,
        auxiliary_chunks,
        selection,
        answer_top_n,
    )
    supplemental_chunks = self._resolve_supplemental_discourse_chunks(
        discourse_only_chunk_ids,
        auxiliary_chunks,
        selection,
    )
    return TopologyRetrievalResult(
        query=original_query,
        grounded_query=grounded_query,
        chunks=chunks,
        paths=paths,
        metadata={
            "retrieval_mode": "mini_graph_first",
            "source_selection": self._source_selection_summary(selection),
            "supplemental_discourse_chunks": supplemental_chunks,
        },
        source_selection=selection,
    )
```

For the existing normal path, call:

```python
return self._retrieve_context_once(
    original_query=query,
    grounding_query=query,
    auxiliary_query=query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
```

Preserve the existing empty-grounding fallback behavior by updating `_fallback_empty_grounding()` only as needed to accept `original_query` and `auxiliary_query` while returning `TopologyRetrievalResult.query == original_query`.

- [ ] **Step 4: Run existing MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS. This task should not add rewrite behavior yet.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/ragflow_lite/application/services/mini_graph_first_retriever.py tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "refactor: isolate MiniRAG retrieval pass"
```

Expected: commit succeeds.

## Task 5: Integrate Gate And Failed-Rewrite Fallback

Purpose: snapshot initial candidates, trigger a deterministic gate, call the rewriter, and fall back to cached initial candidates on rewrite failure.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Modify: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add fake rewriter helpers**

Add near the test fakes in `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
@dataclass
class FailingCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="failed",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=2,
            failure_reason="invalid structured output",
        )
```

Update imports:

```python
from ragflow_lite.domain.models import CoTGroundingResult
```

- [ ] **Step 2: Add failing fallback test**

Add:

```python
def test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query() -> None:
    grounder = EmptyGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    rewriter = FailingCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]
    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk_0"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] == "failed"
    assert rewrite["attempts"] == 2
    assert rewrite["failure_reason"] == "invalid structured output"
    assert rewrite["fallback_source"] == "initial_candidate_snapshot"
```

- [ ] **Step 3: Run the test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query -q
```

Expected: FAIL because `cot_grounding_rewriter` is not accepted and metadata is absent.

- [ ] **Step 4: Add optional rewriter constructor parameter**

In `MiniGraphFirstRetriever.__init__()`, add:

```python
cot_grounding_rewriter: CoTGroundingRewriter | None = None,
```

Store:

```python
self.cot_grounding_rewriter = cot_grounding_rewriter
```

Import the protocol:

```python
from ragflow_lite.domain.ports.interfaces import CoTGroundingRewriter
```

- [ ] **Step 5: Add snapshot helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.models import InitialCandidateSnapshot, TopologyRetrievalResult


def snapshot_initial_candidates(result: TopologyRetrievalResult) -> InitialCandidateSnapshot:
    return InitialCandidateSnapshot(
        query=result.query,
        grounded_query=result.grounded_query,
        candidates=list(result.chunks),
        source_selection=result.source_selection,
        metadata=dict(result.metadata),
    )
```

- [ ] **Step 6: Implement failed-rewrite fallback orchestration**

In `MiniGraphFirstRetriever.retrieve_context()`:

```python
initial_result = self._retrieve_context_once(
    original_query=query,
    grounding_query=query,
    auxiliary_query=query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
if self.cot_grounding_rewriter is None:
    return initial_result

snapshot = snapshot_initial_candidates(initial_result)
gate = decide_grounding_gate(snapshot, requested_top_n=answer_top_n)
if not gate.should_rewrite:
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=False,
            strategy=None,
            status="not_triggered",
            gate_reason=gate.reason,
            attempts=0,
            failure_reason=None,
            fallback_source=None,
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result

rewrite = self.cot_grounding_rewriter.rewrite(snapshot.query)
if rewrite.status == "failed":
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=True,
            strategy="cot_grounding",
            status="failed",
            gate_reason=gate.reason,
            attempts=rewrite.attempts,
            failure_reason=rewrite.failure_reason,
            fallback_source="initial_candidate_snapshot",
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result
```

Keep the successful rewrite branch temporarily returning `initial_result` with a comment only if it is unreachable in this task's tests. Do not leave the branch incomplete after Task 6.

- [ ] **Step 7: Run the fallback test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py::test_rewrite_failure_uses_initial_snapshot_without_rerunning_raw_query -q
```

Expected: PASS.

- [ ] **Step 8: Run focused MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/retrieval_rewrite.py \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "feat: fall back to initial candidates when rewrite fails"
```

Expected: commit succeeds.

## Task 6: Implement Successful Rewrite And Candidate Merge

Purpose: use `original_query + solution_steps` for enriched grounding and auxiliary retrieval, merge candidates, and keep final-window bounds.

**Files:**

- Modify: `src/ragflow_lite/application/services/retrieval_rewrite.py`
- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Test: `tests/unit/application/test_retrieval_rewrite.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`

- [ ] **Step 1: Add successful rewriter and enriched grounder test fakes**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
@dataclass
class SuccessfulCoTRewriter:
    calls: list[str] = field(default_factory=list)

    def rewrite(self, query: str) -> CoTGroundingResult:
        self.calls.append(query)
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=["Identify missing MiniRAG relation evidence."],
            attempts=1,
            failure_reason=None,
        )


@dataclass
class EnrichedAwareGrounder:
    calls: list[str] = field(default_factory=list)

    def ground(self, query: str) -> GroundedQuery:
        self.calls.append(query)
        if "Solution steps:" in query:
            return GroundedQuery(
                query=query,
                answer_type_keywords=["relation"],
                entities_from_query=["EnrichedMiniRAG"],
            )
        return GroundedQuery(
            query=query,
            answer_type_keywords=["mechanism"],
            entities_from_query=[],
        )
```

- [ ] **Step 2: Add successful rewrite test**

Add:

```python
def test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass() -> None:
    grounder = EnrichedAwareGrounder()
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=4)
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=2)

    assert rewriter.calls == ["ambiguous question"]
    assert len(grounder.calls) == 2
    assert grounder.calls[0] == "ambiguous question"
    assert "Original query:" in grounder.calls[1]
    assert "ambiguous question" in grounder.calls[1]
    assert "Solution steps:" in grounder.calls[1]
    assert "Identify missing MiniRAG relation evidence." in grounder.calls[1]
    assert len(result.chunks) <= 2
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["status"] in {"succeeded", "degraded"}
    assert rewrite["initial_candidate_count"] >= 1
    assert rewrite["enriched_candidate_count"] >= 1
```

- [ ] **Step 3: Add no-solution-steps failure test**

Add:

```python
@dataclass
class EmptyStepsCoTRewriter:
    def rewrite(self, query: str) -> CoTGroundingResult:
        return CoTGroundingResult(
            status="succeeded",
            strategy="cot_grounding",
            original_query=query,
            solution_steps=[],
            attempts=1,
            failure_reason=None,
        )


def test_success_status_with_empty_steps_is_treated_as_rewrite_failure() -> None:
    auxiliary_retriever = ManyAuxiliaryRetriever(chunk_count=1)
    retriever = MiniGraphFirstRetriever(
        query_grounder=EmptyGrounder(),
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=auxiliary_retriever,
        cot_grounding_rewriter=EmptyStepsCoTRewriter(),
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert result.metadata["retrieval_rewrite"]["status"] == "failed"
    assert result.metadata["retrieval_rewrite"]["fallback_source"] == "initial_candidate_snapshot"
    assert auxiliary_retriever.calls == [("ambiguous question", 30)]
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass \
  tests/unit/application/test_mini_graph_first_retriever.py::test_success_status_with_empty_steps_is_treated_as_rewrite_failure -q
```

Expected: FAIL because successful rewrite branch is not implemented.

- [ ] **Step 5: Add enriched input helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import CoTGroundingResult, EnrichedGroundingInput
from ragflow_lite.infrastructure.retrievers.cot_grounding import render_enriched_grounding_input


def build_enriched_grounding_input(
    *,
    snapshot: InitialCandidateSnapshot,
    rewrite: CoTGroundingResult,
) -> EnrichedGroundingInput:
    if rewrite.status != "succeeded":
        raise ProcessingError("CoT grounding rewrite did not succeed.")
    if rewrite.original_query.strip() != snapshot.query.strip():
        raise ProcessingError("CoT grounding original_query does not match snapshot.")
    steps = [step.strip() for step in rewrite.solution_steps if step.strip()]
    if not steps:
        raise ProcessingError("CoT grounding solution_steps must not be empty.")
    return EnrichedGroundingInput(original_query=snapshot.query, solution_steps=steps)


def render_enriched_query(input_value: EnrichedGroundingInput) -> str:
    return render_enriched_grounding_input(
        original_query=input_value.original_query,
        solution_steps=input_value.solution_steps,
    )
```

- [ ] **Step 6: Implement merge helper**

In `src/ragflow_lite/application/services/retrieval_rewrite.py`, add:

```python
from ragflow_lite.domain.models import RetrievedChunk, TopologyRetrievalResult


def merge_retrieval_results(
    *,
    initial: TopologyRetrievalResult,
    enriched: TopologyRetrievalResult,
    top_k: int,
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for source_name, chunks in (
        ("initial", initial.chunks),
        ("enriched", enriched.chunks),
    ):
        for chunk in chunks:
            existing = merged.get(chunk.chunk_id)
            source_set = set()
            if existing is not None:
                source_set.update(existing.metadata.get("retrieval_rewrite_sources", []))
                if existing.score >= chunk.score:
                    target = existing
                else:
                    target = chunk
            else:
                target = chunk
            source_set.add(source_name)
            target.metadata = dict(target.metadata)
            target.metadata["retrieval_rewrite_sources"] = sorted(source_set)
            merged[chunk.chunk_id] = target
    return sorted(merged.values(), key=lambda chunk: chunk.score, reverse=True)[:top_k]
```

This smallest merge rule keeps current behavior when rewrite is not triggered and preserves source metadata when rewrite is triggered.

- [ ] **Step 7: Complete successful rewrite branch**

In `MiniGraphFirstRetriever.retrieve_context()`:

```python
try:
    enriched_input = build_enriched_grounding_input(snapshot=snapshot, rewrite=rewrite)
    enriched_query = render_enriched_query(enriched_input)
except ProcessingError as exc:
    initial_result.metadata.update(
        build_retrieval_rewrite_metadata(
            enabled=True,
            triggered=True,
            strategy="cot_grounding",
            status="failed",
            gate_reason=gate.reason,
            attempts=rewrite.attempts,
            failure_reason=str(exc),
            fallback_source="initial_candidate_snapshot",
            initial_candidate_count=len(snapshot.candidates),
            enriched_candidate_count=0,
            post_rewrite_gate_passed=None,
            post_rewrite_gate_reason=None,
            answer_notice_required=False,
        )
    )
    return initial_result

enriched_result = self._retrieve_context_once(
    original_query=query,
    grounding_query=enriched_query,
    auxiliary_query=enriched_query,
    top_k=answer_top_n,
    discourse_selection_n=discourse_selection_n,
)
merged_chunks = merge_retrieval_results(
    initial=initial_result,
    enriched=enriched_result,
    top_k=answer_top_n,
)
```

Build a final `TopologyRetrievalResult` using `enriched_result` as the base, replacing `.chunks` with `merged_chunks`, and then Task 7 will add post-rewrite assessment metadata.

- [ ] **Step 8: Run successful rewrite tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py::test_successful_rewrite_uses_original_query_and_solution_steps_for_enriched_pass \
  tests/unit/application/test_mini_graph_first_retriever.py::test_success_status_with_empty_steps_is_treated_as_rewrite_failure -q
```

Expected: PASS.

- [ ] **Step 9: Run full MiniRAG tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_mini_graph_first_retriever.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/retrieval_rewrite.py \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py
git commit -m "feat: run enriched MiniRAG retrieval after CoT rewrite"
```

Expected: commit succeeds.

## Task 7: Add Post-Rewrite Assessment And Answer-Facing Notice

Purpose: mark successful rewrite as degraded when final evidence is still weak, without recursive rewrite.

**Files:**

- Modify: `src/ragflow_lite/application/services/mini_graph_first_retriever.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/deepseek_chat.py`
- Modify: `src/ragflow_lite/infrastructure/answerers/openai_responses.py`
- Test: `tests/unit/application/test_mini_graph_first_retriever.py`
- Test: `tests/unit/infrastructure/test_deepseek_chat_answerer.py`
- Test: `tests/unit/infrastructure/test_openai_responses_answerer.py`

- [ ] **Step 1: Add post-rewrite degraded metadata test**

Add to `tests/unit/application/test_mini_graph_first_retriever.py`:

```python
def test_post_rewrite_gate_failure_marks_notice_without_second_rewrite() -> None:
    grounder = EnrichedAwareGrounder()
    rewriter = SuccessfulCoTRewriter()
    retriever = MiniGraphFirstRetriever(
        query_grounder=grounder,
        entity_index=RecordingEntityIndex(),
        relationship_index=RecordingRelationshipIndex(),
        path_expander=RecordingPathExpander(),
        chunk_lookup=RecordingChunkLookup(),
        chunk_auxiliary_retriever=ManyAuxiliaryRetriever(chunk_count=1),
        cot_grounding_rewriter=rewriter,
    )

    result = retriever.retrieve_context("ambiguous question", top_k=4)

    assert rewriter.calls == ["ambiguous question"]
    rewrite = result.metadata["retrieval_rewrite"]
    assert rewrite["triggered"] is True
    assert rewrite["post_rewrite_gate_passed"] is False
    assert rewrite["answer_notice_required"] is True
```

- [ ] **Step 2: Add answerer notice tests**

In `tests/unit/infrastructure/test_deepseek_chat_answerer.py`, add a fake client test:

```python
def test_deepseek_answerer_includes_retrieval_rewrite_notice() -> None:
    client = _FakeDeepSeekClient("Evidence is still limited.")
    answerer = DeepSeekChatAnswerer(client=client, instructions="Answer.")
    request = AnswerRequest(
        query="ambiguous question",
        contexts=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="limited evidence",
                score=1.0,
                metadata={},
            )
        ],
        mode="discorag",
        metadata={
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        },
    )

    answerer.answer(request)

    sent_input = client.calls[0]["input_text"]
    assert "Retrieval rewrite notice:" in sent_input
    assert "retrieval rewrite already ran" in sent_input
    assert "available evidence still appears insufficient" in sent_input
```

In `tests/unit/infrastructure/test_openai_responses_answerer.py`, add the equivalent assertion against the fake response input:

```python
def test_openai_answerer_includes_retrieval_rewrite_notice() -> None:
    client = _FakeClient("Evidence is still limited.")
    answerer = OpenAIResponsesAnswerer(
        api_key="key",
        base_url="https://example.invalid/v1",
        model="test-model",
        reasoning_effort="medium",
        store=False,
        client=client,
        instructions="Answer.",
    )
    request = AnswerRequest(
        query="ambiguous question",
        contexts=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="limited evidence",
                score=1.0,
                metadata={},
            )
        ],
        mode="discorag",
        metadata={
            "retrieval_rewrite": {
                "answer_notice_required": True,
                "post_rewrite_gate_reason": "selected_answer_candidate_count_below_threshold",
            }
        },
    )

    answerer.answer(request)

    sent_input = client.responses.calls[0]["input"]
    assert "Retrieval rewrite notice:" in sent_input
    assert "retrieval rewrite already ran" in sent_input
```

If existing fake client names differ, adapt only the fake plumbing.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_post_rewrite_gate_failure_marks_notice_without_second_rewrite \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py::test_deepseek_answerer_includes_retrieval_rewrite_notice \
  tests/unit/infrastructure/test_openai_responses_answerer.py::test_openai_answerer_includes_retrieval_rewrite_notice -q
```

Expected: FAIL because notice metadata and rendering are not implemented.

- [ ] **Step 4: Add post-rewrite assessment metadata**

In successful rewrite branch of `MiniGraphFirstRetriever.retrieve_context()`:

```python
merged_result = TopologyRetrievalResult(
    query=query,
    grounded_query=enriched_result.grounded_query,
    chunks=merged_chunks,
    paths=enriched_result.paths,
    source_selection=enriched_result.source_selection,
    metadata=dict(enriched_result.metadata),
)
merged_snapshot = snapshot_initial_candidates(merged_result)
assessment = assess_post_rewrite(merged_snapshot, requested_top_n=answer_top_n)
answer_notice_required = not assessment.gate_passed
merged_result.metadata.update(
    build_retrieval_rewrite_metadata(
        enabled=True,
        triggered=True,
        strategy="cot_grounding",
        status="succeeded" if assessment.gate_passed else "degraded",
        gate_reason=gate.reason,
        attempts=rewrite.attempts,
        failure_reason=None,
        fallback_source=None,
        initial_candidate_count=len(snapshot.candidates),
        enriched_candidate_count=len(enriched_result.chunks),
        post_rewrite_gate_passed=assessment.gate_passed,
        post_rewrite_gate_reason=assessment.reason,
        answer_notice_required=answer_notice_required,
    )
)
return merged_result
```

- [ ] **Step 5: Add answerer notice helper**

In both answerers, add:

```python
def _format_retrieval_rewrite_notice(metadata: dict[str, Any]) -> list[str]:
    rewrite = metadata.get("retrieval_rewrite")
    if not isinstance(rewrite, dict) or rewrite.get("answer_notice_required") is not True:
        return []
    return [
        "Retrieval rewrite notice:",
        "- Retrieval rewrite already ran, but the available evidence still appears insufficient.",
        "- Likely causes include missing relevant documents in the knowledge base or a query that is still too ambiguous.",
        "- Tell the user that they may need to rephrase the query or add the needed documents.",
        "",
    ]
```

Then in `_build_input()` after the question block and before blueprint/context blocks:

```python
notice_lines = _format_retrieval_rewrite_notice(request.metadata)
if notice_lines:
    lines.extend(notice_lines)
```

- [ ] **Step 6: Run notice tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py::test_post_rewrite_gate_failure_marks_notice_without_second_rewrite \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py::test_deepseek_answerer_includes_retrieval_rewrite_notice \
  tests/unit/infrastructure/test_openai_responses_answerer.py::test_openai_answerer_includes_retrieval_rewrite_notice -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add \
  src/ragflow_lite/application/services/mini_graph_first_retriever.py \
  src/ragflow_lite/infrastructure/answerers/deepseek_chat.py \
  src/ragflow_lite/infrastructure/answerers/openai_responses.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py
git commit -m "feat: surface degraded retrieval rewrite notices"
```

Expected: commit succeeds.

## Task 8: Wire Provider And Preserve API Boundary

Purpose: enable the feature in service wiring while keeping `/queries` schema unchanged.

**Files:**

- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_providers.py`
- Test: `tests/unit/api/test_v0_routes.py`

- [ ] **Step 1: Add provider wiring test**

Add to `tests/unit/api/test_providers.py` near MiniGraphFirstRetriever wiring tests:

```python
def test_build_services_wires_cot_grounding_rewriter_non_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragflow_lite.api.deps import providers as providers_module

    _patch_non_live_build_services_dependencies(monkeypatch)
    monkeypatch.setattr(
        providers_module,
        "DeepSeekCoTGroundingRewriter",
        lambda *args, **kwargs: SimpleNamespace(args=args, **kwargs),
    )
    settings = _build_settings(tmp_path)

    services = build_services(settings)

    assert services.retriever.cot_grounding_rewriter is not None
    assert services.retriever.cot_grounding_rewriter.model == settings.deepseek_model
```

If `_fake_mini_graph_first_retriever` returns a `SimpleNamespace(**kwargs)`, this assertion shape will work with existing non-live patching.

- [ ] **Step 2: Add API schema non-change test**

Add or extend in `tests/unit/api/test_v0_routes.py`:

```python
def test_query_request_does_not_expose_retrieval_rewrite_strategy() -> None:
    from ragflow_lite.api.schemas.v0 import QueryRequest

    fields = set(QueryRequest.model_fields)

    assert "rewrite_strategy" not in fields
    assert "retrieval_rewrite" not in fields
    assert "cot_grounding" not in fields
```

- [ ] **Step 3: Run tests and verify they fail where wiring is missing**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py::test_build_services_wires_cot_grounding_rewriter_non_live \
  tests/unit/api/test_v0_routes.py::test_query_request_does_not_expose_retrieval_rewrite_strategy -q
```

Expected:

- Provider test FAILS because `DeepSeekCoTGroundingRewriter` is not wired.
- API schema test PASSES if schema is unchanged.

- [ ] **Step 4: Wire DeepSeek rewriter**

In `src/ragflow_lite/api/deps/providers.py`, import:

```python
from ragflow_lite.infrastructure.retrievers import (
    DeepSeekChatQueryGrounder,
    DeepSeekCoTGroundingRewriter,
)
```

Construct next to `query_grounder`:

```python
cot_grounding_rewriter = DeepSeekCoTGroundingRewriter(
    api_key=deepseek_runtime_config.api_key,
    base_url=deepseek_runtime_config.base_url,
    model=deepseek_runtime_config.model,
    reasoning_effort=deepseek_runtime_config.reasoning_effort,
)
```

Pass to `MiniGraphFirstRetriever`:

```python
cot_grounding_rewriter=cot_grounding_rewriter,
```

- [ ] **Step 5: Run provider/API tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py::test_build_services_wires_cot_grounding_rewriter_non_live \
  tests/unit/api/test_v0_routes.py::test_query_request_does_not_expose_retrieval_rewrite_strategy -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_providers.py tests/unit/api/test_v0_routes.py
git commit -m "feat: wire gated retrieval rewrite provider"
```

Expected: commit succeeds.

## Task 9: Verify DiscoRAG Boundary And Update Contracts

Purpose: prove `DiscoRAGQueryService` receives resolved retrieval results and document the landed behavior.

**Files:**

- Modify: `tests/unit/application/test_discorag_query_service.py`
- Modify: `src/ragflow_lite/application/CONTRACTS.md`

- [ ] **Step 1: Add DiscoRAG boundary test**

Add to `tests/unit/application/test_discorag_query_service.py`:

```python
def test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata() -> None:
    retrieval_result = TopologyRetrievalResult(
        query="ambiguous question",
        grounded_query=GroundedQuery(
            query="ambiguous question",
            answer_type_keywords=["mechanism"],
            entities_from_query=["MiniRAG"],
        ),
        chunks=[
            RetrievedChunk(
                chunk_id="chunk_a",
                document_id="doc1",
                text="retrieved evidence",
                score=1.0,
                metadata={"selected_for_answer": True, "selected_for_discourse": True},
            )
        ],
        paths=[],
        metadata={
            "retrieval_rewrite": {
                "enabled": True,
                "triggered": True,
                "status": "failed",
                "fallback_source": "initial_candidate_snapshot",
            },
            "supplemental_discourse_chunks": {},
        },
    )
    retriever = FakeTopologyRetriever(result=retrieval_result)
    answerer = RecordingAnswerer()
    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=FakeDiscourseExtractor(),
        inter_chunk_graph_builder=FakeInterChunkGraphBuilder(),
        blueprint_builder=FakeBlueprintBuilder(),
        answerer=answerer,
    )

    service.query("ambiguous question", top_k=1)

    assert answerer.last_request is not None
    assert answerer.last_request.metadata["retrieval_rewrite"]["status"] == "failed"
    assert retriever.calls == [("ambiguous question", 1)]
```

Adapt fake class names to the existing test file helpers.

- [ ] **Step 2: Run boundary test and verify it fails if metadata is dropped**

Run:

```bash
.venv/bin/python -m pytest tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata -q
```

Expected: PASS if existing metadata propagation already preserves `retrieval_rewrite`; otherwise FAIL and implement the minimal propagation fix in `DiscoRAGQueryService`.

- [ ] **Step 3: Update application contract after tests pass**

Add a short section to `src/ragflow_lite/application/CONTRACTS.md`:

```markdown
## MiniRAG Retrieval Rewrite

- Retrieval rewrite is an internal MiniRAG capability owned by `MiniGraphFirstRetriever`.
- `/queries` does not expose a rewrite strategy field; routing remains `standard` or `discorag`.
- The deterministic gate uses final answer candidates, not internal graph/path/discourse-only candidates.
- `cot_grounding` may produce only explicit `solution_steps`; the grounding layer extracts entities, relations, and answer-type keywords.
- CoT rewrite may run at most once. Post-rewrite assessment may mark retrieval degraded but must not trigger recursive rewrite.
- If CoT rewrite exhausts attempts, retrieval falls back to the cached initial candidate snapshot and must not rerun raw-query MiniRAG retrieval.
- DiscoRAG receives the resolved MiniRAG retrieval result and does not own rewrite decisions.
```

- [ ] **Step 4: Run contract-adjacent focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py::test_discorag_query_service_receives_resolved_retrieval_rewrite_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add tests/unit/application/test_discorag_query_service.py src/ragflow_lite/application/CONTRACTS.md
git commit -m "docs: document MiniRAG retrieval rewrite boundary"
```

Expected: commit succeeds.

## Task 10: Final Focused Verification

Purpose: run the minimal affected suite and make sure no boundary regressed.

- [ ] **Step 1: Run domain and application tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_minirag_topology_models.py \
  tests/unit/application/test_retrieval_rewrite.py \
  tests/unit/application/test_mini_graph_first_retriever.py \
  tests/unit/application/test_discorag_query_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run infrastructure rewriter and answerer tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_cot_grounding.py \
  tests/unit/infrastructure/test_deepseek_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_openai_cot_grounding_rewriter.py \
  tests/unit/infrastructure/test_deepseek_chat_answerer.py \
  tests/unit/infrastructure/test_openai_responses_answerer.py -q
```

Expected: PASS.

- [ ] **Step 3: Run provider and route boundary tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_providers.py \
  tests/unit/api/test_v0_routes.py -q
```

Expected: PASS.

- [ ] **Step 4: Run import smoke for touched modules**

Run:

```bash
.venv/bin/python - <<'PY'
from ragflow_lite.application.services.mini_graph_first_retriever import MiniGraphFirstRetriever
from ragflow_lite.application.services.retrieval_rewrite import decide_grounding_gate
from ragflow_lite.infrastructure.retrievers import DeepSeekCoTGroundingRewriter, OpenAIResponsesCoTGroundingRewriter
from ragflow_lite.domain.models import InitialCandidateSnapshot, CoTGroundingResult

print("imports ok")
PY
```

Expected:

```text
imports ok
```

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intentional files are modified, or the working tree is clean after commits.

## Self-Review Notes

Spec coverage:

- Deterministic local gate is covered by Tasks 2, 5, and 6.
- `solution_steps`-only CoT output is covered by Task 3.
- Initial candidate snapshot and no duplicate raw-query retrieval are covered by Task 5.
- Successful enriched grounding and auxiliary retrieval are covered by Task 6.
- Post-rewrite degraded notice and no recursive rewrite are covered by Task 7.
- API/router/DiscoRAG boundary preservation is covered by Tasks 8 and 9.
- Contract update after behavior lands is covered by Task 9.

Implementation choices made by this plan:

- Use typed domain models rather than metadata-only contracts.
- Add `CoTGroundingRewriter` as a sibling port instead of widening `QueryGrounder`.
- Keep the first merge rule minimal: dedupe by `chunk_id`, preserve highest score, attach source metadata, then trim to `top_k`.
- Wire DeepSeek rewriter in `build_services()` because current runtime provider wiring already uses DeepSeek for query grounding.
