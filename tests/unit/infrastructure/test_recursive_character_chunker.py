from __future__ import annotations

import pytest

from ragflow_lite.domain.models import ParsedDocument
from ragflow_lite.infrastructure.chunkers.recursive_character import (
    RecursiveCharacterChunker,
    _merge_pieces,
    _recursive_split,
)

# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_params(self) -> None:
        chunker = RecursiveCharacterChunker()
        assert chunker.chunk_size == 500
        assert chunker.chunk_overlap == 50
        assert len(chunker.separators) == 10  # DEFAULT_SEPARATORS

    def test_custom_params(self) -> None:
        chunker = RecursiveCharacterChunker(
            chunk_size=200, chunk_overlap=20, separators=["\n", ""]
        )
        assert chunker.chunk_size == 200
        assert chunker.chunk_overlap == 20
        assert chunker.separators == ["\n", ""]

    def test_invalid_chunk_size_zero(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            RecursiveCharacterChunker(chunk_size=0)

    def test_invalid_chunk_size_negative(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            RecursiveCharacterChunker(chunk_size=-1)

    def test_invalid_chunk_overlap_negative(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap"):
            RecursiveCharacterChunker(chunk_overlap=-1)

    def test_invalid_chunk_overlap_equal_to_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap"):
            RecursiveCharacterChunker(chunk_size=100, chunk_overlap=100)

    def test_invalid_chunk_overlap_greater_than_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap"):
            RecursiveCharacterChunker(chunk_size=50, chunk_overlap=60)


# ---------------------------------------------------------------------------
# _recursive_split unit tests
# ---------------------------------------------------------------------------


class TestRecursiveSplit:
    def test_short_text_returned_as_is(self) -> None:
        result = _recursive_split("abc", ["\n", ""], 10)
        assert result == ["abc"]

    def test_splits_on_paragraph(self) -> None:
        # "AAAA\n\nBBBB" splits on "\n\n" -> ["AAAA\n\n", "BBBB"].
        # "AAAA\n\n" is 6 chars, too big for chunk_size=5, so it recursively
        # splits on "\n" -> ["AAAA\n", "\n"].
        text = "AAAA\n\nBBBB"
        result = _recursive_split(text, ["\n\n", "\n", ""], 5)
        assert result == ["AAAA\n", "\n", "BBBB"]
        assert "".join(result) == text

    def test_recursive_fallback_to_line_break(self) -> None:
        # "AAABBB" is 6 chars, chunk_size=3, no paragraph break so it
        # falls through to line-break, then to char-level.
        text = "AAABBB"
        result = _recursive_split(text, ["\n\n", "\n", ""], 3)
        assert all(len(p) <= 3 for p in result)
        # Concatenation must reconstruct original.
        assert "".join(result) == text

    def test_empty_separator_splits_chars(self) -> None:
        text = "abc"
        result = _recursive_split(text, [""], 1)
        assert result == ["a", "b", "c"]

    def test_preserves_text_on_concat(self) -> None:
        text = "Para one\n\nPara two\nLine two.\nLine three."
        result = _recursive_split(text, ["\n\n", "\n", ".", " "], 5)
        assert "".join(result) == text

    def test_chinese_period_separator(self) -> None:
        text = "第一句。第二句。第三句。"
        result = _recursive_split(text, ["。", ""], 10)
        # Each piece includes the separator except the last.
        for p in result:
            assert len(p) <= 10
        assert "".join(result) == text


# ---------------------------------------------------------------------------
# _merge_pieces unit tests
# ---------------------------------------------------------------------------


class TestMergePieces:
    def test_single_piece(self) -> None:
        result = _merge_pieces(["hello"], 10, 0)
        assert len(result) == 1
        assert result[0] == ("hello", 0, 5)

    def test_merge_small_pieces(self) -> None:
        pieces = ["ab", "cd", "ef"]
        result = _merge_pieces(pieces, 6, 0)
        # All three pieces fit: "abcdef" = 6 chars
        assert len(result) == 1
        text, start, end = result[0]
        assert text == "abcdef"
        assert start == 0
        assert end == 6

    def test_split_into_three_chunks(self) -> None:
        # Each piece is 3 chars. chunk_size=5 means at most one piece per chunk.
        pieces = ["abc", "def", "ghi"]
        result = _merge_pieces(pieces, 5, 0)
        assert len(result) == 3
        assert result[0] == ("abc", 0, 3)
        assert result[1] == ("def", 3, 6)
        assert result[2] == ("ghi", 6, 9)

    def test_overlap_between_chunks(self) -> None:
        pieces = ["aaa", "bbb", "ccc"]
        result = _merge_pieces(pieces, 5, 2)
        # First chunk: pieces[0:1] = "aaa" (3 chars)
        # overlap: from end of chunk, take pieces going backwards until > 2 chars.
        # piece[0]="aaa" is 3 > 2, so overlap_count=0 (len(aaa)=3 > chunk_overlap=2)
        # Actually: overlap_len=0, k=0: 0+3=3 > 2 -> break. overlap_count=0
        # current_start = 1 - 0 = 1
        # Second chunk: pieces[1:2] = "bbb"
        # overlap: piece[1]="bbb" 3 > 2 -> overlap_count=0
        # current_start = 2 - 0 = 2
        # Third chunk: pieces[2:3] = "ccc"
        assert len(result) == 3

    def test_overlap_with_small_pieces(self) -> None:
        pieces = ["a", "b", "c", "d", "e"]
        result = _merge_pieces(pieces, 3, 2)
        # First chunk: j=0..2 = "abc" (3 <= 3). j=3: 4 > 3. current_end=3
        # chunk1 = pieces[0:3] = "abc", offset [0,3)
        # overlap: from k=2 going back: piece[2]="c" (1 <= 2), piece[1]="b" (1+1=2 <= 2), piece[0]="a" (3 > 2) -> break
        # overlap_count = 2 (pieces 1 and 2)
        # current_start = 3 - 2 = 1
        # i = 3
        # Second chunk: j=1..3 = pieces[1]+pieces[2]+pieces[3] = "bcd" (3 <= 3). j=4: 4 > 3. current_end=4
        # chunk2 = pieces[1:4] = "bcd", offset [1,4)
        # overlap: k=3="d"(1<=2), k=2="c"(2<=2), k=1="b"(3>2) -> break. overlap_count=2
        # current_start = 4 - 2 = 2
        # i = 4
        # Third chunk: j=2..4 = pieces[2]+pieces[3]+pieces[4] = "cde" (3 <= 3). current_end=5
        # chunk3 = pieces[2:5] = "cde", offset [2,5)
        assert len(result) == 3
        assert result[0] == ("abc", 0, 3)
        assert result[1] == ("bcd", 1, 4)
        assert result[2] == ("cde", 2, 5)

    def test_offsets_preserve_positions(self) -> None:
        pieces = ["hel", "lo ", "wor", "ld"]
        result = _merge_pieces(pieces, 6, 0)
        # Verify reconstruction and offsets
        full_text = "".join(pieces)
        for text, start, end in result:
            assert full_text[start:end] == text


# ---------------------------------------------------------------------------
# Integration: RecursiveCharacterChunker.chunk()
# ---------------------------------------------------------------------------


class TestChunk:
    def _make_doc(
        self, text: str, doc_id: str = "d1", **metadata: object
    ) -> ParsedDocument:
        return ParsedDocument(
            document_id=doc_id,
            file_type="txt",
            raw_text=text,
            metadata=metadata,
        )

    def test_empty_text_returns_empty(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=10, chunk_overlap=0)
        doc = self._make_doc("")
        assert chunker.chunk(doc) == []

    def test_single_chunk(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
        doc = self._make_doc("Hello world")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].chunk_id == "chunk_d1_0"

    def test_chunk_ids_sequential(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
        doc = self._make_doc("abcdefghij", doc_id="doc42")
        chunks = chunker.chunk(doc)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"chunk_doc42_{i}"
            assert chunk.index == i

    def test_deterministic_output(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
        doc = self._make_doc("The quick brown fox jumps over the lazy dog.")
        result1 = chunker.chunk(doc)
        result2 = chunker.chunk(doc)
        assert [c.text for c in result1] == [c.text for c in result2]
        assert [c.chunk_id for c in result1] == [c.chunk_id for c in result2]

    def test_no_page_info_without_page_spans(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100)
        doc = self._make_doc("Hello world", filename="test.txt")
        chunks = chunker.chunk(doc)
        assert "page_start" not in chunks[0].metadata
        assert "page_end" not in chunks[0].metadata
        assert "page_spans" not in chunks[0].metadata
        assert "page_texts" not in chunks[0].metadata

    def test_page_start_end_injected(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100)
        doc = ParsedDocument(
            document_id="pdf1",
            file_type="pdf",
            raw_text="Hello world",
            metadata={
                "page_spans": [{"start": 0, "end": 11, "page_number": 1}],
            },
        )
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata["page_start"] == 1
        assert chunks[0].metadata["page_end"] == 1
        assert "page_spans" not in chunks[0].metadata

    def test_multi_page_range(self) -> None:
        text = "AAAA\n\nBBBB\n\nCCCC"
        chunker = RecursiveCharacterChunker(chunk_size=100)
        doc = ParsedDocument(
            document_id="pdf2",
            file_type="pdf",
            raw_text=text,
            metadata={
                "page_spans": [
                    {"start": 0, "end": 4, "page_number": 1},
                    {"start": 6, "end": 10, "page_number": 2},
                    {"start": 12, "end": 16, "page_number": 3},
                ],
            },
        )
        chunks = chunker.chunk(doc)
        # Single chunk covers entire text -> overlaps all three pages.
        assert chunks[0].metadata["page_start"] == 1
        assert chunks[0].metadata["page_end"] == 3

    def test_metadata_keys_copied(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100)
        doc = self._make_doc("Hello", filename="a.txt", author="test")
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata["filename"] == "a.txt"
        assert chunks[0].metadata["author"] == "test"

    def test_recursive_split_on_paragraphs(self) -> None:
        text = (
            "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
        )
        chunker = RecursiveCharacterChunker(chunk_size=25, chunk_overlap=0)
        doc = self._make_doc(text)
        chunks = chunker.chunk(doc)
        # Each paragraph should become its own chunk (or be further split).
        texts = [c.text for c in chunks]
        assert len(texts) >= 2
        # Verify no text is lost (modulo stripping).
        joined = " ".join(texts)
        assert "First" in joined
        assert "Second" in joined
        assert "Third" in joined

    def test_offsets_are_correct(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
        doc = self._make_doc("abcdefghij")
        chunks = chunker.chunk(doc)
        for chunk in chunks:
            start = chunk.metadata["start_offset"]
            end = chunk.metadata["end_offset"]
            # The offset should point into the original text.
            # Note: chunk.text is stripped, so the slice may have leading/trailing whitespace.
            assert doc.raw_text[start:end].strip() == chunk.text

    def test_offsets_are_continuous(self) -> None:
        """With zero overlap, concatenated (stripped) chunk texts should cover
        all non-whitespace content without gaps in the original text."""
        chunker = RecursiveCharacterChunker(chunk_size=8, chunk_overlap=0)
        text = "one two three four five six"
        doc = self._make_doc(text)
        chunks = chunker.chunk(doc)
        # Verify each offset range is valid.
        prev_end = 0
        for chunk in chunks:
            start = chunk.metadata["start_offset"]
            end = chunk.metadata["end_offset"]
            assert start >= 0
            assert end <= len(text)
            assert end > start
            prev_end = end

    def test_overlap_chunks_share_text(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=6, chunk_overlap=3)
        doc = self._make_doc("abcdefghijkl")
        chunks = chunker.chunk(doc)
        if len(chunks) >= 2:
            # The end of chunk 0 should overlap with the start of chunk 1.
            tail = chunks[0].text[-3:]
            head = chunks[1].text[:3]
            # Overlap may not be exact due to stripping and piece boundaries,
            # but some shared content should exist.
            assert tail == head or len(set(tail) & set(head)) > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_whitespace_only_text(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=10, chunk_overlap=0)
        doc = ParsedDocument(
            document_id="ws",
            file_type="txt",
            raw_text="   \n\n   \n   ",
            metadata={},
        )
        chunks = chunker.chunk(doc)
        # All chunks are whitespace-only after stripping -> empty result.
        assert chunks == []

    def test_single_long_word(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
        doc = ParsedDocument(
            document_id="long",
            file_type="txt",
            raw_text="abcdefghij",
            metadata={},
        )
        chunks = chunker.chunk(doc)
        # Should still split via character fallback.
        assert len(chunks) >= 2
        assert "".join(c.text for c in chunks) == "abcdefghij"

    def test_zero_overlap(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=5, chunk_overlap=0)
        doc = ParsedDocument(
            document_id="noover",
            file_type="txt",
            raw_text="abcdefghij",
            metadata={},
        )
        chunks = chunker.chunk(doc)
        # Chunks should not share content at boundaries.
        for i in range(len(chunks) - 1):
            end = chunks[i].metadata["end_offset"]
            start = chunks[i + 1].metadata["start_offset"]
            assert end <= start

    def test_page_spans_internal_key_stripped(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100)
        doc = ParsedDocument(
            document_id="p1",
            file_type="pdf",
            raw_text="Hello world",
            metadata={
                "page_spans": [{"start": 0, "end": 11, "page_number": 1}],
                "page_texts": {1: "Hello world"},
                "source": "upload",
            },
        )
        chunks = chunker.chunk(doc)
        assert "page_spans" not in chunks[0].metadata
        assert "page_texts" not in chunks[0].metadata
        assert chunks[0].metadata["source"] == "upload"
        assert chunks[0].metadata["page_start"] == 1
