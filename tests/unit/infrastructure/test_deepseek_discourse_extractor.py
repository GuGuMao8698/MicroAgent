from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GroundedQuery,
)
from ragflow_lite.infrastructure.evidence import (
    DeepSeekChatIntraChunkDiscourseExtractor,
)


class _FakeDeepSeekClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, str]] = []

    def complete_json(self, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return self.output_text


def _package() -> EvidencePackage:
    grounded = GroundedQuery(
        query="How does MiniRAG recover evidence?",
        answer_type_keywords=["mechanism"],
        entities_from_query=["MiniRAG"],
        metadata={"grounder": "unit"},
    )
    item = EvidenceItem(
        canonical_chunk_id="chunk_doc_alpha_0",
        text="MiniRAG first retrieves chunks. Graph paths then explain why they matter.",
        score=0.82,
        order=0,
        provenance=EvidenceProvenance(
            document_id="doc_alpha",
            filename="alpha.md",
            file_type="markdown",
            chunk_index=0,
        ),
        retained_reasons=["topology_path"],
        grounded_entities=["MiniRAG"],
        answer_type_keywords=["mechanism"],
        topology_path_ids=["path_alpha_0"],
        topology_relation_ids=["relation_alpha_0"],
        metadata={"retrieval_mode": "minirag_topology"},
    )
    return EvidencePackage(
        query=grounded.query,
        grounded_query=grounded,
        items=[item],
        metadata={"evidence_count": 1},
    )


def _package_with_two_items() -> EvidencePackage:
    package = _package()
    second = EvidenceItem(
        canonical_chunk_id="chunk_doc_alpha_1",
        text="A second chunk should not be sent when max_chunks is one.",
        score=0.4,
        order=1,
        provenance=EvidenceProvenance(
            document_id="doc_alpha",
            filename="alpha.md",
            file_type="markdown",
            chunk_index=1,
        ),
        retained_reasons=["baseline_retrieval"],
        grounded_entities=["MiniRAG"],
        answer_type_keywords=["mechanism"],
        metadata={},
    )
    package.items.append(second)
    package.metadata["evidence_count"] = 2
    return package


def _package_with_discourse_items(count: int) -> EvidencePackage:
    package = _package()
    package.items = []
    for index in range(count):
        package.items.append(
            EvidenceItem(
                canonical_chunk_id=f"chunk_doc_alpha_{index}",
                text=f"Discourse-visible chunk {index}.",
                score=1.0 - (index * 0.01),
                order=index,
                provenance=EvidenceProvenance(
                    document_id="doc_alpha",
                    filename="alpha.md",
                    file_type="markdown",
                    chunk_index=index,
                ),
                retained_reasons=["discourse_selection"],
                grounded_entities=["MiniRAG"],
                answer_type_keywords=["mechanism"],
                metadata={"selected_for_discourse": True},
            )
        )
    package.metadata["evidence_count"] = count
    package.metadata["source_selection"] = {"discourse_selection_k": count}
    return package


def _extractor_for_chunk_output(
    chunk_output: dict,
) -> DeepSeekChatIntraChunkDiscourseExtractor:
    return DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(json.dumps({"chunks": [chunk_output]})),
    )


