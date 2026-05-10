"""Tests for LLMInterChunkDiscourseGraphBuilder.

Covers: valid output with multiple relations, empty chunks, LLM call failure,
parser failure, chunk selection logic, RST summaries in prompt, and correct
chunk IDs passed to parser.
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
    IntraChunkDiscoursePackage,
    IntraChunkDiscourseRelation,
)
from ragflow_lite.infrastructure.evidence.llm_inter_chunk_graph_builder import (
    LLMInterChunkDiscourseGraphBuilder,
    _build_input,
    _rst_summary,
    _select_discourse_visible_items,
)

# ── Fake client ──────────────────────────────────────────────────────────────


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
    ) -> str:
        return self._next_response(locals())

    def complete_messages_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
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
    ) -> str:
        raise self.error

    def complete_messages_json(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 262144,
        timeout_seconds: float | None = None,
    ) -> str:
        raise self.error


# ── Fixture helpers ──────────────────────────────────────────────────────────


def _evidence_item(
    chunk_id: str,
    text: str,
    *,
    order: int = 0,
    selected_for_discourse: bool | None = None,
) -> EvidenceItem:
    metadata: dict = {}
    if selected_for_discourse is not None:
        metadata["selected_for_discourse"] = selected_for_discourse
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
        metadata=metadata,
    )


def _evidence_package(*items: EvidenceItem) -> EvidencePackage:
    return EvidencePackage(
        query="How does MiniRAG handle discourse?",
        grounded_query=GroundedQuery(
            query="How does MiniRAG handle discourse?",
            answer_type_keywords=[],
            entities_from_query=[],
            metadata={},
        ),
        items=list(items),
        metadata={},
    )


def _intra_chunk_package(
    *items: EvidenceItem,
    structures: list[ChunkDiscourseStructure] | None = None,
) -> IntraChunkDiscoursePackage:
    ep = _evidence_package(*items)
    return IntraChunkDiscoursePackage(
        query=ep.query,
        evidence_package=ep,
        structures=structures or [],
        metadata={},
    )


def _valid_llm_output(*relations: dict) -> str:
    return json.dumps({"relations": list(relations)})


def _relation(
    source: str,
    target: str,
    relation_type: str = "supports",
    confidence: float = 0.8,
    rationale: str = "test rationale",
) -> dict:
    return {
        "source_chunk_id": source,
        "target_chunk_id": target,
        "relation_type": relation_type,
        "confidence": confidence,
        "rationale": rationale,
    }


# ── Tests: valid output with multiple relations ──────────────────────────────


def test_build_returns_valid_graph_with_multiple_relations() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    item_b = _evidence_item("chunk_b", "Text B", order=1, selected_for_discourse=True)
    item_c = _evidence_item("chunk_c", "Text C", order=2, selected_for_discourse=True)
    package = _intra_chunk_package(item_a, item_b, item_c)

    client = _FakeClient(
        _valid_llm_output(
            _relation("chunk_a", "chunk_b", "supports"),
            _relation("chunk_b", "chunk_c", "elaborates"),
            _relation("chunk_a", "chunk_c", "background_for", confidence=0.6),
        )
    )
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.query == "How does MiniRAG handle discourse?"
    assert graph.chunk_ids == ["chunk_a", "chunk_b", "chunk_c"]
    assert len(graph.relations) == 3
    assert graph.relations[0].source_chunk_id == "chunk_a"
    assert graph.relations[0].target_chunk_id == "chunk_b"
    assert graph.relations[0].relation_type == "supports"
    assert graph.relations[1].relation_type == "elaborates"
    assert graph.relations[2].confidence == 0.6
    assert graph.metadata["builder"] == "llm_inter_chunk_graph"
    assert graph.metadata["llm"]["model"] == "deepseek-v4-flash"
    assert graph.metadata["llm"]["reasoning_effort"] == "high"
    assert graph.metadata["llm"]["builder"] == "llm_inter_chunk_discourse_graph"


# ── Tests: empty discourse-visible chunks ────────────────────────────────────


def test_build_empty_items_returns_empty_graph() -> None:
    package = _intra_chunk_package()
    client = _FakeClient("unused")
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.chunk_ids == []
    assert graph.relations == []
    assert graph.metadata["status"] == "empty"
    assert client.calls == []


def test_build_no_items_selected_for_discourse_uses_all() -> None:
    """When no items have selected_for_discourse=True, all items are used."""
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    item_b = _evidence_item("chunk_b", "Text B", order=1)
    package = _intra_chunk_package(item_a, item_b)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.chunk_ids == ["chunk_a", "chunk_b"]
    assert client.calls  # LLM was called


def test_build_empty_output_relations_returns_graph_with_no_relations() -> None:
    """LLM returns empty relations list — valid empty graph."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)
    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.chunk_ids == ["chunk_a"]
    assert graph.relations == []
    assert graph.metadata["valid_relation_count"] == 0


