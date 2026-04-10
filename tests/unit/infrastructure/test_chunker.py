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


def test_chunker_adds_page_start_end_for_single_page_chunk() -> None:
    chunker = FixedWindowChunker(chunk_size=20, chunk_overlap=0)
    document = ParsedDocument(
        document_id="doc_pdf1",
        file_type="pdf",
        raw_text="Hello world foo bar",
        metadata={
            "filename": "test.pdf",
            "format": "pdf",
            "page_spans": [
                {"start": 0, "end": 19, "page_number": 1},
            ],
        },
    )

    chunks = chunker.chunk(document)

    assert len(chunks) == 1
    assert chunks[0].metadata["page_start"] == 1
    assert chunks[0].metadata["page_end"] == 1
    # Internal key should not leak.
    assert "page_spans" not in chunks[0].metadata
    assert "page_texts" not in chunks[0].metadata


def test_chunker_adds_page_range_for_cross_page_chunk() -> None:
    chunker = FixedWindowChunker(chunk_size=20, chunk_overlap=0)
    # Page 1: "AAAA" (0-4), separator 2, Page 2: "BBBB" (6-10), separator 2, Page 3: "CCCC" (12-16)
    document = ParsedDocument(
        document_id="doc_pdf2",
        file_type="pdf",
        raw_text="AAAA\n\nBBBB\n\nCCCC",
        metadata={
            "filename": "multi.pdf",
            "format": "pdf",
            "page_spans": [
                {"start": 0, "end": 4, "page_number": 1},
                {"start": 6, "end": 10, "page_number": 2},
                {"start": 12, "end": 16, "page_number": 3},
            ],
        },
    )

    chunks = chunker.chunk(document)

    # First chunk covers [0, 20) → overlaps all three pages
    assert chunks[0].metadata["page_start"] == 1
    assert chunks[0].metadata["page_end"] == 3


def test_chunker_no_page_info_when_page_spans_absent() -> None:
    chunker = FixedWindowChunker(chunk_size=5, chunk_overlap=0)
    document = ParsedDocument(
        document_id="doc_txt",
        file_type="txt",
        raw_text="Hello",
        metadata={"filename": "test.txt"},
    )

    chunks = chunker.chunk(document)

    assert "page_start" not in chunks[0].metadata
    assert "page_end" not in chunks[0].metadata
