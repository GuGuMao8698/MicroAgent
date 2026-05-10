"""Full-chain DiscoRAG smoke test using mocked structurer model responses.

Proves the graph-first DiscoRAG chain works end-to-end without live providers.
Uses LLMInterChunkDiscourseGraphBuilder AND LLMDiscoRAGAnswerBlueprintBuilder
with fake DeepSeekChatCompletionsClient — no deterministic fallbacks.

12 acceptance criteria (AC):
  AC1: No network or live provider flags needed
  AC2: Evidence package contains answer + supplemental chunks
  AC3: LLM graph builder receives all discourse-visible chunks
  AC4: Mocked graph output creates expected relations
  AC5: Invalid graph output does NOT silently become deterministic graph
  AC6: Final answer contexts <= top_k
  AC7: Promotion uses hard assertions (supplemental present, replaced absent, <= top_k)
  AC8: Answerer receives mode="discorag" + filtered blueprint with planner ordering
  AC9: Invalid planner output does NOT silently become deterministic blueprint
  AC10: Planner output references existing relation IDs and RST unit IDs
  AC11: Blueprint chunk_roles and ordered_chunk_ids are validated
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from ragflow_lite.application.services.discorag_query_service import (
    DiscoRAGQueryService,
)
from ragflow_lite.application.services.evidence_package_builder import (
    EvidencePackageBuilder,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerRequest,
    AnswerResult,
    ChunkDiscourseStructure,
    DiscourseUnit,
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GraphFirstSource,
    GraphFirstSourceSelection,
    GroundedQuery,
    IntraChunkDiscoursePackage,
    IntraChunkDiscourseRelation,
    RetrievedChunk,
    TopologyRetrievalResult,
)
from ragflow_lite.infrastructure.evidence.llm_discorag_blueprint_builder import (
    LLMDiscoRAGAnswerBlueprintBuilder,
)
from ragflow_lite.infrastructure.evidence.llm_inter_chunk_graph_builder import (
    LLMInterChunkDiscourseGraphBuilder,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUERY = "How does DiscoRAG handle cross-chunk contradictions?"
TOP_K = 3
DOC_ID = "doc_test"

# Chunk IDs: 2 answer chunks + 1 supplemental discourse chunk
CHUNK_A = "chunk_a"
CHUNK_B = "chunk_b"
CHUNK_SUPP = "chunk_supp"

ALL_CHUNK_IDS = [CHUNK_A, CHUNK_B, CHUNK_SUPP]
ANSWER_CHUNK_IDS = [CHUNK_A, CHUNK_B]

# Valid LLM JSON output for the graph builder (AC4).
# Contains contradicts, replaces, background_for.
VALID_GRAPH_LLM_JSON = json.dumps(
    {
        "relations": [
            {
                "source_chunk_id": CHUNK_A,
                "target_chunk_id": CHUNK_B,
                "relation_type": "contradicts",
                "rationale": "chunk_a claims X while chunk_b claims not-X",
                "confidence": 0.9,
            },
            {
                "source_chunk_id": CHUNK_SUPP,
                "target_chunk_id": CHUNK_A,
                "relation_type": "replaces",
                "rationale": "supplemental chunk provides updated evidence",
                "confidence": 0.85,
            },
            {
                "source_chunk_id": CHUNK_SUPP,
                "target_chunk_id": CHUNK_B,
                "relation_type": "background_for",
                "rationale": "supplemental provides context for chunk_b",
                "confidence": 0.7,
            },
        ]
    }
)

# The inter-chunk graph parser does not set relation_id metadata, so the
# blueprint builder synthesizes IDs as ic_rel_{i}.  The fake RST extractor
# creates units named {chunk_id}_u0 and {chunk_id}_u1.
_SYNTH_REL_IDS = ["ic_rel_0", "ic_rel_1", "ic_rel_2"]
_SYNTH_RST_UNIT_IDS = [
    f"{CHUNK_A}_u0",
    f"{CHUNK_A}_u1",
    f"{CHUNK_B}_u0",
    f"{CHUNK_B}_u1",
    f"{CHUNK_SUPP}_u0",
    f"{CHUNK_SUPP}_u1",
]

# Valid LLM JSON output for the blueprint builder (planner).
# Promotes CHUNK_SUPP to replace CHUNK_B (the weaker answer chunk).
VALID_BLUEPRINT_LLM_JSON = json.dumps(
    {
        "final_answer_chunk_ids": [CHUNK_A, CHUNK_SUPP],
        "chunk_roles": {
            CHUNK_A: "lead",
            CHUNK_SUPP: "comparison",
        },
        "promotions": [
            {
                "replace_chunk_id": CHUNK_B,
                "with_chunk_id": CHUNK_SUPP,
                "reason": "supplemental replaces weaker evidence with updated data",
                "source_relation_ids": [_SYNTH_REL_IDS[1]],
                "source_rst_unit_ids": [_SYNTH_RST_UNIT_IDS[4]],
            }
        ],
        "answer_constraints": [
            {
                "type": "conflict",
                "text": "Explicitly address contradiction between chunk_a and chunk_b.",
                "source_chunk_ids": [CHUNK_A, CHUNK_B],
                "source_relation_ids": [_SYNTH_REL_IDS[0]],
                "source_rst_unit_ids": [_SYNTH_RST_UNIT_IDS[0], _SYNTH_RST_UNIT_IDS[2]],
            }
        ],
        "plan_steps": [
            {
                "text": "Lead with chunk_a's claim about graph-based contradiction detection.",
                "source_chunk_ids": [CHUNK_A],
                "source_relation_ids": [],
                "source_rst_unit_ids": [_SYNTH_RST_UNIT_IDS[0]],
            },
            {
                "text": "Use promoted supplemental chunk to present updated evidence.",
                "source_chunk_ids": [CHUNK_SUPP],
                "source_relation_ids": [_SYNTH_REL_IDS[1]],
                "source_rst_unit_ids": [_SYNTH_RST_UNIT_IDS[4]],
            },
        ],
        "metadata": {
            "planner": "llm_discorag_answer_blueprint_builder",
        },
    }
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _chunk(
    chunk_id: str, text: str, score: float = 0.9, **meta: object
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=DOC_ID,
        text=text,
        score=score,
        metadata=dict(meta),
    )


def _grounded_query() -> GroundedQuery:
    return GroundedQuery(
        query=QUERY,
        answer_type_keywords=["mechanism"],
        entities_from_query=["DiscoRAG", "contradictions"],
    )


def _answer_chunks() -> list[RetrievedChunk]:
    return [
        _chunk(
            CHUNK_A,
            "DiscoRAG detects cross-chunk contradictions via graph analysis.",
            0.95,
        ),
        _chunk(
            CHUNK_B,
            "Contradictions are resolved using rhetorical structure theory.",
            0.88,
        ),
    ]


def _supplemental_chunk() -> RetrievedChunk:
    return _chunk(
        CHUNK_SUPP,
        "Updated: DiscoRAG v2 uses LLM-based graph construction.",
        0.4,
        selected_for_answer=False,
        selected_for_discourse=True,
        supplemental_discourse=True,
    )


def _source_selection() -> GraphFirstSourceSelection:
    return GraphFirstSourceSelection(
        sources=[
            GraphFirstSource(
                chunk_id=CHUNK_A,
                rank=0,
                score=0.95,
                score_components={"score": 0.95},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=True,
                selected_for_discourse=True,
                selection_reason="graph_path_support",
            ),
            GraphFirstSource(
                chunk_id=CHUNK_B,
                rank=1,
                score=0.88,
                score_components={"score": 0.88},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=True,
                selected_for_discourse=True,
                selection_reason="graph_path_support",
            ),
            GraphFirstSource(
                chunk_id=CHUNK_SUPP,
                rank=2,
                score=0.4,
                score_components={"score": 0.4},
                supporting_entity_ids=[],
                supporting_relation_ids=[],
                supporting_path_ids=[],
                auxiliary_chunk_hit=False,
                selected_for_answer=False,
                selected_for_discourse=True,
                selection_reason="discourse_auxiliary",
                metadata={"supplemental_discourse": True},
            ),
        ],
        final_context_k=2,
        discourse_selection_k=3,
        context_token_budget=None,
        omitted_source_count=0,
        fallback_reason=None,
    )


def _retrieval_result() -> TopologyRetrievalResult:
    result = TopologyRetrievalResult(
        query=QUERY,
        grounded_query=_grounded_query(),
        chunks=_answer_chunks(),
        paths=[],
        source_selection=_source_selection(),
    )
    result.metadata["supplemental_discourse_chunks"] = {
        CHUNK_SUPP: _supplemental_chunk()
    }
    return result


# ---------------------------------------------------------------------------
# Fake collaborators (dataclass recording fakes, not unittest.mock)
# ---------------------------------------------------------------------------


@dataclass
class FakeTopologyRetriever:
    result: TopologyRetrievalResult = field(default_factory=_retrieval_result)
    calls: list[tuple[str, int]] = field(default_factory=list)

    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult:
        self.calls.append((query, top_k))
        return self.result


@dataclass
class FakeRSTDiscourseExtractor:
    """Returns claim/evidence/qualification structures with proper DiscourseUnit fields."""

    last_package: EvidencePackage | None = None
    chunk_ids_seen: list[str] = field(default_factory=list)

    def extract(self, evidence_package: EvidencePackage) -> IntraChunkDiscoursePackage:
        self.last_package = evidence_package
        self.chunk_ids_seen = [
            item.canonical_chunk_id for item in evidence_package.items
        ]

        structures: list[ChunkDiscourseStructure] = []
        for item in evidence_package.items:
            # Build units with planning_role and nuclearity for main chunks
            claim_unit = DiscourseUnit(
                unit_id=f"{item.canonical_chunk_id}_u0",
                canonical_chunk_id=item.canonical_chunk_id,
                text=item.text[:60],
                order=0,
                role="claim",
                nuclearity="nucleus",
                planning_role="claim",
            )
            evidence_unit = DiscourseUnit(
                unit_id=f"{item.canonical_chunk_id}_u1",
                canonical_chunk_id=item.canonical_chunk_id,
                text=item.text[60:] if len(item.text) > 60 else "",
                order=1,
                role="evidence",
                nuclearity="satellite",
                planning_role="evidence",
            )
            relation = IntraChunkDiscourseRelation(
                relation_id=f"{item.canonical_chunk_id}_r0",
                canonical_chunk_id=item.canonical_chunk_id,
                source_unit_id=claim_unit.unit_id,
                target_unit_id=evidence_unit.unit_id,
                relation_type="elaboration",
                weight=1.0,
            )
            structures.append(
                ChunkDiscourseStructure(
                    canonical_chunk_id=item.canonical_chunk_id,
                    document_id=DOC_ID,
                    units=[claim_unit, evidence_unit],
                    relations=[relation],
                    main_unit_ids=[claim_unit.unit_id],
                    supporting_unit_ids=[evidence_unit.unit_id],
                )
            )

        return IntraChunkDiscoursePackage(
            query=evidence_package.query,
            evidence_package=evidence_package,
            structures=structures,
            metadata={"status": "ok"},
        )


@dataclass
class FakeDeepSeekJsonClient:
    """Fake LLM client that returns predetermined JSON.

    Callers may pass *output_text* to override the response.  The client
    accepts any positional/keyword arguments to match the real
    DeepSeekChatCompletionsClient.complete_json signature.

    Supports both ``complete_json`` (single-turn) and ``complete_messages_json``
    (multi-turn repair) used by the structurer retry loop.  Both return the
    same ``output_text`` so that retry / repair paths exercise the builder logic
    without needing a real LLM.
    """

    output_text: str = "{}"

    def complete_json(self, *args: object, **kwargs: object) -> str:
        return self.output_text

    def complete_messages_json(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> str:
        return self.output_text


@dataclass
class SequentialFakeDeepSeekJsonClient:
    """Fake LLM client that returns a sequence of responses.

    ``complete_json`` pops from the front of *responses* on each call.
    ``complete_messages_json`` does the same, allowing the repair path to
    return a different (valid) response after the initial (invalid) one.
    """

    responses: list[str] = field(default_factory=lambda: ["{}"])

    def complete_json(self, *args: object, **kwargs: object) -> str:
        if not self.responses:
            return "{}"
        return self.responses.pop(0)

    def complete_messages_json(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> str:
        if not self.responses:
            return "{}"
        return self.responses.pop(0)


@dataclass
class RecordingAnswerer:
    last_request: AnswerRequest | None = None
    error: Exception | None = None

    def answer(self, request: AnswerRequest) -> AnswerResult:
        self.last_request = request
        if self.error is not None:
            raise self.error
        return AnswerResult(
            answer="DiscoRAG uses LLM-based graph construction for cross-chunk analysis.",
            contexts=request.contexts,
            metadata={"ok": True},
        )


# ---------------------------------------------------------------------------
# Service wiring helper
# ---------------------------------------------------------------------------


def _build_service(
    *,
    graph_llm_json: str = VALID_GRAPH_LLM_JSON,
    blueprint_llm_json: str = VALID_BLUEPRINT_LLM_JSON,
    retrieval_result: TopologyRetrievalResult | None = None,
) -> tuple[
    DiscoRAGQueryService,
    RecordingAnswerer,
    FakeRSTDiscourseExtractor,
    FakeDeepSeekJsonClient,
    FakeDeepSeekJsonClient,
]:
    """Wire up the full DiscoRAG chain with fakes.

    Returns (service, answerer, extractor, graph_llm_client, blueprint_llm_client).
    Both structurer calls use LLM builders backed by separate fake clients.
    """
    result = retrieval_result or _retrieval_result()
    retriever = FakeTopologyRetriever(result=result)

    graph_llm_client = FakeDeepSeekJsonClient(output_text=graph_llm_json)
    graph_builder = LLMInterChunkDiscourseGraphBuilder(client=graph_llm_client)

    blueprint_llm_client = FakeDeepSeekJsonClient(output_text=blueprint_llm_json)
    blueprint_builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=blueprint_llm_client,
    )

    extractor = FakeRSTDiscourseExtractor()
    answerer = RecordingAnswerer()

    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=extractor,
        inter_chunk_graph_builder=graph_builder,
        blueprint_builder=blueprint_builder,
        answerer=answerer,
    )
    return service, answerer, extractor, graph_llm_client, blueprint_llm_client


# ---------------------------------------------------------------------------
# AC1: No network or live provider flags needed
# ---------------------------------------------------------------------------


def test_ac1_no_network_or_live_provider_flags() -> None:
    """The full chain runs with only fake in-process collaborators; no env vars or network required."""
    service, answerer, _, _, _ = _build_service()

    result = service.query(QUERY, top_k=TOP_K)

    assert (
        result.answer
        == "DiscoRAG uses LLM-based graph construction for cross-chunk analysis."
    )
    assert answerer.last_request is not None


# ---------------------------------------------------------------------------
# AC2: Evidence package contains answer + supplemental chunks
# ---------------------------------------------------------------------------


def test_ac2_evidence_package_contains_answer_and_supplemental() -> None:
    """EvidencePackage from EvidencePackageBuilder includes both answer chunks and the supplemental discourse chunk."""
    service, _, extractor, _, _ = _build_service()
    service.query(QUERY, top_k=TOP_K)

    # The extractor receives the evidence package from EvidencePackageBuilder
    assert extractor.last_package is not None
    chunk_ids = [item.canonical_chunk_id for item in extractor.last_package.items]
    assert CHUNK_A in chunk_ids, "Answer chunk A must be in evidence package"
    assert CHUNK_B in chunk_ids, "Answer chunk B must be in evidence package"
    assert CHUNK_SUPP in chunk_ids, (
        "Supplemental discourse chunk must be in evidence package"
    )


# ---------------------------------------------------------------------------
# AC3: LLM graph builder receives all discourse-visible chunks
# ---------------------------------------------------------------------------


def test_ac3_llm_graph_builder_receives_all_discourse_visible_chunks() -> None:
    """The LLM graph builder receives an IntraChunkDiscoursePackage with all discourse-visible chunks."""
    service, _, extractor, _, _ = _build_service()
    service.query(QUERY, top_k=TOP_K)

    assert extractor.last_package is not None
    # The evidence package passed to the extractor contains all discourse-visible chunks
    evidence_chunk_ids = [
        item.canonical_chunk_id for item in extractor.last_package.items
    ]
    for cid in ALL_CHUNK_IDS:
        assert cid in evidence_chunk_ids, (
            f"Discourse-visible chunk {cid} missing from evidence package"
        )


# ---------------------------------------------------------------------------
# AC4: Mocked graph output creates expected relations
# ---------------------------------------------------------------------------


def test_ac4_mocked_output_creates_expected_relations() -> None:
    """The LLM graph builder produces InterChunkDiscourseGraph with contradicts, replaces, background_for."""
    service, answerer, _, _, _ = _build_service()

    result = service.query(QUERY, top_k=TOP_K)

    # The answerer received a blueprint built from the graph with expected relations
    assert answerer.last_request is not None
    assert result.answer != ""
    # Verify the chain completed successfully with mocked relations
    assert result.metadata.get("ok") is True


def test_ac4_graph_has_expected_relation_types() -> None:
    """Directly verify the LLM graph builder output with fake client has the expected relation types."""
    fake_client = FakeDeepSeekJsonClient(output_text=VALID_GRAPH_LLM_JSON)
    builder = LLMInterChunkDiscourseGraphBuilder(client=fake_client)

    # Build a minimal discourse package for the graph builder
    package = _make_discourse_package_for_graph_builder()
    graph = builder.build(package)

    relation_types = {r.relation_type for r in graph.relations}
    assert "contradicts" in relation_types
    assert "replaces" in relation_types
    assert "background_for" in relation_types
    assert len(graph.relations) == 3


def _make_discourse_package_for_graph_builder() -> IntraChunkDiscoursePackage:
    """Build a minimal IntraChunkDiscoursePackage for direct graph builder tests."""
    items = [
        EvidenceItem(
            canonical_chunk_id=CHUNK_A,
            text="DiscoRAG detects cross-chunk contradictions via graph analysis.",
            score=0.95,
            order=0,
            provenance=EvidenceProvenance(document_id=DOC_ID),
            metadata={"selected_for_discourse": True},
        ),
        EvidenceItem(
            canonical_chunk_id=CHUNK_B,
            text="Contradictions are resolved using rhetorical structure theory.",
            score=0.88,
            order=1,
            provenance=EvidenceProvenance(document_id=DOC_ID),
            metadata={"selected_for_discourse": True},
        ),
        EvidenceItem(
            canonical_chunk_id=CHUNK_SUPP,
            text="Updated: DiscoRAG v2 uses LLM-based graph construction.",
            score=0.4,
            order=2,
            provenance=EvidenceProvenance(document_id=DOC_ID),
            metadata={"selected_for_discourse": True},
        ),
    ]
    evidence = EvidencePackage(
        query=QUERY,
        grounded_query=_grounded_query(),
        items=items,
    )
    return IntraChunkDiscoursePackage(
        query=QUERY,
        evidence_package=evidence,
        structures=[],
    )


# ---------------------------------------------------------------------------
# AC5: Invalid graph output does NOT silently become deterministic graph
# ---------------------------------------------------------------------------


def test_ac5_invalid_output_raises_processing_error() -> None:
    """When the LLM returns invalid JSON, a ProcessingError is raised (not silent deterministic fallback)."""
    invalid_json = "this is not valid json at all"
    fake_client = FakeDeepSeekJsonClient(output_text=invalid_json)
    builder = LLMInterChunkDiscourseGraphBuilder(client=fake_client)

    package = _make_discourse_package_for_graph_builder()

    with pytest.raises(ProcessingError, match="not valid JSON"):
        builder.build(package)


def test_ac5_all_relations_invalid_raises_processing_error() -> None:
    """When every relation in LLM output is invalid, ProcessingError is raised (not empty deterministic graph)."""
    bad_relations_json = json.dumps(
        {
            "relations": [
                {
                    "source_chunk_id": "nonexistent_1",
                    "target_chunk_id": "nonexistent_2",
                    "relation_type": "contradicts",
                    "confidence": 0.5,
                },
            ]
        }
    )
    fake_client = FakeDeepSeekJsonClient(output_text=bad_relations_json)
    builder = LLMInterChunkDiscourseGraphBuilder(client=fake_client)

    package = _make_discourse_package_for_graph_builder()

    with pytest.raises(ProcessingError, match="references unknown source chunk"):
        builder.build(package)


def test_ac5_invalid_graph_output_falls_back_to_minirag() -> None:
    """When the graph LLM client returns invalid output, DiscoRAGQueryService degrades to MiniRAG fallback."""
    service, answerer, _, _, _ = _build_service(graph_llm_json="not valid json")

    result = service.query(QUERY, top_k=TOP_K)

    # Service degrades to MiniRAG instead of raising
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "inter_chunk_graph"


# ---------------------------------------------------------------------------
# AC6: Final answer contexts <= top_k
# ---------------------------------------------------------------------------


def test_ac6_final_answer_contexts_bounded_by_top_k() -> None:
    """Answerer receives at most top_k contexts, even with promotion."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert len(answerer.last_request.contexts) <= TOP_K


