from __future__ import annotations

from ragflow_lite.infrastructure.vector_indexes.chunk_text_fields import (
    ACADEMIC_CHUNK_TEXT_FIELDS,
)
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    _REQUIRED_CHUNK_AUXILIARY_TEXT_COLUMNS,
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
        == "filename_kwd^30,paper_title_tks^24,filename_tks^20,academic_role_kwd^18,section_tks^12,caption_tks^10,media_context_tks^9,visual_description_tks^8,element_type_kwd^8,element_label_tks^6,content_tks^2,content_sm_tks"
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


def test_required_chunk_auxiliary_columns_include_academic_fields() -> None:
    assert set(ACADEMIC_CHUNK_TEXT_FIELDS).issubset(
        _REQUIRED_CHUNK_AUXILIARY_TEXT_COLUMNS
    )
