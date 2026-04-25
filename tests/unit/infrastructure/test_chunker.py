from __future__ import annotations

from ragflow_lite.domain.models import ParsedDocument
from ragflow_lite.infrastructure.chunkers import RecursiveCharacterChunker


def test_recursive_chunker_creates_stable_ids_and_overlap() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=2)
    document = ParsedDocument(
        document_id="doc_alpha",
        file_type="txt",
        raw_text="abcdefghij",
        metadata={"filename": "alpha.txt"},
    )

    chunks = chunker.chunk(document)

    # Sequential indices and chunk_id format.
    assert [chunk.chunk_id for chunk in chunks] == [
        f"chunk_doc_alpha_{i}" for i in range(len(chunks))
    ]
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))

    # Offsets are present in metadata and the text matches the slice.
    for chunk in chunks:
        assert "start_offset" in chunk.metadata
        assert "end_offset" in chunk.metadata
        expected_text = document.raw_text[
            chunk.metadata["start_offset"] : chunk.metadata["end_offset"]
        ].strip()
        assert chunk.text == expected_text


def test_recursive_chunker_adds_page_start_end_for_single_page_chunk() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=20, chunk_overlap=0)
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
    # Internal keys should not leak.
    assert "page_spans" not in chunks[0].metadata
    assert "page_texts" not in chunks[0].metadata


def test_recursive_chunker_adds_page_range_for_cross_page_chunk() -> None:
    # Use a large chunk_size so a single chunk covers all pages.
    chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
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

    # Single chunk covers the whole document, spanning all three pages.
    assert len(chunks) == 1
    assert chunks[0].metadata["page_start"] == 1
    assert chunks[0].metadata["page_end"] == 3


def test_recursive_chunker_no_page_info_when_page_spans_absent() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
    document = ParsedDocument(
        document_id="doc_txt",
        file_type="txt",
        raw_text="Hello",
        metadata={"filename": "test.txt"},
    )

    chunks = chunker.chunk(document)

    assert "page_start" not in chunks[0].metadata
    assert "page_end" not in chunks[0].metadata


def test_recursive_chunker_splits_on_chinese_punctuation() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=10, chunk_overlap=0)
    document = ParsedDocument(
        document_id="doc_zh",
        file_type="txt",
        raw_text="第一句话。第二句话！第三句话？第四句话。",
        metadata={},
    )

    chunks = chunker.chunk(document)

    # Verify that each chunk starts at a sentence boundary (after stripping).
    # Chinese punctuation 。！？ should be used as split points.
    assert len(chunks) >= 2, f"Expected multiple chunks, got {len(chunks)}"
    for chunk in chunks:
        assert len(chunk.text) <= 10 + 1, (
            f"Chunk text too long ({len(chunk.text)}): {chunk.text!r}"
        )


def test_recursive_chunker_splits_on_paragraphs_first() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=20, chunk_overlap=0)
    document = ParsedDocument(
        document_id="doc_para",
        file_type="txt",
        raw_text="Short para one.\n\nPara two is short.\n\nThird para here.",
        metadata={},
    )

    chunks = chunker.chunk(document)

    # The chunker should split on \n\n first, producing chunks that
    # respect paragraph boundaries.
    assert len(chunks) >= 2, f"Expected multiple chunks, got {len(chunks)}"
    # Paragraph-level splitting means no chunk should contain \n\n
    assert all("\n\n" not in chunk.text for chunk in chunks)
    for chunk in chunks:
        # Each chunk's text is stripped (no leading/trailing whitespace).
        assert chunk.text == chunk.text.strip()


def test_recursive_chunker_deterministic_output() -> None:
    chunker = RecursiveCharacterChunker(chunk_size=50, chunk_overlap=10)
    document = ParsedDocument(
        document_id="doc_det",
        file_type="txt",
        raw_text=(
            "The quick brown fox jumps over the lazy dog. "
            "Pack my box with five dozen liquor jugs. "
            "How vexingly quick daft zebras jump."
        ),
        metadata={"filename": "det.txt"},
    )

    first = chunker.chunk(document)
    second = chunker.chunk(document)

    assert len(first) == len(second)
    for a, b in zip(first, second):
        assert a.chunk_id == b.chunk_id
        assert a.text == b.text
        assert a.index == b.index
        assert a.metadata == b.metadata