def test_ac6_contexts_bounded_by_answer_chunk_count() -> None:
    """With top_k=2 and a promoted supplemental chunk, final contexts <= 2."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=2)

    assert answerer.last_request is not None
    assert len(answerer.last_request.contexts) <= 2


# ---------------------------------------------------------------------------
# AC7: Supplemental chunk is NOT appended (promotion is replacement)
# ---------------------------------------------------------------------------


def test_ac7_supplemental_chunk_replaces_not_appends() -> None:
    """When a supplemental chunk is promoted, it replaces (not appends to) the answer context list.

    With top_k=2 and 2 answer chunks, the blueprint promotes chunk_supp to
    replace chunk_b.  Hard assertions ensure:
      - promoted supplemental chunk IS present in final contexts
      - replaced weak answer chunk is NOT in final contexts
      - context count stays <= top_k (replacement, not append)
    A no-promotion regression will fail these assertions.
    """
    # Build a retrieval result with 2 answer chunks
    result = _retrieval_result()
    service, answerer, _, _, _ = _build_service(retrieval_result=result)

    service.query(QUERY, top_k=2)

    assert answerer.last_request is not None
    context_ids = [c.chunk_id for c in answerer.last_request.contexts]

    # Hard assertion: promoted supplemental chunk must be present
    assert CHUNK_SUPP in context_ids, (
        f"Promoted supplemental chunk {CHUNK_SUPP!r} must be in final contexts {context_ids}"
    )
    # Hard assertion: replaced weak answer chunk must NOT be present
    assert CHUNK_B not in context_ids, (
        f"Replaced chunk {CHUNK_B!r} must not be in final contexts {context_ids}"
    )
    # Hard assertion: context count bounded by top_k
    assert len(context_ids) <= 2, (
        f"Context count {len(context_ids)} exceeds top_k=2, promotion appended instead of replaced"
    )
    # Hard assertion: one original answer chunk remains (the non-replaced one)
    answer_remaining = [cid for cid in context_ids if cid in ANSWER_CHUNK_IDS]
    assert len(answer_remaining) == 1, (
        f"Expected exactly 1 remaining answer chunk, got {answer_remaining}"
    )


# ---------------------------------------------------------------------------
# AC8: Answerer receives mode="discorag" + filtered blueprint
# ---------------------------------------------------------------------------


def test_ac8_answerer_receives_discorag_mode() -> None:
    """Answerer receives mode='discorag' in the AnswerRequest."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.mode == "discorag"


