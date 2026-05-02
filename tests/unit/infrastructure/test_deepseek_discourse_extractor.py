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
        max_chunks=5,
    )

    package = extractor.extract(_package())

    assert package.query == "How does MiniRAG recover evidence?"
    assert package.metadata == {
        "extractor": "deepseek_chat_intra_chunk_discourse",
        "model": "deepseek-v4-flash",
        "selected_evidence_count": 1,
        "structure_count": 1,
        "status": "ok",
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

    assert len(client.calls) == 1
    assert "JSON object" in client.calls[0]["instructions"]
    assert "canonical_chunk_id: chunk_doc_alpha_0" in client.calls[0]["input_text"]
    assert "MiniRAG first retrieves chunks" in client.calls[0]["input_text"]


def test_deepseek_discourse_extractor_respects_max_chunks() -> None:
    client = _FakeDeepSeekClient(json.dumps({"chunks": []}))
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        max_chunks=1,
    )

    package = extractor.extract(_package_with_two_items())

    assert package.metadata["selected_evidence_count"] == 1
    assert "canonical_chunk_id: chunk_doc_alpha_0" in client.calls[0]["input_text"]
    assert "canonical_chunk_id: chunk_doc_alpha_1" not in client.calls[0]["input_text"]


def test_deepseek_discourse_extractor_disabled_path_skips_model_call() -> None:
    client = _FakeDeepSeekClient("not json")
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=client,
        enabled=False,
    )

    package = extractor.extract(_package())

    assert package.structures == []
    assert package.metadata["status"] == "disabled"
    assert client.calls == []


def test_deepseek_discourse_extractor_empty_package_skips_model_call() -> None:
    evidence_package = _package()
    evidence_package.items = []
    client = _FakeDeepSeekClient("not json")
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(client=client)

    package = extractor.extract(evidence_package)

    assert package.structures == []
    assert package.metadata["status"] == "empty"
    assert client.calls == []


def test_deepseek_discourse_extractor_rejects_invalid_json() -> None:
    extractor = DeepSeekChatIntraChunkDiscourseExtractor(
        client=_FakeDeepSeekClient("not json"),
    )

    with pytest.raises(ProcessingError, match="invalid JSON"):
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
