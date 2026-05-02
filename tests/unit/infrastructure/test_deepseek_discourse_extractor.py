from __future__ import annotations

import json

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