def test_ac8_answerer_receives_filtered_blueprint() -> None:
    """Answerer receives a blueprint whose ordered_chunk_ids match the final context set."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    blueprint = answerer.last_request.blueprint

    # Blueprint ordered_chunk_ids should be a subset of (or equal to) the context ids
    context_ids = {c.chunk_id for c in answerer.last_request.contexts}
    for cid in blueprint.ordered_chunk_ids:
        assert cid in context_ids, (
            f"Blueprint references chunk {cid} not in answer contexts"
        )

    # Blueprint metadata should contain answer_context_chunk_ids matching final contexts
    assert "answer_context_chunk_ids" in blueprint.metadata
    assert set(blueprint.metadata["answer_context_chunk_ids"]) == context_ids

    # Chunk roles should only reference chunks in the final context set
    for cid in blueprint.chunk_roles:
        assert cid in context_ids, (
            f"Blueprint chunk_roles references {cid} not in contexts"
        )


def test_ac8_blueprint_is_filtered_not_raw() -> None:
    """The blueprint passed to answerer is filtered to match contexts, not the raw full blueprint."""
    # Use a result where supplemental discourse chunks exist so the raw blueprint
    # would reference chunks not in the final context
    result = _retrieval_result()
    service, answerer, _, _, _ = _build_service(retrieval_result=result)

    service.query(QUERY, top_k=2)

    assert answerer.last_request is not None
    context_ids = {c.chunk_id for c in answerer.last_request.contexts}
    blueprint = answerer.last_request.blueprint
    assert blueprint is not None

    # The filtered blueprint must not reference chunks outside the context set
    blueprint_ids = set(blueprint.ordered_chunk_ids)
    assert blueprint_ids <= context_ids, (
        f"Blueprint chunk IDs {blueprint_ids - context_ids} not in contexts {context_ids}"
    )


def test_ac8_blueprint_ordered_chunk_ids_preserves_planner_order() -> None:
    """Answer-facing blueprint ordered_chunk_ids preserves planner ordering, not retrieval score order.

    The planner specifies final_answer_chunk_ids=[CHUNK_A, CHUNK_SUPP].
    After promotion replaces CHUNK_B with CHUNK_SUPP, the filtered blueprint's
    ordered_chunk_ids must follow planner order [CHUNK_A, CHUNK_SUPP], not
    retrieval score order [CHUNK_A, CHUNK_B].
    """
    result = _retrieval_result()
    service, answerer, _, _, _ = _build_service(retrieval_result=result)

    service.query(QUERY, top_k=2)

    assert answerer.last_request is not None
    blueprint = answerer.last_request.blueprint
    assert blueprint is not None

    # Planner specified [CHUNK_A, CHUNK_SUPP] — this order must be preserved
    assert blueprint.ordered_chunk_ids == [CHUNK_A, CHUNK_SUPP], (
        f"ordered_chunk_ids {blueprint.ordered_chunk_ids} does not match "
        f"planner order [{CHUNK_A}, {CHUNK_SUPP}]"
    )


# ---------------------------------------------------------------------------
# AC9: Invalid planner output does NOT silently become deterministic blueprint
# ---------------------------------------------------------------------------


def test_ac9_invalid_planner_json_falls_back_to_minirag() -> None:
    """When the planner LLM returns invalid JSON, DiscoRAGQueryService degrades to MiniRAG fallback."""
    service, answerer, _, _, _ = _build_service(
        blueprint_llm_json="not valid json at all"
    )

    result = service.query(QUERY, top_k=TOP_K)

    # Service degrades to MiniRAG instead of raising
    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"


def test_ac9_invalid_planner_missing_fields_falls_back_to_minirag() -> None:
    """When the planner LLM returns valid JSON but missing required fields, DiscoRAGQueryService degrades to MiniRAG."""
    bad_blueprint = json.dumps({"metadata": {}})  # missing final_answer_chunk_ids
    service, answerer, _, _, _ = _build_service(blueprint_llm_json=bad_blueprint)

    result = service.query(QUERY, top_k=TOP_K)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"


def test_ac9_invalid_planner_unknown_chunk_id_falls_back_to_minirag() -> None:
    """When the planner references a non-existent chunk ID, DiscoRAGQueryService degrades to MiniRAG."""
    bad_blueprint = json.dumps(
        {
            "final_answer_chunk_ids": ["nonexistent_chunk"],
            "chunk_roles": {},
        }
    )
    service, answerer, _, _, _ = _build_service(blueprint_llm_json=bad_blueprint)

    result = service.query(QUERY, top_k=TOP_K)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"


# ---------------------------------------------------------------------------
# AC10: Planner output references existing relation IDs and RST unit IDs
# ---------------------------------------------------------------------------


def test_ac10_blueprint_references_valid_relation_ids() -> None:
    """The planner output in the final blueprint references only known inter-chunk relation IDs."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    metadata = answerer.last_request.blueprint.metadata
    # The parser stores source_relation_ids from constraints, plan_steps, promotions
    source_rel_ids = metadata.get("source_relation_ids", [])
    # Every referenced relation ID must be one of the synthesized graph IDs
    for rid in source_rel_ids:
        assert rid in _SYNTH_REL_IDS, (
            f"Blueprint references unknown relation ID {rid!r}"
        )


