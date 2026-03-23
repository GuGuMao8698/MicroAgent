from __future__ import annotations

from ragflow_lite.domain.models import ParsedDocument
from ragflow_lite.infrastructure.chunkers import FixedWindowChunker


def test_fixed_window_chunker_creates_stable_ids_and_overlap() -> None:
    chunker = FixedWindowChunker(chunk_size=5, chunk_overlap=2)
    document = ParsedDocument(
        document_id="doc_alpha",
        file_type="txt",
        raw_text="abcdefghij",
        metadata={"filename": "alpha.txt"},
    )

    chunks = chunker.chunk(document)

    assert [chunk.chunk_id for chunk in chunks] == [
        "chunk_doc_alpha_0",
        "chunk_doc_alpha_1",
        "chunk_doc_alpha_2",
    ]
    assert [chunk.text for chunk in chunks] == ["abcde", "defgh", "ghij"]
    assert chunks[1].metadata["start_offset"] == 3
    assert chunks[1].metadata["end_offset"] == 8
