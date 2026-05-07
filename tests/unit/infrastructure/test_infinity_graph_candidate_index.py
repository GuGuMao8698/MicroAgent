from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    GraphCandidateInfinityConfig,
)


def test_graph_candidate_config_defaults_match_spec() -> None:
    config = GraphCandidateInfinityConfig()

    assert config.entity_table == "graph_entities"
    assert config.relationship_table == "graph_relationships"
    assert config.graph_initial_recall_n == 1024
    assert config.text_weight == 0.05
    assert config.dense_weight == 0.95
    assert config.minimum_should_match == 0.3
    assert config.dense_similarity_threshold == 0.2
    assert config.fusion_normalize == "atan"


def test_graph_candidate_config_is_frozen() -> None:
    config = GraphCandidateInfinityConfig()

    with pytest.raises(AttributeError):
        config.entity_table = "other"  # type: ignore[misc]


def test_graph_candidate_config_accepts_custom_values() -> None:
    config = GraphCandidateInfinityConfig(
        entity_table="my_entities",
        relationship_table="my_relationships",
        graph_initial_recall_n=512,
        text_weight=0.1,
        dense_weight=0.9,
    )

    assert config.entity_table == "my_entities"
    assert config.relationship_table == "my_relationships"
    assert config.graph_initial_recall_n == 512
    assert config.text_weight == 0.1
    assert config.dense_weight == 0.9


def test_relationship_output_fields_preserve_candidate_contract() -> None:
    from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
        RELATIONSHIP_OUTPUT_FIELDS,
    )

    assert "candidate_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "canonical_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "document_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_entity_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "target_entity_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_entity_name" in RELATIONSHIP_OUTPUT_FIELDS
    assert "target_entity_name" in RELATIONSHIP_OUTPUT_FIELDS
    assert "relationship_description_tks" in RELATIONSHIP_OUTPUT_FIELDS
    assert "keywords" in RELATIONSHIP_OUTPUT_FIELDS
    assert "weight" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_chunk_ids" in RELATIONSHIP_OUTPUT_FIELDS
    assert "metadata" in RELATIONSHIP_OUTPUT_FIELDS
    assert "_score" in RELATIONSHIP_OUTPUT_FIELDS


def test_relationship_candidate_mapper_preserves_relation_fields() -> None:
    from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
        GraphCandidateInfinityConfig,
        _relationship_candidate_from_row,
    )

    candidate = _relationship_candidate_from_row(
        {
            "candidate_id": "relation_python_django_raw",
            "canonical_id": "relation_python_django",
            "document_id": "graph_doc",
            "source_entity_id": "entity_python",
            "target_entity_id": "entity_django",
            "source_entity_name": "Python",
            "target_entity_name": "Django",
            "relationship_description_tks": "Python uses Django",
            "keywords": '["framework"]',
            "weight": 1.0,
            "source_chunk_ids": '["chunk_python"]',
            "metadata": '{"canonical_id": "relation_python_django"}',
            "_score": 0.75,
        },
        GraphCandidateInfinityConfig(),
    )

    relation = candidate.relation
    assert relation.relation_id == "relation_python_django"
    assert relation.document_id == "graph_doc"
    assert relation.source_entity_id == "entity_python"
    assert relation.target_entity_id == "entity_django"
    assert relation.source_entity_name == "Python"
    assert relation.target_entity_name == "Django"
    assert relation.description == "Python uses Django"
    assert relation.keywords == ["framework"]
    assert relation.weight == 1.0
    assert relation.source_chunk_ids == ["chunk_python"]
    assert candidate.score == 0.75
    assert candidate.metadata["candidate_id"] == "relation_python_django_raw"
    assert candidate.metadata["candidate_kind"] == "relationship"