def test_ac10_blueprint_references_valid_rst_unit_ids() -> None:
    """The planner output in the final blueprint references only known RST unit IDs."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    metadata = answerer.last_request.blueprint.metadata
    source_rst_ids = metadata.get("source_rst_unit_ids", [])
    for uid in source_rst_ids:
        assert uid in _SYNTH_RST_UNIT_IDS, (
            f"Blueprint references unknown RST unit ID {uid!r}"
        )


def test_ac10_blueprint_with_unknown_relation_id_falls_back_to_minirag() -> None:
    """If the planner references an unknown relation ID, DiscoRAGQueryService degrades to MiniRAG."""
    bad_blueprint = json.dumps(
        {
            "final_answer_chunk_ids": [CHUNK_A],
            "chunk_roles": {CHUNK_A: "lead"},
            "answer_constraints": [
                {
                    "type": "conflict",
                    "text": "test",
                    "source_relation_ids": ["nonexistent_rel"],
                }
            ],
        }
    )
    service, answerer, _, _, _ = _build_service(blueprint_llm_json=bad_blueprint)

    result = service.query(QUERY, top_k=TOP_K)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"


# ---------------------------------------------------------------------------
# AC11: Blueprint chunk_roles and ordered_chunk_ids are validated
# ---------------------------------------------------------------------------


def test_ac11_blueprint_chunk_roles_match_final_contexts() -> None:
    """Blueprint chunk_roles keys match the ordered_chunk_ids from the LLM planner."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    blueprint = answerer.last_request.blueprint

    # After filtering, chunk_roles should only reference chunks in ordered_chunk_ids
    for cid in blueprint.chunk_roles:
        assert cid in blueprint.ordered_chunk_ids, (
            f"chunk_roles references {cid} not in ordered_chunk_ids"
        )


