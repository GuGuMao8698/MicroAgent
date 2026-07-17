from __future__ import annotations

import pytest

from ragflow_lite.infrastructure.evidence.infinity_psi_node_index import (
    PsiNodeInfinityConfig,
    _equals_filter,
    _fulltext_columns,
    _hit_from_row,
    _in_filter,
    _minimum_should_match_option,
    allowed_projection_row_ids,
)


def test_psi_node_config_validates_hybrid_parameters() -> None:
    with pytest.raises(ValueError, match="weight"):
        PsiNodeInfinityConfig(text_weight=0, dense_weight=0)
    with pytest.raises(ValueError, match="between"):
        PsiNodeInfinityConfig(minimum_should_match=1.1)


def test_psi_node_query_helpers_build_sdk_options_and_safe_filters() -> None:
    assert _minimum_should_match_option(0.3) == "30%"
    assert _equals_filter("build_id", "build'1") == "build_id = 'build\\'1'"
    assert _in_filter("psi_node_id", ["psi-a", "psi-b"]) == (
        "psi_node_id IN ('psi-a', 'psi-b')"
    )
    assert allowed_projection_row_ids("build-1", ["psi-a", "psi-b"]) == [
        "build-1:psi-a",
        "build-1:psi-b",
    ]
    assert _fulltext_columns() == [
        "psi_node_label_kwd",
        "psi_node_label_tks",
        "psi_keyword_tks",
        "psi_summary_tks",
        "psi_leaf_text_tks",
    ]


def test_psi_node_hit_mapping_never_exposes_chunk_identity() -> None:
    hit = _hit_from_row(
        {
            "psi_node_id": "psi-a",
            "projection_row_id": "build-1:psi-a",
            "build_id": "build-1",
            "document_id": "doc-1",
            "layer": 2,
            "node_type": "root",
            "abstract_type": "keyword",
            "metadata_json": '{"internal": true}',
            "_score": 0.8,
        }
    )

    assert hit.psi_node_id == "psi-a"
    assert hit.score == 0.8
    assert hit.metadata["retrieval_mode"] == "psi_node_infinity_hybrid"
    assert "chunk_id" not in hit.metadata