# ── Tests: LLM call failure ─────────────────────────────────────────────────


def test_build_llm_call_failure_raises_processing_error() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FailingClient(RuntimeError("API connection refused"))
    builder = LLMInterChunkDiscourseGraphBuilder(client=client, max_attempts=1)

    with pytest.raises(
        ProcessingError, match="LLM inter-chunk graph builder call failed"
    ):
        builder.build(package)


def test_build_llm_call_processing_error_propagates() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FailingClient(ProcessingError("model returned empty content"))
    builder = LLMInterChunkDiscourseGraphBuilder(client=client, max_attempts=1)

    with pytest.raises(
        ProcessingError, match="LLM inter-chunk graph builder call failed"
    ):
        builder.build(package)


# ── Tests: parser failure ────────────────────────────────────────────────────


def test_build_invalid_json_raises_processing_error() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient("not valid json")
    builder = LLMInterChunkDiscourseGraphBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="not valid JSON"):
        builder.build(package)


def test_build_all_invalid_relations_raises_processing_error() -> None:
    """Strict parser raises on first invalid relation entry."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(
        _valid_llm_output(
            _relation("chunk_unknown", "chunk_a", "invalid_type"),
        )
    )
    builder = LLMInterChunkDiscourseGraphBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="unknown relation type"):
        builder.build(package)


# ── Tests: chunk selection logic ─────────────────────────────────────────────


def test_select_discourse_visible_prefers_explicit_selection() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    item_b = _evidence_item("chunk_b", "Text B", order=1, selected_for_discourse=True)
    item_c = _evidence_item("chunk_c", "Text C", order=2, selected_for_discourse=True)

    selected = _select_discourse_visible_items([item_a, item_b, item_c])

    assert [i.canonical_chunk_id for i in selected] == ["chunk_b", "chunk_c"]


def test_select_discourse_visible_uses_all_when_no_explicit() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    item_b = _evidence_item("chunk_b", "Text B", order=1)

    selected = _select_discourse_visible_items([item_a, item_b])

    assert [i.canonical_chunk_id for i in selected] == ["chunk_a", "chunk_b"]


def test_select_discourse_visible_deduplicates_by_chunk_id() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    item_a_dup = _evidence_item("chunk_a", "Text A duplicate", order=1)

    selected = _select_discourse_visible_items([item_a, item_a_dup])

    assert len(selected) == 1
    assert selected[0].canonical_chunk_id == "chunk_a"
    # Keeps first occurrence
    assert selected[0].text == "Text A"


def test_select_discourse_visible_empty_input() -> None:
    selected = _select_discourse_visible_items([])
    assert selected == []


def test_build_only_selected_for_discourse_chunks_sent_to_llm() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    item_b = _evidence_item("chunk_b", "Text B", order=1)
    item_c = _evidence_item("chunk_c", "Text C", order=2, selected_for_discourse=True)
    package = _intra_chunk_package(item_a, item_b, item_c)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.chunk_ids == ["chunk_a", "chunk_c"]
    input_text = client.calls[0]["input_text"]
    assert "chunk_a" in input_text
    assert "chunk_c" in input_text
    assert "chunk_b" not in input_text


# ── Tests: RST summaries in prompt ───────────────────────────────────────────


def test_build_includes_rst_summary_when_structure_present() -> None:
    item_a = _evidence_item("chunk_a", "MiniRAG retrieves evidence.", order=0)
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_test",
        units=[
            DiscourseUnit(
                unit_id="unit_main_0",
                canonical_chunk_id="chunk_a",
                text="MiniRAG retrieves evidence.",
                order=0,
                role="main",
            ),
            DiscourseUnit(
                unit_id="unit_support_1",
                canonical_chunk_id="chunk_a",
                text="Graph paths explain relevance.",
                order=1,
                role="support",
            ),
        ],
        relations=[
            IntraChunkDiscourseRelation(
                relation_id="rel_0",
                canonical_chunk_id="chunk_a",
                source_unit_id="unit_support_1",
                target_unit_id="unit_main_0",
                relation_type="supports",
                weight=1.0,
            ),
        ],
        main_unit_ids=["unit_main_0"],
        supporting_unit_ids=["unit_support_1"],
        metadata={},
    )
    package = _intra_chunk_package(item_a, structures=[structure])

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "rst_summary:" in input_text
    assert "main: MiniRAG retrieves evidence." in input_text
    assert "intra_relations: supports(1)" in input_text


def test_build_omits_rst_summary_when_no_structure() -> None:
    item_a = _evidence_item("chunk_a", "Plain text chunk.", order=0)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "rst_summary" not in input_text


def test_build_omits_rst_summary_for_chunks_without_structure() -> None:
    item_a = _evidence_item("chunk_a", "Has structure.", order=0)
    item_b = _evidence_item("chunk_b", "No structure.", order=1)
    structure_a = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_test",
        units=[
            DiscourseUnit(
                unit_id="unit_0",
                canonical_chunk_id="chunk_a",
                text="Has structure.",
                order=0,
                role="main",
            ),
        ],
        relations=[],
        main_unit_ids=["unit_0"],
        supporting_unit_ids=[],
        metadata={},
    )
    package = _intra_chunk_package(item_a, item_b, structures=[structure_a])

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(package)

    input_text = client.calls[0]["input_text"]
    # The prompt is "query: ...\n\n---\n\nCHUNK[1]...\n\n---\n\nCHUNK[2]..."
    # chunk_a (index 1) has structure, chunk_b (index 2) does not.
    # Use the chunk identifiers to locate each section.
    parts = input_text.split("---")
    # Find the part containing chunk_a and the part containing chunk_b
    chunk_a_part = [p for p in parts if "CHUNK[1] id=chunk_a" in p][0]
    chunk_b_part = [p for p in parts if "CHUNK[2] id=chunk_b" in p][0]
    assert "rst_summary" in chunk_a_part
    assert "rst_summary" not in chunk_b_part


# ── Tests: correct chunk IDs passed to parser ────────────────────────────────


def test_build_passes_correct_chunk_ids_to_parser() -> None:
    """Verify chunk_ids in the graph match the discourse-visible items."""
    item_a = _evidence_item("chunk_x", "Text X", order=0, selected_for_discourse=True)
    item_b = _evidence_item("chunk_y", "Text Y", order=1, selected_for_discourse=True)
    package = _intra_chunk_package(item_a, item_b)

    client = _FakeClient(
        _valid_llm_output(
            _relation("chunk_x", "chunk_y", "elaborates"),
        )
    )
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert set(graph.chunk_ids) == {"chunk_x", "chunk_y"}
    # Parser validated that source/target are in the chunk_ids set
    assert graph.relations[0].source_chunk_id == "chunk_x"
    assert graph.relations[0].target_chunk_id == "chunk_y"


def test_build_unknown_chunk_id_raises_processing_error() -> None:
    """Strict parser raises on unknown chunk ID immediately."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(
        _valid_llm_output(
            _relation("chunk_a", "chunk_unknown", "supports"),
        )
    )
    builder = LLMInterChunkDiscourseGraphBuilder(client=client, max_attempts=1)

    with pytest.raises(ProcessingError, match="unknown target chunk"):
        builder.build(package)