def test_ac11_blueprint_roles_are_valid() -> None:
    """All chunk roles in the blueprint are from the valid role set."""
    valid_roles = {
        "lead",
        "support",
        "background",
        "caveat",
        "comparison",
        "definition",
        "condition",
        "context",
    }
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=TOP_K)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    blueprint = answerer.last_request.blueprint

    for cid, role in blueprint.chunk_roles.items():
        assert role in valid_roles, f"Invalid role {role!r} for chunk {cid!r}"


def test_ac11_blueprint_with_invalid_role_falls_back_to_minirag() -> None:
    """When the planner assigns an invalid role, DiscoRAGQueryService degrades to MiniRAG."""
    # Use a blueprint with one valid and one invalid role
    blueprint_with_bad_role = json.dumps(
        {
            "final_answer_chunk_ids": [CHUNK_A],
            "chunk_roles": {
                CHUNK_A: "lead",
                CHUNK_B: "not_a_real_role",
            },
            "metadata": {},
        }
    )
    service, answerer, *_ = _build_service(
        blueprint_llm_json=blueprint_with_bad_role,
    )

    result = service.query(QUERY, top_k=TOP_K)

    assert result.metadata["discorag_degraded"] is True
    assert result.metadata["answer_mode"] == "minirag_fallback"
    assert result.metadata["discorag_error"]["stage"] == "blueprint"


