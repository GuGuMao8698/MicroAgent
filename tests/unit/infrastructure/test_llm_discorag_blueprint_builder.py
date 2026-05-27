"""Tests for LLMDiscoRAGAnswerBlueprintBuilder.

Covers: valid output producing blueprint, prompt construction with answer and
supplemental chunks, RST structures, inter-chunk relations, top_k budget,
invalid LLM output propagation, empty chunks, metadata provenance, single LLM
call, and no fallback to deterministic builder.
"""

from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ChunkDiscourseStructure,
    DiscourseUnit,
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GroundedQuery,
    InterChunkDiscourseGraph,
    InterChunkDiscourseRelation,
    IntraChunkDiscoursePackage,
    IntraChunkDiscourseRelation,
)
from ragflow_lite.infrastructure.evidence.llm_discorag_blueprint_builder import (
    LLMDiscoRAGAnswerBlueprintBuilder,
    _chunk_unit_summary,
    _classify_items,
    _resolve_top_k,
)
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptsExhaustedError as StructurerAttemptsExhaustedError,
)

# ── Fake clients ──────────────────────────────────────────────────────────────


class _FakeClient:
    """Minimal fake DeepSeekChatCompletionsClient for testing.

    Accepts a single str (backward compatible) or a list of str|Exception
    for sequential responses across retry attempts.
    """

    def __init__(self, responses: str | list[str | Exception]) -> None:
        if isinstance(responses, str):
            self._responses: list[str | Exception] = [responses]
        else:
            self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(
        self,
        instructions: str,
        input_text: str,
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> str:
        return self._next_response(locals())

    def complete_messages_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> str:
        return self._next_response(locals())

    def _next_response(self, call_args: dict) -> str:
        if not self._responses:
            raise RuntimeError("No more fake responses")
        self.calls.append(call_args)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FailingClient:
    """Client that always raises."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def complete_json(
        self,
        instructions: str,
        input_text: str,
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> str:
        raise self.error

    def complete_messages_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> str:
        raise self.error


# ── Fixture helpers ──────────────────────────────────────────────────────────

QUERY = "How does MiniRAG handle discourse?"


def _evidence_item(
    chunk_id: str,
    text: str,
    *,
    order: int = 0,
    selected_for_answer: bool = False,
    selected_for_discourse: bool = False,
) -> EvidenceItem:
    return EvidenceItem(
        canonical_chunk_id=chunk_id,
        text=text,
        score=0.9,
        order=order,
        provenance=EvidenceProvenance(
            document_id="doc_test",
            filename="test.md",
            file_type="markdown",
            chunk_index=order,
        ),
        retained_reasons=[],
        grounded_entities=[],
        answer_type_keywords=[],
        topology_path_ids=[],
        topology_relation_ids=[],
        metadata={
            "selected_for_answer": selected_for_answer,
            "selected_for_discourse": selected_for_discourse,
        },
    )


def _evidence_package(
    *items: EvidenceItem,
    source_selection: dict | None = None,
) -> EvidencePackage:
    metadata: dict = {}
    if source_selection is not None:
        metadata["source_selection"] = source_selection
    return EvidencePackage(
        query=QUERY,
        grounded_query=GroundedQuery(
            query=QUERY,
            answer_type_keywords=[],
            entities_from_query=[],
            metadata={},
        ),
        items=list(items),
        metadata=metadata,
    )


def _package(
    *items: EvidenceItem,
    structures: list[ChunkDiscourseStructure] | None = None,
    source_selection: dict | None = None,
) -> IntraChunkDiscoursePackage:
    ep = _evidence_package(*items, source_selection=source_selection)
    return IntraChunkDiscoursePackage(
        query=ep.query,
        evidence_package=ep,
        structures=structures or [],
        metadata={},
    )


def _inter_chunk_graph(
    *relations: InterChunkDiscourseRelation,
    chunk_ids: list[str] | None = None,
) -> InterChunkDiscourseGraph:
    if chunk_ids is None:
        cids: set[str] = set()
        for r in relations:
            cids.add(r.source_chunk_id)
            cids.add(r.target_chunk_id)
        chunk_ids = sorted(cids)
    return InterChunkDiscourseGraph(
        query=QUERY,
        chunk_ids=chunk_ids,
        relations=list(relations),
        metadata={},
    )


def _valid_blueprint_json(
    *,
    final_ids: list[str] | None = None,
    chunk_roles: dict[str, str] | None = None,
    promotions: list[dict] | None = None,
    constraints: list[dict] | None = None,
    plan_steps: list[dict] | None = None,
) -> str:
    resolved_final_ids = final_ids or []
    resolved_chunk_roles = chunk_roles
    if resolved_chunk_roles is None:
        resolved_chunk_roles = {
            chunk_id: ("lead" if index == 0 else "support")
            for index, chunk_id in enumerate(resolved_final_ids)
        }
    return json.dumps(
        {
            "final_answer_chunk_ids": resolved_final_ids,
            "chunk_roles": resolved_chunk_roles,
            "promotions": promotions or [],
            "answer_constraints": constraints or [],
            "plan_steps": plan_steps or [],
            "metadata": {"planner": "llm_discorag_answer_blueprint_builder"},
        }
    )


def _discourse_structure(
    chunk_id: str,
    units: list[DiscourseUnit] | None = None,
    relations: list[IntraChunkDiscourseRelation] | None = None,
) -> ChunkDiscourseStructure:
    return ChunkDiscourseStructure(
        canonical_chunk_id=chunk_id,
        document_id="doc_test",
        units=units or [],
        relations=relations or [],
        main_unit_ids=[u.unit_id for u in (units or []) if u.role == "main"],
        supporting_unit_ids=[u.unit_id for u in (units or []) if u.role == "support"],
        metadata={},
    )


def _unit(
    unit_id: str,
    chunk_id: str,
    text: str,
    *,
    role: str = "main",
    nuclearity: str | None = "nucleus",
    planning_role: str | None = None,
    rst_relation: str | None = None,
) -> DiscourseUnit:
    return DiscourseUnit(
        unit_id=unit_id,
        canonical_chunk_id=chunk_id,
        text=text,
        order=0,
        role=role,
        nuclearity=nuclearity,
        rst_relation=rst_relation,
        planning_role=planning_role,
        metadata={},
    )


def _intra_relation(
    relation_id: str,
    chunk_id: str,
    source: str,
    target: str,
    relation_type: str = "supports",
    weight: float = 1.0,
) -> IntraChunkDiscourseRelation:
    return IntraChunkDiscourseRelation(
        relation_id=relation_id,
        canonical_chunk_id=chunk_id,
        source_unit_id=source,
        target_unit_id=target,
        relation_type=relation_type,
        weight=weight,
        metadata={},
    )


# ── 1. Valid LLM output produces correct AnswerBlueprint ────────────────────


def test_valid_llm_output_produces_correct_blueprint() -> None:
    item_a = _evidence_item(
        "chunk_a", "Answer text.", order=0, selected_for_answer=True
    )
    package = _package(
        item_a,
        source_selection={"final_context_k": 3},
    )
    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package, graph=None)

    assert blueprint.ordered_chunk_ids == ["chunk_a"]
    assert blueprint.chunk_roles == {"chunk_a": "lead"}
    assert blueprint.metadata["builder"] == "llm_discorag_blueprint_parser"
    assert blueprint.metadata["final_chunk_count"] == 1


# ── 2. Builder constructs prompt with answer and supplemental chunks ─────────


def test_prompt_contains_answer_and_supplemental_chunks() -> None:
    item_a = _evidence_item(
        "chunk_a",
        "Answer.",
        order=0,
        selected_for_answer=True,
        selected_for_discourse=True,
    )
    item_s = _evidence_item(
        "chunk_s", "Supplemental.", order=1, selected_for_discourse=True
    )
    package = _package(item_a, item_s, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "## answer_candidates" in input_text
    assert "CHUNK[1] id=chunk_a" in input_text
    assert "text: Answer." in input_text
    assert "## supplemental_discourse_chunks" in input_text
    assert "CHUNK[2] id=chunk_s" in input_text
    assert "text: Supplemental." in input_text


# ── 3. Builder constructs prompt with RST structures ─────────────────────────


def test_prompt_contains_rst_structures() -> None:
    item_a = _evidence_item("chunk_a", "Main claim.", order=0, selected_for_answer=True)
    unit_main = _unit(
        "u0", "chunk_a", "Main claim.", role="main", planning_role="claim"
    )
    unit_support = _unit(
        "u1", "chunk_a", "Support detail.", role="support", planning_role="evidence"
    )
    structure = _discourse_structure(
        "chunk_a",
        units=[unit_main, unit_support],
        relations=[_intra_relation("r0", "chunk_a", "u1", "u0")],
    )
    package = _package(item_a, structures=[structure])

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    input_text = client.calls[0]["input_text"]
    # Chunk should have rst_units in its block
    assert "rst_units:" in input_text
    assert "u0(role=claim" in input_text
    assert "u1(role=evidence" in input_text
    # Intra-chunk relations section
    assert "## rst_intra_chunk_relations" in input_text
    assert "u1 -> u0: supports" in input_text


def test_chunk_unit_summary_preserves_unknown_nuclearity() -> None:
    structure = _discourse_structure(
        "chunk_a",
        units=[
            _unit(
                "u0",
                "chunk_a",
                "Main claim.",
                role="main",
                planning_role="claim",
                nuclearity=None,
            )
        ],
    )

    summary = _chunk_unit_summary(structure)

    assert "nuclearity=unknown" in summary


# ── 4. Builder constructs prompt with inter-chunk graph relations ────────────


def test_prompt_contains_inter_chunk_relations() -> None:
    item_a = _evidence_item("chunk_a", "Text A.", order=0, selected_for_answer=True)
    item_b = _evidence_item("chunk_b", "Text B.", order=1, selected_for_answer=True)
    package = _package(item_a, item_b, source_selection={"final_context_k": 5})

    relation = InterChunkDiscourseRelation(
        source_chunk_id="chunk_a",
        target_chunk_id="chunk_b",
        relation_type="supports",
        rationale="A supports B",
        confidence=0.9,
        metadata={"relation_id": "rel_0"},
    )
    graph = _inter_chunk_graph(relation, chunk_ids=["chunk_a", "chunk_b"])

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a", "chunk_b"],
        chunk_roles={"chunk_a": "lead", "chunk_b": "support"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package, graph=graph)

    input_text = client.calls[0]["input_text"]
    assert "## inter_chunk_relations" in input_text
    assert "id=rel_0" in input_text
    assert "chunk_a -> chunk_b: supports" in input_text
    assert "confidence=0.9" in input_text
    assert "rationale=A supports B" in input_text


# ── 5. Builder passes top_k budget to parser ────────────────────────────────


def test_builder_passes_top_k_to_parser() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 2})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    blueprint = builder.build(package)

    # Parser should have accepted within budget
    assert blueprint.ordered_chunk_ids == ["chunk_a"]
    # Verify the prompt contains top_k
    input_text = client.calls[0]["input_text"]
    assert "top_k budget: 2" in input_text


def test_builder_exceeding_top_k_raises() -> None:
    item_a = _evidence_item("chunk_a", "A.", order=0, selected_for_answer=True)
    item_b = _evidence_item("chunk_b", "B.", order=1, selected_for_answer=True)
    package = _package(item_a, item_b, source_selection={"final_context_k": 1})

    # LLM returns 2 chunks but budget is 1
    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a", "chunk_b"],
        chunk_roles={"chunk_a": "lead", "chunk_b": "support"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="exceeds top_k"):
        builder.build(package)


# ── 6. Invalid LLM output (ProcessingError from parser) propagates ──────────


def test_invalid_json_propagates_processing_error() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient("not valid json {{{")
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="not valid JSON"):
        builder.build(package)


def test_missing_final_ids_propagates_processing_error() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(json.dumps({"chunk_roles": {}}))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="missing 'final_answer_chunk_ids'"):
        builder.build(package)


# ── 7. Empty discourse-visible chunks produces valid output ─────────────────


def test_empty_items_with_no_answer_candidates() -> None:
    """When no items have selected_for_answer=True, answer_candidates is empty."""
    package = _package(source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(final_ids=[], chunk_roles={})
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package)

    assert blueprint.ordered_chunk_ids == []
    assert blueprint.metadata["final_chunk_count"] == 0


def test_only_supplemental_items_no_answer() -> None:
    """When only supplemental items exist (no answer), parser accepts empty final."""
    item_s = _evidence_item(
        "chunk_s", "Supplemental.", order=0, selected_for_discourse=True
    )
    package = _package(item_s, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(final_ids=[], chunk_roles={})
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package)

    assert blueprint.ordered_chunk_ids == []


# ── 8. Metadata includes model/reasoning_effort/builder provenance ──────────


def test_metadata_includes_llm_provenance() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        model="test-model-v2",
        reasoning_effort="medium",
        provider="custom-provider",
    )

    blueprint = builder.build(package)

    assert blueprint.metadata["llm"]["model"] == "test-model-v2"
    assert blueprint.metadata["llm"]["reasoning_effort"] == "medium"
    assert blueprint.metadata["llm"]["provider"] == "custom-provider"
    assert (
        blueprint.metadata["llm"]["builder"] == "llm_discorag_answer_blueprint_builder"
    )


# ── 9. Builder calls the structurer client exactly once ──────────────────────


def test_builder_calls_client_exactly_once() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(_valid_blueprint_json(final_ids=["chunk_a"]))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    builder.build(package)

    assert len(client.calls) == 1


# ── 10. No fallback to deterministic builder ────────────────────────────────


def test_llm_call_failure_propagates_no_fallback() -> None:
    """LLM call failure raises ProcessingError — no fallback."""
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FailingClient(RuntimeError("API connection refused"))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    with pytest.raises(
        ProcessingError, match="LLM DiscoRAG blueprint builder call failed"
    ):
        builder.build(package)


def test_parser_failure_propagates_no_fallback() -> None:
    """Parser rejection raises ProcessingError — no fallback."""
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    # LLM returns unknown chunk ID → parser rejects
    llm_output = _valid_blueprint_json(
        final_ids=["chunk_ghost"],
        chunk_roles={"chunk_ghost": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="Unknown chunk ID"):
        builder.build(package)


# ── Tests: _classify_items helper ────────────────────────────────────────────


def test_classify_items_splits_correctly() -> None:
    answer = _evidence_item(
        "a", "A", selected_for_answer=True, selected_for_discourse=True
    )
    supp = _evidence_item("s", "S", selected_for_discourse=True)
    neither = _evidence_item("n", "N")

    ans_items, sup_items = _classify_items([answer, supp, neither])

    assert [i.canonical_chunk_id for i in ans_items] == ["a"]
    assert [i.canonical_chunk_id for i in sup_items] == ["s"]


def test_classify_items_empty() -> None:
    ans_items, sup_items = _classify_items([])
    assert ans_items == []
    assert sup_items == []


# ── Tests: _resolve_top_k helper ────────────────────────────────────────────


def test_resolve_top_k_from_metadata() -> None:
    item = _evidence_item("a", "A", selected_for_answer=True)
    ep = _evidence_package(item, source_selection={"final_context_k": 7})
    package = _package(item, source_selection={"final_context_k": 7})

    assert _resolve_top_k(package) == 7


def test_resolve_top_k_falls_back_to_answer_count() -> None:
    item = _evidence_item("a", "A", selected_for_answer=True)
    package = _package(item)

    assert _resolve_top_k(package) == 1


# ── Tests: constructor ───────────────────────────────────────────────────────


def test_constructor_stores_params() -> None:
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        api_key="key",
        base_url="http://localhost",
        model="custom-model",
        reasoning_effort="low",
    )
    assert builder.model == "custom-model"
    assert builder.reasoning_effort == "low"


def test_build_raises_without_api_key() -> None:
    builder = LLMDiscoRAGAnswerBlueprintBuilder(base_url="http://localhost")
    item = _evidence_item("a", "Text", order=0, selected_for_answer=True)
    package = _package(item)

    with pytest.raises(ProcessingError, match="api_key and base_url"):
        builder.build(package)


def test_build_raises_without_base_url() -> None:
    builder = LLMDiscoRAGAnswerBlueprintBuilder(api_key="key")
    item = _evidence_item("a", "Text", order=0, selected_for_answer=True)
    package = _package(item)

    with pytest.raises(ProcessingError, match="api_key and base_url"):
        builder.build(package)


# ── Tests: prompt format details ────────────────────────────────────────────


def test_prompt_contains_query() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(_valid_blueprint_json(final_ids=["chunk_a"]))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "query: How does MiniRAG handle discourse?" in input_text


def test_prompt_instructions_contain_role_and_constraint_vocab() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(_valid_blueprint_json(final_ids=["chunk_a"]))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    instructions = client.calls[0]["instructions"]
    assert "lead" in instructions
    assert "caveat" in instructions
    assert "condition" in instructions
    assert "comparison" in instructions
    assert "definition" in instructions
    assert "ordering" in instructions


def test_prompt_complete_context_ordering_instructions_and_input() -> None:
    item_a = _evidence_item("chunk_a", "Text A.", order=0, selected_for_answer=True)
    item_b = _evidence_item("chunk_b", "Text B.", order=1, selected_for_answer=True)
    package = _package(item_a, item_b, source_selection={"final_context_k": 5})

    client = _FakeClient(
        _valid_blueprint_json(
            final_ids=["chunk_a", "chunk_b"],
            chunk_roles={"chunk_a": "lead", "chunk_b": "support"},
        )
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    instructions = client.calls[0]["instructions"]
    input_text = client.calls[0]["input_text"]
    assert "final_answer_chunk_ids" in instructions
    assert "all final answer contexts" in instructions
    assert "not a subset" in instructions
    assert "answer candidate" in instructions
    assert "valid promotion" in instructions
    assert "background" in instructions
    assert "context" in instructions
    assert "validation repair" in instructions
    assert "complete JSON object" in instructions
    assert "patch" in instructions
    assert "top_k is a hard parser guardrail" in instructions
    assert "do not drop required answer candidates" in instructions
    assert "answer_candidate_ids: ['chunk_a', 'chunk_b']" in input_text


def test_prompt_no_inter_chunk_section_when_graph_is_none() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(_valid_blueprint_json(final_ids=["chunk_a"]))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package, graph=None)

    input_text = client.calls[0]["input_text"]
    assert "## inter_chunk_relations" not in input_text


def test_prompt_no_rst_section_when_no_structures() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(_valid_blueprint_json(final_ids=["chunk_a"]))
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)
    builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "## rst_intra_chunk_relations" not in input_text


# ── Tests: promotion via LLM output ──────────────────────────────────────────


def test_llm_promotion_produces_valid_blueprint() -> None:
    item_a = _evidence_item("chunk_a", "Answer A.", order=0, selected_for_answer=True)
    item_s = _evidence_item(
        "chunk_s", "Supplemental S.", order=1, selected_for_discourse=True
    )
    package = _package(item_a, item_s, source_selection={"final_context_k": 5})

    relation = InterChunkDiscourseRelation(
        source_chunk_id="chunk_s",
        target_chunk_id="chunk_a",
        relation_type="contradicts",
        rationale="S contradicts A",
        confidence=0.85,
        metadata={"relation_id": "rel_0"},
    )
    graph = _inter_chunk_graph(relation, chunk_ids=["chunk_a", "chunk_s"])

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_s"],
        chunk_roles={"chunk_s": "caveat"},
        promotions=[
            {
                "replace_chunk_id": "chunk_a",
                "with_chunk_id": "chunk_s",
                "reason": "S contradicts A",
                "source_relation_ids": ["rel_0"],
                "source_rst_unit_ids": [],
            }
        ],
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package, graph=graph)

    assert blueprint.ordered_chunk_ids == ["chunk_s"]
    assert blueprint.metadata["promotion_count"] == 1
    assert "chunk_s" in blueprint.ordered_chunk_ids


# ── Tests: safe provenance metadata ──────────────────────────────────────────


def _metadata_as_str(meta: dict) -> str:
    """Flatten metadata dict to a single string for key-scanning assertions."""
    return json.dumps(meta)


def test_provenance_includes_provider_default() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package)

    assert blueprint.metadata["llm"]["provider"] == "deepseek"


def test_provenance_default_provider_is_deepseek() -> None:
    builder = LLMDiscoRAGAnswerBlueprintBuilder()
    assert builder.provider == "deepseek"


def test_build_client_disables_deepseek_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class _CapturedDeepSeekClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "ragflow_lite.infrastructure.llms.DeepSeekChatCompletionsClient",
        _CapturedDeepSeekClient,
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        model="deepseek-v4-flash",
        reasoning_effort="high",
    )

    builder._build_client("test-key", "https://api.deepseek.com")

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_provenance_includes_base_url_host() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        base_url="https://api.deepseek.com/v1/chat/completions",
    )

    blueprint = builder.build(package)

    assert blueprint.metadata["llm"]["base_url_host"] == "api.deepseek.com"


def test_provenance_no_base_url_host_when_absent() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    blueprint = builder.build(package)

    assert "base_url_host" not in blueprint.metadata["llm"]


def test_provenance_never_includes_api_key() -> None:
    item_a = _evidence_item("chunk_a", "Text.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    llm_output = _valid_blueprint_json(
        final_ids=["chunk_a"],
        chunk_roles={"chunk_a": "lead"},
    )
    client = _FakeClient(llm_output)
    # 传入包含敏感信息的 api_key 和 base_url
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        api_key="sk-super-secret-key-67890",
        base_url="https://api.deepseek.com/v1",
    )

    blueprint = builder.build(package)

    meta_str = _metadata_as_str(blueprint.metadata)
    assert "sk-super-secret-key-67890" not in meta_str
    assert "api_key" not in meta_str


# ── Tests: validation repair and timeout retry ────────────────────────────────


def _package_with_two_answer_chunks() -> IntraChunkDiscoursePackage:
    """Package with two answer chunks for retry tests."""
    item_a = _evidence_item("chunk_a", "Answer A.", order=0, selected_for_answer=True)
    item_b = _evidence_item("chunk_b", "Answer B.", order=1, selected_for_answer=True)
    return _package(item_a, item_b, source_selection={"final_context_k": 5})


def _graph() -> InterChunkDiscourseGraph:
    """Minimal inter-chunk graph for retry tests."""
    rel = InterChunkDiscourseRelation(
        source_chunk_id="chunk_a",
        target_chunk_id="chunk_b",
        relation_type="supports",
        metadata={"relation_id": "rel_0"},
    )
    return _inter_chunk_graph(rel, chunk_ids=["chunk_a", "chunk_b"])


def test_blueprint_builder_repairs_validation_error_with_multiturn_messages() -> None:
    """First attempt returns invalid JSON (missing chunk_b role), repair returns valid."""
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},  # missing chunk_b
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
    # Second call should be message-based (repair)
    repair_call = client.calls[1]
    assert repair_call.get("messages") is not None
    messages = repair_call["messages"]
    assert messages[2]["role"] == "assistant"
    assert "chunk_roles" in messages[3]["content"]
    assert "query:" not in messages[3]["content"]
    assert "Do not output a patch" in messages[3]["content"]


def test_blueprint_builder_repairs_missing_final_context_ids() -> None:
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a"],
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
    assert repair_call.get("messages") is not None
    messages = repair_call["messages"]
    assert messages[2]["role"] == "assistant"
    assert '"final_answer_chunk_ids": ["chunk_a"]' in messages[2]["content"]
    feedback = messages[3]["content"]
    assert "missing_final_context_ids=['chunk_b']" in feedback
    assert "expected_final_context_ids=['chunk_a', 'chunk_b']" in feedback
    assert "actual_final_answer_chunk_ids=['chunk_a']" in feedback
    assert "complete JSON object" in feedback
    assert "patch" in feedback


def test_prompt_validation_repair_instruction_applies_to_semantic_failures() -> None:
    item_a = _evidence_item("chunk_a", "Text A.", order=0, selected_for_answer=True)
    item_b = _evidence_item("chunk_b", "Text B.", order=1, selected_for_answer=True)
    package = _package(item_a, item_b, source_selection={"final_context_k": 5})

    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a"],
                    "chunk_roles": {"chunk_a": "lead"},
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
            _valid_blueprint_json(
                final_ids=["chunk_a", "chunk_b"],
                chunk_roles={"chunk_a": "lead", "chunk_b": "background"},
            ),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client, max_attempts=2)

    builder.build(package)

    feedback = client.calls[1]["messages"][3]["content"]
    assert "Validation error:" in feedback
    assert "missing_final_context_ids=['chunk_b']" in feedback
    assert "expected_final_context_ids=['chunk_a', 'chunk_b']" in feedback
    assert "actual_final_answer_chunk_ids=['chunk_a']" in feedback
    assert "complete JSON object" in feedback
    assert "patch" in feedback


def test_blueprint_builder_raises_after_repair_attempts_exhausted() -> None:
    """Both attempts return invalid JSON, builder raises ProcessingError."""
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},  # missing chunk_b
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},  # still missing chunk_b
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

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(_package_with_two_answer_chunks(), graph=_graph())


def test_blueprint_builder_retries_timeout_with_fresh_original_request() -> None:
    """First call times out, second call is a fresh original request (not repair)."""
    client = _FakeClient(
        responses=[
            TimeoutError("request timed out"),
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
    # Second call should be a fresh original (instructions+input_text based)
    second_call = client.calls[1]
    assert "instructions" in second_call
    assert "input_text" in second_call


def test_blueprint_builder_timeout_exhausted_raises() -> None:
    """Both attempts time out, builder raises ProcessingError."""
    client = _FakeClient(
        responses=[
            TimeoutError("request timed out"),
            TimeoutError("request timed out"),
        ]
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(_package_with_two_answer_chunks(), graph=_graph())


def test_blueprint_builder_disables_low_level_retry_for_structurer_attempts() -> None:
    item_a = _evidence_item("chunk_a", "Answer A.", order=0, selected_for_answer=True)
    package = _package(item_a, source_selection={"final_context_k": 5})

    client = _FakeClient(
        _valid_blueprint_json(
            final_ids=["chunk_a"],
            chunk_roles={"chunk_a": "lead"},
        )
    )
    builder = LLMDiscoRAGAnswerBlueprintBuilder(client=client)

    builder.build(package)

    assert client.calls[0]["max_retries"] == 0


def test_blueprint_builder_raises_structured_exhaustion_after_validation_failures() -> (
    None
):
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},  # missing chunk_b
                    "promotions": [],
                    "answer_constraints": [],
                    "plan_steps": [],
                    "metadata": {},
                }
            ),
            json.dumps(
                {
                    "final_answer_chunk_ids": ["chunk_a", "chunk_b"],
                    "chunk_roles": {"chunk_a": "lead"},  # still missing chunk_b
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

    with pytest.raises(StructurerAttemptsExhaustedError) as exc_info:
        builder.build(_package_with_two_answer_chunks(), graph=_graph())

    assert exc_info.value.stage == "blueprint"
    assert exc_info.value.failure_type == "validation_error"
    assert exc_info.value.attempts == 2
    assert exc_info.value.max_attempts == 2
