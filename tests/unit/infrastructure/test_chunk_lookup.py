from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.infrastructure.vector_indexes.local_json_index import (
    LocalJsonVectorIndex,
)


def test_local_json_vector_index_get_chunks_returns_requested_chunks(
    tmp_path: Path,
) -> None:
    index = LocalJsonVectorIndex(
        index_dir=tmp_path,
        embedding_signature={"model": "unit", "dimensions": 2},
    )
    asset = DocumentAsset(
        document_id="doc1",
        filename="doc.md",
        file_type="markdown",
        storage_path=tmp_path / "doc.md",
        size_bytes=12,
    )
    index.index_document(
        asset,
        [
            EmbeddedChunk(
                chunk_id="chunk_doc1_0",
                document_id="doc1",
                text="MiniRAG grounds queries.",
                index=0,
                vector=[1.0, 0.0],
                metadata={"section": "intro"},
            ),
            EmbeddedChunk(
                chunk_id="chunk_doc1_1",
                document_id="doc1",
                text="MiniRAG recovers chunks from graph paths.",
                index=1,
                vector=[0.0, 1.0],
                metadata={"section": "details"},
            ),
        ],
    )

    chunks = index.get_chunks(["chunk_doc1_1", "missing"])

    assert [chunk.chunk_id for chunk in chunks] == ["chunk_doc1_1"]
    assert chunks[0].text == "MiniRAG recovers chunks from graph paths."
    assert chunks[0].score == 0.0
    assert chunks[0].metadata["section"] == "details"
    assert chunks[0].metadata["filename"] == "doc.md"