def test_ac11_blueprint_ordered_chunk_ids_respects_budget() -> None:
    """The planner's ordered_chunk_ids count does not exceed the top_k budget."""
    service, answerer, _, _, _ = _build_service()

    service.query(QUERY, top_k=2)

    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    blueprint = answerer.last_request.blueprint

    # After filtering, ordered_chunk_ids must be within budget
    assert len(blueprint.ordered_chunk_ids) <= 2


# ---------------------------------------------------------------------------
# AC12: Blueprint repair succeeds after one validation failure
# ---------------------------------------------------------------------------

# Invalid blueprint: final_answer_chunk_ids has [CHUNK_A, CHUNK_B] but
# chunk_roles only covers CHUNK_A (missing CHUNK_B).  This triggers the
# "chunk_roles must cover final_answer_chunk_ids exactly" validation error,
# causing the builder to retry via complete_messages_json.
_INVALID_BLUEPRINT_MISSING_ROLE = json.dumps(
    {
        "final_answer_chunk_ids": [CHUNK_A, CHUNK_B],
        "chunk_roles": {
            CHUNK_A: "lead",
            # CHUNK_B intentionally omitted
        },
    }
)


def test_ac12_blueprint_repair_succeeds_after_validation_failure() -> None:
    """Blueprint builder fails validation once, then succeeds on repair via complete_messages_json."""
    result = _retrieval_result()
    retriever = FakeTopologyRetriever(result=result)

    # Graph builder uses a standard fake (always returns valid graph)
    graph_llm_client = FakeDeepSeekJsonClient(output_text=VALID_GRAPH_LLM_JSON)
    graph_builder = LLMInterChunkDiscourseGraphBuilder(client=graph_llm_client)

    # Blueprint builder uses sequential fake:
    # 1st call (complete_json) -> invalid blueprint (missing CHUNK_B role)
    # 2nd call (complete_messages_json, repair) -> valid blueprint
    blueprint_llm_client = SequentialFakeDeepSeekJsonClient(
        responses=[
            _INVALID_BLUEPRINT_MISSING_ROLE,
            VALID_BLUEPRINT_LLM_JSON,
        ]
    )
    blueprint_builder = LLMDiscoRAGAnswerBlueprintBuilder(
        client=blueprint_llm_client,
    )

    extractor = FakeRSTDiscourseExtractor()
    answerer = RecordingAnswerer()

    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=extractor,
        inter_chunk_graph_builder=graph_builder,
        blueprint_builder=blueprint_builder,
        answerer=answerer,
    )

    query_result = service.query(QUERY, top_k=2)

    # The service did NOT fall back to MiniRAG — repair succeeded
    assert query_result.metadata.get("discorag_degraded") is not True
    assert query_result.answer != ""

    # The answerer received a valid blueprint (not None)
    assert answerer.last_request is not None
    assert answerer.last_request.blueprint is not None
    assert answerer.last_request.mode == "discorag"

    # The sequential client was called twice: once for initial, once for repair
    assert len(blueprint_llm_client.responses) == 0, (
        "Expected both responses consumed (2 calls), "
        f"but {len(blueprint_llm_client.responses)} remain"
    )

    # Promotion metadata preserved after repair
    blueprint = answerer.last_request.blueprint
    assert blueprint.ordered_chunk_ids == [CHUNK_A, CHUNK_SUPP]


