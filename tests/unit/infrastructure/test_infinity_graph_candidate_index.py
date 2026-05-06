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