def test_deepseek_discourse_extractor_returns_validated_structures() -> None:
    client = _FakeDeepSeekClient(
        json.dumps(
            {
                "chunks": [
                    {
                        "canonical_chunk_id": "chunk_doc_alpha_0",
                        "units": [
                            {
                                "text": "MiniRAG first retrieves chunks.",
                                "role": "main",
                                "start_char": 0,
                                "end_char": 30,
                            },
                            {
                                "text": "Graph paths then explain why they matter.",
                                "role": "support",
                                "start_char": 31,
                                "end_char": 73,
                            },
                        ],
                        "relations": [
                            {
                                "source_unit_index": 1,
                                "target_unit_index": 0,
                                "relation_type": "supports",
                                "weight": 1.0,
                            }
                        ],
                        "main_unit_indexes": [0],
                        "supporting_unit_indexes": [1],
                    }
                ]
            }
        )
    )
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        model="deepseek-v4-flash",
        reasoning_effort="high",
        client=client,
    )

    package = extractor.extract(_package())

    assert package.query == "How does MiniRAG recover evidence?"
    assert package.metadata == {
        "extractor": "deepseek_chat_intra_chunk_discourse",
        "model": "deepseek-v4-flash",
        "selected_evidence_count": 1,
        "structure_count": 1,
        "status": "ok",
        "selection_source": "prefix",
        "max_chunks": None,
        "selected_chunk_ids": ["chunk_doc_alpha_0"],
        "skipped_chunk_ids": [],
    }
    structure = package.structures[0]
    assert structure.canonical_chunk_id == "chunk_doc_alpha_0"
    assert structure.document_id == "doc_alpha"
    assert [unit.role for unit in structure.units] == ["main", "support"]
    assert structure.main_unit_ids == [structure.units[0].unit_id]
    assert structure.supporting_unit_ids == [structure.units[1].unit_id]
    assert structure.relations[0].source_unit_id == structure.units[1].unit_id
    assert structure.relations[0].target_unit_id == structure.units[0].unit_id
    assert structure.relations[0].relation_type == "supports"

    # Functional RST projections
    assert [u.nuclearity for u in structure.units] == ["nucleus", "satellite"]
    assert [u.rst_relation for u in structure.units] == ["supports", None]
    assert [u.planning_role for u in structure.units] == ["claim", "context"]

    assert len(client.calls) == 1
    assert "JSON object" in client.calls[0]["instructions"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" in client.calls[0]["input_text"]
    assert "MiniRAG first retrieves chunks" in client.calls[0]["input_text"]


def test_deepseek_discourse_extractor_default_consumes_all_discourse_items() -> None:
    client = _FakeDeepSeekClient(json.dumps({"chunks": []}))
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(client=client)

    package = extractor.extract(_package_with_discourse_items(12))

    assert package.metadata["selected_evidence_count"] == 12
    assert package.metadata["max_chunks"] is None
    assert package.metadata["selected_chunk_ids"] == [
        f"chunk_doc_alpha_{index}" for index in range(12)
    ]
    assert package.metadata["skipped_chunk_ids"] == []
    for index in range(12):
        assert (
            f"canonical_chunk_id: chunk_doc_alpha_{index}"
            in client.calls[0]["input_text"]
        )


def test_deepseek_discourse_extractor_explicit_max_chunks_reports_skipped_items() -> (
    None
):
    client = _FakeDeepSeekClient(json.dumps({"chunks": []}))
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        max_chunks=1,
    )

    package = extractor.extract(_package_with_two_items())

    assert package.metadata["selected_evidence_count"] == 1
    assert "canonical_chunk_id: chunk_doc_alpha_0" in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_1" not in client.calls[0]["input_text"]
    assert package.metadata["max_chunks"] == 1
    assert package.metadata["selected_chunk_ids"] == ["chunk_doc_alpha_0"]
    assert package.metadata["skipped_chunk_ids"] == ["chunk_doc_alpha_1"]


def test_deepseek_discourse_extractor_disabled_path_skips_model_call() -> None:
    client = _FakeDeepSeekClient("not json")
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        enabled=False,
    )

    package = extractor.extract(_package())

    assert package.structures == []
    assert package.metadata["status"] == "disabled"
    assert package.metadata["selection_source"] == "none"
    assert client.calls == []


def test_deepseek_discourse_extractor_empty_package_skips_model_call() -> None:
    evidence_package = _package()
    evidence_package.items = []
    client = _FakeDeepSeekClient("not json")
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(client=client)

    package = extractor.extract(evidence_package)

    assert package.structures == []
    assert package.metadata["status"] == "empty"
    assert package.metadata["selection_source"] == "none"
    assert client.calls == []