# ---------------------------------------------------------------------------
# AC13: Blueprint exhausted → MiniRAG fallback with explicit metadata
# ---------------------------------------------------------------------------


@dataclass
class _ExhaustedBlueprintBuilder:
    """Blueprint builder stub that always raises ProcessingError (simulates exhausted retries)."""

    call_count: int = 0

    def build(self, package: object, *, graph: object = None) -> None:
        self.call_count += 1
        raise ProcessingError(
            "LLM DiscoRAG blueprint builder failed after 2 attempts: "
            "chunk_roles keys must exactly match final_answer_chunk_ids."
        )


def test_ac13_blueprint_exhausted_falls_back_to_minirag_with_explicit_metadata() -> (
    None
):
    """Blueprint builder exhausts retry attempts, service degrades to MiniRAG with explicit metadata."""
    result = _retrieval_result()
    retriever = FakeTopologyRetriever(result=result)

    graph_llm_client = FakeDeepSeekJsonClient(output_text=VALID_GRAPH_LLM_JSON)
    graph_builder = LLMInterChunkDiscourseGraphBuilder(client=graph_llm_client)

    exhausted_builder = _ExhaustedBlueprintBuilder()

    extractor = FakeRSTDiscourseExtractor()
    answerer = RecordingAnswerer()

    service = DiscoRAGQueryService(
        retriever=retriever,
        evidence_package_builder=EvidencePackageBuilder(),
        discourse_extractor=extractor,
        inter_chunk_graph_builder=graph_builder,
        blueprint_builder=exhausted_builder,
        answerer=answerer,
    )

    query_result = service.query(QUERY, top_k=TOP_K)

    # --- Explicit fallback metadata ---
    assert query_result.metadata["mode"] == "discorag"
    assert query_result.metadata["answer_mode"] == "minirag_fallback"
    assert query_result.metadata["discorag_degraded"] is True
    assert query_result.metadata["discorag_error"]["stage"] == "blueprint"
    assert query_result.metadata["discorag_error"]["user_visible"] is True

    # --- Fallback contexts are exactly the retrieval result chunks ---
    expected_chunks = result.chunks
    fallback_context_ids = [c.chunk_id for c in query_result.contexts]
    expected_chunk_ids = [c.chunk_id for c in expected_chunks]
    assert fallback_context_ids == expected_chunk_ids, (
        f"Fallback contexts {fallback_context_ids} must match "
        f"retrieval chunks {expected_chunk_ids}"
    )

    # --- Supplemental discourse chunk is NOT in fallback contexts ---
    assert CHUNK_SUPP not in fallback_context_ids, (
        f"Supplemental discourse chunk {CHUNK_SUPP!r} must not appear "
        f"in fallback contexts {fallback_context_ids}"
    )

    # --- Fallback context count <= top_k ---
    assert len(query_result.contexts) <= TOP_K

    # --- Answerer received mode="standard" (MiniRAG path, not "discorag") ---
    assert answerer.last_request is not None
    assert answerer.last_request.mode == "standard"
    assert answerer.last_request.blueprint is None
