from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import Chunk, DocumentAsset
from ragflow_lite.infrastructure.embedders import DeterministicHashEmbedder
from ragflow_lite.infrastructure.vector_indexes import LocalJsonVectorIndex


def test_local_json_index_persists_searches_and_deletes(tmp_path: Path) -> None:
    index = LocalJsonVectorIndex(tmp_path)
    embedder = DeterministicHashEmbedder(dimensions=256)
    asset = DocumentAsset(
        document_id="doc_alpha",
        filename="alpha.txt",
        file_type="txt",
        storage_path=tmp_path / "alpha.txt",
        size_bytes=12,
    )
    chunk = Chunk(
        chunk_id="chunk_doc_alpha_0",
        document_id="doc_alpha",
        text="rag pipeline with citations later",
        index=0,
        metadata={"filename": "alpha.txt"},
    )

    embedded_chunk = embedder.embed_chunks([chunk])
    index.index_document(asset, embedded_chunk)

    index_files = list(tmp_path.glob("*"))
    assert [path.suffix for path in index_files] == [".json"]

    results = index.search(embedder.embed_query("pipeline"), top_k=3)
    assert len(results) == 1
    assert results[0].document_id == "doc_alpha"
    assert results[0].metadata["filename"] == "alpha.txt"

    index.delete_document("doc_alpha")
    assert list(tmp_path.glob("*.json")) == []