def test_deepseek_discourse_extractor_rejects_invalid_json() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient("not json"),
    )

    with pytest.raises(ProcessingError, match="invalid JSON"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_unknown_canonical_chunk_id() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_unknown",
                            "units": [
                                {
                                    "text": "Unexpected chunk.",
                                    "role": "main",
                                    "start_char": 0,
                                    "end_char": 17,
                                }
                            ],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            )
        )
    )

    with pytest.raises(ProcessingError, match="unknown canonical_chunk_id"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_mixed_valid_and_unknown_chunk_ids() -> (
    None
):
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [
                                {
                                    "text": "MiniRAG first retrieves chunks.",
                                    "role": "main",
                                    "start_char": 0,
                                    "end_char": 30,
                                }
                            ],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        },
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_unknown",
                            "units": [
                                {
                                    "text": "Unexpected chunk.",
                                    "role": "support",
                                    "start_char": 0,
                                    "end_char": 17,
                                }
                            ],
                            "relations": [],
                            "main_unit_indexes": [],
                            "supporting_unit_indexes": [0],
                        },
                    ]
                }
            )
        )
    )

    with pytest.raises(ProcessingError, match="unknown canonical_chunk_id"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_invalid_span() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [
                                {
                                    "text": "bad span",
                                    "role": "main",
                                    "start_char": 100,
                                    "end_char": 120,
                                }
                            ],
                            "relations": [],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            )
        )
    )

    with pytest.raises(ProcessingError, match="span is outside chunk text"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_invalid_relation_reference() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient(
            json.dumps(
                {
                    "chunks": [
                        {
                            "canonical_chunk_id": "chunk_doc_alpha_0",
                            "units": [
                                {
                                    "text": "MiniRAG first retrieves chunks.",
                                    "role": "main",
                                }
                            ],
                            "relations": [
                                {
                                    "source_unit_index": 0,
                                    "target_unit_index": 9,
                                    "relation_type": "supports",
                                    "weight": 1.0,
                                }
                            ],
                            "main_unit_indexes": [0],
                            "supporting_unit_indexes": [],
                        }
                    ]
                }
            )
        )
    )

    with pytest.raises(ProcessingError, match="target index is invalid"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_boolean_span_fields() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {
                    "text": "MiniRAG first retrieves chunks.",
                    "role": "main",
                    "start_char": False,
                    "end_char": 30,
                }
            ],
            "relations": [],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [],
        }
    )

    with pytest.raises(ProcessingError, match="start_char"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_boolean_relation_index() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "MiniRAG first retrieves chunks.", "role": "main"},
                {
                    "text": "Graph paths then explain why they matter.",
                    "role": "support",
                },
            ],
            "relations": [
                {
                    "source_unit_index": True,
                    "target_unit_index": 0,
                    "relation_type": "supports",
                    "weight": 1.0,
                }
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    with pytest.raises(ProcessingError, match="source_unit_index"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_boolean_unit_index_lists() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "MiniRAG first retrieves chunks.", "role": "main"},
            ],
            "relations": [],
            "main_unit_indexes": [True],
            "supporting_unit_indexes": [],
        }
    )

    with pytest.raises(ProcessingError, match="main_unit_indexes"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_rejects_boolean_weight() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "MiniRAG first retrieves chunks.", "role": "main"},
                {
                    "text": "Graph paths then explain why they matter.",
                    "role": "support",
                },
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": "supports",
                    "weight": False,
                }
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    with pytest.raises(ProcessingError, match="weight"):
        extractor.extract(_package())


def test_deepseek_discourse_extractor_normalizes_label_whitespace() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {
                    "text": "MiniRAG first retrieves chunks.",
                    "role": "  Main   Claim  ",
                },
                {
                    "text": "Graph paths then explain why they matter.",
                    "role": "  Supporting   Detail  ",
                },
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": "  Supports   By  ",
                    "weight": 0.75,
                }
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    package = extractor.extract(_package())

    structure = package.structures[0]
    assert [unit.role for unit in structure.units] == [
        "Main Claim",
        "Supporting Detail",
    ]
    assert structure.relations[0].relation_type == "Supports By"


def test_extract_prefers_selected_discourse_items_before_prefix() -> None:
    client = _FakeDeepSeekClient(
        json.dumps(
            {
                "chunks": [
                    {
                        "canonical_chunk_id": "chunk_doc_alpha_1",
                        "units": [
                            {
                                "text": "Discourse-visible chunk 1.",
                                "role": "main",
                                "start_char": 0,
                                "end_char": 25,
                            }
                        ],
                        "relations": [],
                        "main_unit_indexes": [0],
                        "supporting_unit_indexes": [],
                    }
                ]
            }
        )
    )
    package = _package_with_two_items()
    package.items[1].metadata["selected_for_discourse"] = True
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        max_chunks=1,
    )

    result = extractor.extract(package)

    assert [s.canonical_chunk_id for s in result.structures] == ["chunk_doc_alpha_1"]
    assert result.metadata["selected_evidence_count"] == 1
    assert result.metadata["selection_source"] == "source_selection"
    assert "canonical_chunk_id: chunk_doc_alpha_1" in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" not in client.calls[0]["input_text"]