# ── Tests: prompt format ─────────────────────────────────────────────────────


def test_build_prompt_contains_stable_identifiers() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    item_b = _evidence_item("chunk_b", "Text B", order=1)
    package = _intra_chunk_package(item_a, item_b)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(package)

    input_text = client.calls[0]["input_text"]
    assert "CHUNK[1] id=chunk_a" in input_text
    assert "CHUNK[2] id=chunk_b" in input_text
    assert "text: Text A" in input_text
    assert "text: Text B" in input_text


def test_build_instructions_contain_relation_types() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    builder.build(package)

    instructions = client.calls[0]["instructions"]
    assert "supports" in instructions
    assert "contradicts" in instructions
    assert "elaborates" in instructions
    assert "motivates" in instructions
    assert "justifies" in instructions
    assert "relation_type" in instructions


# ── Tests: _rst_summary helper ───────────────────────────────────────────────


def test_rst_summary_with_main_units_and_relations() -> None:
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_test",
        units=[
            DiscourseUnit(
                unit_id="u0",
                canonical_chunk_id="chunk_a",
                text="Main claim.",
                order=0,
                role="main",
            ),
            DiscourseUnit(
                unit_id="u1",
                canonical_chunk_id="chunk_a",
                text="Supporting detail.",
                order=1,
                role="support",
            ),
        ],
        relations=[
            IntraChunkDiscourseRelation(
                relation_id="r0",
                canonical_chunk_id="chunk_a",
                source_unit_id="u1",
                target_unit_id="u0",
                relation_type="supports",
                weight=1.0,
            ),
            IntraChunkDiscourseRelation(
                relation_id="r1",
                canonical_chunk_id="chunk_a",
                source_unit_id="u1",
                target_unit_id="u0",
                relation_type="elaborates",
                weight=0.8,
            ),
        ],
        main_unit_ids=["u0"],
        supporting_unit_ids=["u1"],
        metadata={},
    )

    summary = _rst_summary(structure)

    assert "main: Main claim." in summary
    assert "intra_relations:" in summary
    assert "elaborates(1)" in summary
    assert "supports(1)" in summary


