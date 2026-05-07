from __future__ import annotations

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    InterChunkDiscourseGraph,
    InterChunkDiscourseRelation,
)


def test_inter_chunk_graph_preserves_sparse_relations() -> None:
    relation = InterChunkDiscourseRelation(
        source_chunk_id="chunk_a",
        target_chunk_id="chunk_b",
        relation_type="qualifies",
        rationale="chunk_b limits chunk_a",
        confidence=0.8,
        metadata={"source": "unit"},
    )

    graph = InterChunkDiscourseGraph(
        query="Does vitamin D prevent flu?",
        chunk_ids=["chunk_a", "chunk_b", "chunk_c"],
        relations=[relation],
        metadata={"builder": "deterministic"},
    )

    assert graph.chunk_ids == ["chunk_a", "chunk_b", "chunk_c"]
    assert graph.relations == [relation]
    assert graph.metadata["builder"] == "deterministic"


def test_inter_chunk_relation_rejects_self_relation() -> None:
    with pytest.raises(ProcessingError, match="must use different chunks"):
        InterChunkDiscourseRelation(
            source_chunk_id="chunk_a",
            target_chunk_id="chunk_a",
            relation_type="supports",
        )


def test_inter_chunk_graph_rejects_relation_for_unknown_chunk() -> None:
    relation = InterChunkDiscourseRelation(
        source_chunk_id="chunk_a",
        target_chunk_id="chunk_missing",
        relation_type="supports",
    )

    with pytest.raises(ProcessingError, match="unknown chunk"):
        InterChunkDiscourseGraph(
            query="q",
            chunk_ids=["chunk_a"],
            relations=[relation],
        )