def test_extract_with_mixed_source_selection_skips_unselected_items_without_cap() -> (
    None
):
    client = _FakeDeepSeekClient(
        json.dumps(
            {
                "chunks": [
                    {
                        "canonical_chunk_id": "chunk_doc_alpha_1",
                        "units": [
                            {
                                "text": "Discourse-visible chunk 1.",
                                "role": "main",
                                "start_char": 0,
                                "end_char": 25,
                            }
                        ],
                        "relations": [],
                        "main_unit_indexes": [0],
                        "supporting_unit_indexes": [],
                    },
                    {
                        "canonical_chunk_id": "chunk_doc_alpha_2",
                        "units": [
                            {
                                "text": "Discourse-visible chunk 2.",
                                "role": "support",
                                "start_char": 0,
                                "end_char": 25,
                            }
                        ],
                        "relations": [],
                        "main_unit_indexes": [],
                        "supporting_unit_indexes": [0],
                    },
                ]
            }
        )
    )
    package = _package_with_discourse_items(4)
    package.items[0].metadata["selected_for_discourse"] = False
    package.items[1].metadata["selected_for_discourse"] = True
    package.items[2].metadata["selected_for_discourse"] = True
    package.items[3].metadata.pop("selected_for_discourse")
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        max_chunks=None,
    )

    result = extractor.extract(package)

    assert [s.canonical_chunk_id for s in result.structures] == [
        "chunk_doc_alpha_1",
        "chunk_doc_alpha_2",
    ]
    assert result.metadata["selected_evidence_count"] == 2
    assert result.metadata["selection_source"] == "source_selection"
    assert result.metadata["max_chunks"] is None
    assert result.metadata["selected_chunk_ids"] == [
        "chunk_doc_alpha_1",
        "chunk_doc_alpha_2",
    ]
    assert result.metadata["skipped_chunk_ids"] == [
        "chunk_doc_alpha_0",
        "chunk_doc_alpha_3",
    ]
    assert "canonical_chunk_id: chunk_doc_alpha_1" in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_2" in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" not in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_3" not in client.calls[0]["input_text"]


# --- Functional RST projection tests ---


def test_rst_projection_nuclearity_joint() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Unit A.", "role": "main"},
                {"text": "Unit B.", "role": "support"},
            ],
            "relations": [],
            "main_unit_indexes": [0, 1],
            "supporting_unit_indexes": [0, 1],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert [u.nuclearity for u in structure.units] == ["joint", "joint"]


def test_rst_projection_nuclearity_neither() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Orphan unit.", "role": "detail"},
            ],
            "relations": [],
            "main_unit_indexes": [],
            "supporting_unit_indexes": [],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert structure.units[0].nuclearity is None


def test_rst_projection_planning_role_mappings() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Claim.", "role": "claim"},
                {"text": "Main.", "role": "main"},
                {"text": "Thesis.", "role": "thesis"},
                {"text": "Evidence.", "role": "evidence"},
                {"text": "Data.", "role": "data"},
                {"text": "Fact.", "role": "fact"},
                {"text": "Definition.", "role": "definition"},
                {"text": "Term.", "role": "term"},
                {"text": "Condition.", "role": "condition"},
                {"text": "Prerequisite.", "role": "prerequisite"},
                {"text": "Qualification.", "role": "qualification"},
                {"text": "Caveat.", "role": "caveat"},
                {"text": "Limitation.", "role": "limitation"},
                {"text": "Contrast.", "role": "contrast"},
                {"text": "Opposition.", "role": "opposition"},
                {"text": "Counter.", "role": "counter"},
                {"text": "Procedure.", "role": "procedure"},
                {"text": "Step.", "role": "step"},
                {"text": "Method.", "role": "method"},
                {"text": "Unknown.", "role": "background"},
                {"text": "Bizarre.", "role": "foobar"},
            ],
            "relations": [],
            "main_unit_indexes": [],
            "supporting_unit_indexes": [],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    roles = [u.planning_role for u in structure.units]
    assert roles[:3] == ["claim", "claim", "claim"]
    assert roles[3:6] == ["evidence", "evidence", "evidence"]
    assert roles[6:8] == ["definition", "definition"]
    assert roles[8:10] == ["condition", "condition"]
    assert roles[10:13] == ["qualification", "qualification", "qualification"]
    assert roles[13:16] == ["contrast", "contrast", "contrast"]
    assert roles[16:19] == ["procedure", "procedure", "procedure"]
    assert roles[19:] == ["context", "context"]