def test_rst_summary_empty_structure() -> None:
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_test",
        units=[],
        relations=[],
        main_unit_ids=[],
        supporting_unit_ids=[],
        metadata={},
    )

    summary = _rst_summary(structure)

    assert summary == ""


def test_rst_summary_no_main_units_but_has_relations() -> None:
    structure = ChunkDiscourseStructure(
        canonical_chunk_id="chunk_a",
        document_id="doc_test",
        units=[
            DiscourseUnit(
                unit_id="u0",
                canonical_chunk_id="chunk_a",
                text="Detail.",
                order=0,
                role="detail",
            ),
        ],
        relations=[
            IntraChunkDiscourseRelation(
                relation_id="r0",
                canonical_chunk_id="chunk_a",
                source_unit_id="u0",
                target_unit_id="u0",
                relation_type="qualifies",
                weight=1.0,
            ),
        ],
        main_unit_ids=[],
        supporting_unit_ids=[],
        metadata={},
    )

    summary = _rst_summary(structure)

    assert "main:" not in summary
    assert "intra_relations: qualifies(1)" in summary


# ── Tests: _build_input helper ───────────────────────────────────────────────


def test_build_input_formats_chunks_correctly() -> None:
    items = [
        _evidence_item("chunk_a", "First chunk.", order=0),
        _evidence_item("chunk_b", "Second chunk.", order=1),
    ]

    result = _build_input("test query", items, {})

    assert result.startswith("query: test query")
    assert "CHUNK[1] id=chunk_a" in result
    assert "text: First chunk." in result
    assert "CHUNK[2] id=chunk_b" in result
    assert "text: Second chunk." in result
    assert "---" in result


# ── Tests: constructor and client building ────────────────────────────────────


def test_constructor_requires_no_client() -> None:
    builder = LLMInterChunkDiscourseGraphBuilder(
        api_key="key",
        base_url="http://localhost",
        model="test-model",
        reasoning_effort="low",
    )
    assert builder.model == "test-model"
    assert builder.reasoning_effort == "low"


def test_build_client_raises_without_api_key() -> None:
    builder = LLMInterChunkDiscourseGraphBuilder(
        base_url="http://localhost",
    )
    item = _evidence_item("chunk_a", "Text", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item)

    with pytest.raises(ProcessingError, match="api_key and base_url"):
        builder.build(package)


def test_build_client_raises_without_base_url() -> None:
    builder = LLMInterChunkDiscourseGraphBuilder(
        api_key="key",
    )
    item = _evidence_item("chunk_a", "Text", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item)

    with pytest.raises(ProcessingError, match="api_key and base_url"):
        builder.build(package)


def test_build_with_prebuilt_client_skips_client_construction() -> None:
    item = _evidence_item("chunk_a", "Text A", order=0)
    package = _intra_chunk_package(item)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert graph.chunk_ids == ["chunk_a"]
    assert len(client.calls) == 1


# ── Tests: safe provenance metadata ──────────────────────────────────────────


def _metadata_as_str(meta: dict) -> str:
    """Flatten metadata dict to a single string for key-scanning assertions."""
    return json.dumps(meta)


def test_provenance_includes_provider_and_model() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        model="deepseek-v4-flash",
        reasoning_effort="high",
        provider="deepseek",
    )

    graph = builder.build(package)

    llm = graph.metadata["llm"]
    assert llm["provider"] == "deepseek"
    assert llm["model"] == "deepseek-v4-flash"
    assert llm["reasoning_effort"] == "high"
    assert llm["builder"] == "llm_inter_chunk_discourse_graph"


def test_provenance_includes_base_url_host() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        base_url="https://api.deepseek.com/v1/chat/completions",
    )

    graph = builder.build(package)

    llm = graph.metadata["llm"]
    assert llm["base_url_host"] == "api.deepseek.com"


def test_provenance_no_base_url_host_when_absent() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    builder = LLMInterChunkDiscourseGraphBuilder(client=client)

    graph = builder.build(package)

    assert "base_url_host" not in graph.metadata["llm"]


