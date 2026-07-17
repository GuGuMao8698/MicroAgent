from __future__ import annotations

import pytest

from ragflow_lite.domain.models.psi_tree import PsiNode
from ragflow_lite.infrastructure.evidence.psi_node_fields import (
    PSI_NODE_MATCH_TEXT_FIELDS,
    PsiNodeProjectionError,
    build_psi_node_projection_row,
    build_psi_node_projection_text,
)


def _node(**overrides: object) -> PsiNode:
    values: dict[str, object] = {
        "node_id": "psi-node",
        "build_id": "build-1",
        "layer": 1,
        "node_type": "internal",
        "abstract_type": "keyword",
        "text": "",
        "summary_text": None,
        "keyword_text": "latency budget",
        "source_document_id": "doc-1",
    }
    values.update(overrides)
    return PsiNode(**values)  # type: ignore[arg-type]


def test_keyword_node_uses_keyword_text_for_embedding_and_sparse_fields() -> None:
    fields = build_psi_node_projection_text(_node(), tokenize=lambda value: value)

    assert fields.embedding_text == "latency budget"
    assert fields.psi_keyword_tks == "latency budget"
    assert fields.psi_summary_tks == ""
    assert "psi_keyword_tks^20" in PSI_NODE_MATCH_TEXT_FIELDS


def test_summative_and_leaf_nodes_use_only_their_queryable_text() -> None:
    summary = build_psi_node_projection_text(
        _node(
            abstract_type="summative",
            summary_text="A short summary",
            keyword_text=None,
        ),
        tokenize=lambda value: value,
    )
    leaf = build_psi_node_projection_text(
        _node(node_type="leaf", abstract_type=None, text="Original source text"),
        tokenize=lambda value: value,
    )

    assert summary.embedding_text == "A short summary"
    assert summary.psi_summary_tks == "A short summary"
    assert leaf.embedding_text == "Original source text"
    assert leaf.psi_leaf_text_tks == "Original source text"


def test_empty_keyword_node_fails_instead_of_falling_back_to_chunk_text() -> None:
    with pytest.raises(PsiNodeProjectionError, match="keyword_text"):
        build_psi_node_projection_text(_node(keyword_text="   ", text="source text"))


def test_projection_row_keeps_psi_identity_distinct_from_source_chunks() -> None:
    row = build_psi_node_projection_row(
        _node(),
        document_id="doc-1",
        source_chunk_ids=["chunk-1"],
        vector=[0.1, 0.2],
        tokenize=lambda value: value,
    )

    assert row["psi_node_id"] == "psi-node"
    assert row["projection_row_id"] == "build-1:psi-node"
    assert "chunk_id" not in row
    assert row["source_chunk_ids_json"] == '["chunk-1"]'
    assert row["embedding_text"] == "latency budget"