def test_rst_projection_normalizes_relation_types() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Target A.", "role": "main"},
                {"text": "Target B.", "role": "main"},
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": "elaboration",
                    "weight": 0.9,
                },
                {
                    "source_unit_index": 0,
                    "target_unit_index": 1,
                    "relation_type": "example",
                    "weight": 0.8,
                },
            ],
            "main_unit_indexes": [0, 1],
            "supporting_unit_indexes": [],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert structure.units[0].rst_relation == "elaborates"
    assert structure.units[1].rst_relation == "example_of"


def test_rst_projection_sequences_normalizes_to_temporal_next() -> None:
    """The LLM prompt lists 'sequences' as a valid relation type;
    the normalizer must map it to 'temporal_next'."""
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Step one.", "role": "main"},
                {"text": "Step two.", "role": "support"},
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": "sequences",
                    "weight": 1.0,
                },
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert structure.units[0].rst_relation == "temporal_next"


@pytest.mark.parametrize(
    "relation_type",
    ["Sequences", "SEQUENCES", " sequences ", "  SequenceS  "],
)
def test_rst_projection_sequences_alias_case_and_whitespace_tolerant(
    relation_type: str,
) -> None:
    """Normalizer strips whitespace and lowercases before lookup."""
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Step one.", "role": "main"},
                {"text": "Step two.", "role": "support"},
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": relation_type,
                    "weight": 1.0,
                },
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert structure.units[0].rst_relation == "temporal_next"


def test_rst_projection_unknown_relation_not_mapped() -> None:
    extractor = _extractor_for_chunk_output(
        {
            "canonical_chunk_id": "chunk_doc_alpha_0",
            "units": [
                {"text": "Target.", "role": "main"},
                {"text": "Source.", "role": "support"},
            ],
            "relations": [
                {
                    "source_unit_index": 1,
                    "target_unit_index": 0,
                    "relation_type": "unknown_relation",
                    "weight": 1.0,
                },
            ],
            "main_unit_indexes": [0],
            "supporting_unit_indexes": [1],
        }
    )

    structure = extractor.extract(_package()).structures[0]
    assert structure.units[0].rst_relation is None
    assert structure.relations[0].relation_type == "unknown_relation"


def test_rst_projection_preserves_existing_behavior() -> None:
    client = _FakeDeepSeekClient(
        json.dumps(
            {
                "chunks": [
                    {
                        "canonical_chunk_id": "chunk_doc_alpha_0",
                        "units": [
                            {
                                "text": "MiniRAG first retrieves chunks.",
                                "role": "main",
                                "start_char": 0,
                                "end_char": 30,
                            },
                            {
                                "text": "Graph paths then explain why they matter.",
                                "role": "support",
                                "start_char": 31,
                                "end_char": 73,
                            },
                        ],
                        "relations": [
                            {
                                "source_unit_index": 1,
                                "target_unit_index": 0,
                                "relation_type": "supports",
                                "weight": 1.0,
                            }
                        ],
                        "main_unit_indexes": [0],
                        "supporting_unit_indexes": [1],
                    }
                ]
            }
        )
    )
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        enabled=False,
    )

    package = extractor.extract(_package())

    assert package.structures == []
    assert package.metadata["status"] == "disabled"
    for structure in package.structures:
        for unit in structure.units:
            assert unit.nuclearity is None
            assert unit.rst_relation is None
            assert unit.planning_role is None