def test_provenance_never_includes_api_key() -> None:
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(_valid_llm_output())
    # 传入包含敏感信息的 api_key 和 base_url
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        api_key="sk-super-secret-key-12345",
        base_url="https://api.deepseek.com/v1",
    )

    graph = builder.build(package)

    meta_str = _metadata_as_str(graph.metadata)
    assert "sk-super-secret-key-12345" not in meta_str
    assert "api_key" not in meta_str


def test_provenance_default_provider_is_deepseek() -> None:
    builder = LLMInterChunkDiscourseGraphBuilder()
    assert builder.provider == "deepseek"


def test_provenance_in_empty_graph_fallback() -> None:
    package = _intra_chunk_package()

    builder = LLMInterChunkDiscourseGraphBuilder(
        model="test-model",
        reasoning_effort="low",
        provider="custom-provider",
        base_url="https://example.com/api",
    )

    graph = builder.build(package)

    assert graph.metadata["status"] == "empty"
    llm = graph.metadata["llm"]
    assert llm["provider"] == "custom-provider"
    assert llm["model"] == "test-model"
    assert llm["reasoning_effort"] == "low"
    assert llm["builder"] == "llm_inter_chunk_discourse_graph"
    assert llm["base_url_host"] == "example.com"


def test_provenance_empty_graph_no_api_key() -> None:
    package = _intra_chunk_package()

    builder = LLMInterChunkDiscourseGraphBuilder(
        api_key="sk-secret-for-empty-path",
        base_url="https://api.example.com",
    )

    graph = builder.build(package)

    meta_str = _metadata_as_str(graph.metadata)
    assert "sk-secret-for-empty-path" not in meta_str


# ── Tests: validation repair and timeout retry ────────────────────────────────


def test_graph_builder_repairs_unknown_target_with_multiturn_messages() -> None:
    """First response has unknown target_chunk_id, repair returns valid graph."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    item_b = _evidence_item("chunk_b", "Text B", order=1, selected_for_discourse=True)
    package = _intra_chunk_package(item_a, item_b)

    client = _FakeClient(
        responses=[
            _valid_llm_output(
                _relation("chunk_a", "chunk_unknown", "supports"),
            ),
            _valid_llm_output(
                _relation("chunk_a", "chunk_b", "supports"),
            ),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    graph = builder.build(package)

    assert len(graph.relations) == 1
    assert graph.relations[0].target_chunk_id == "chunk_b"
    assert len(client.calls) == 2
    # Second call should be message-based (repair)
    repair_call = client.calls[1]
    assert repair_call.get("messages") is not None
    messages = repair_call["messages"]
    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert messages[3]["role"] == "user"
    # Feedback should contain validation error, not repeat the original query
    assert "query:" not in messages[3]["content"]
    assert "Do not output a patch" in messages[3]["content"]


def test_graph_builder_raises_after_repair_attempts_exhausted() -> None:
    """Both attempts return invalid JSON with unknown target, builder raises."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(
        responses=[
            _valid_llm_output(
                _relation("chunk_a", "chunk_unknown", "supports"),
            ),
            _valid_llm_output(
                _relation("chunk_a", "chunk_still_unknown", "supports"),
            ),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(package)


def test_graph_builder_retries_timeout_with_fresh_original_request() -> None:
    """First call times out, second call is a fresh original request (not repair)."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    item_b = _evidence_item("chunk_b", "Text B", order=1, selected_for_discourse=True)
    package = _intra_chunk_package(item_a, item_b)

    client = _FakeClient(
        responses=[
            TimeoutError("request timed out"),
            _valid_llm_output(
                _relation("chunk_a", "chunk_b", "supports"),
            ),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    graph = builder.build(package)

    assert len(graph.relations) == 1
    assert len(client.calls) == 2
    # Second call should be fresh original (instructions+input_text based)
    second_call = client.calls[1]
    assert "instructions" in second_call
    assert "input_text" in second_call


def test_graph_builder_timeout_exhausted_raises() -> None:
    """Both attempts time out, builder raises ProcessingError."""
    item_a = _evidence_item("chunk_a", "Text A", order=0, selected_for_discourse=True)
    package = _intra_chunk_package(item_a)

    client = _FakeClient(
        responses=[
            TimeoutError("request timed out"),
            TimeoutError("request timed out"),
        ]
    )
    builder = LLMInterChunkDiscourseGraphBuilder(
        client=client,
        timeout_seconds=90,
        max_attempts=2,
    )

    with pytest.raises(ProcessingError, match="failed after 2 attempts"):
        builder.build(package)
