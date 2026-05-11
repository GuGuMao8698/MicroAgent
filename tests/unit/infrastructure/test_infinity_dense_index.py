from __future__ import annotations

from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    ChunkHybridRetrievalConfig,
)


def test_chunk_hybrid_config_defaults_match_spec() -> None:
    config = ChunkHybridRetrievalConfig()

    assert config.initial_recall_n == 1024
    assert config.text_weight == 0.05
    assert config.dense_weight == 0.95
    assert config.minimum_should_match == 0.3
    assert config.dense_similarity_threshold == 0.2
    assert config.fusion_normalize == "atan"
    assert config.position_prior_weight == 0.03
    assert config.position_prior_enabled is True
    assert (
        config.match_text_fields
        == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
    )


def test_chunk_hybrid_config_accepts_custom_values() -> None:
    config = ChunkHybridRetrievalConfig(
        initial_recall_n=77,
        text_weight=0.2,
        dense_weight=0.8,
        minimum_should_match=0.4,
        dense_similarity_threshold=0.25,
        fusion_normalize="atan",
        position_prior_weight=0.01,
        position_prior_enabled=False,
    )

    assert config.initial_recall_n == 77
    assert config.text_weight == 0.2
    assert config.dense_weight == 0.8
    assert config.minimum_should_match == 0.4
    assert config.dense_similarity_threshold == 0.25
    assert config.fusion_normalize == "atan"
    assert config.position_prior_weight == 0.01
    assert config.position_prior_enabled is False
