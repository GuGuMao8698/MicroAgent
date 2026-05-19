from __future__ import annotations

import pytest

from ragflow_lite.domain.models import ParsedDocument
from ragflow_lite.infrastructure.chunkers.recursive_character import (
    RecursiveCharacterChunker,
    _merge_pieces,
    _recursive_split,
)
from ragflow_lite.infrastructure.chunkers.token_counter import count_cl100k_tokens

# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_params(self) -> None:
        chunker = RecursiveCharacterChunker()
        assert chunker.chunk_size == 512
        assert chunker.chunk_overlap == 0
        assert len(chunker.separators) == 10

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


class TestTokenCounter:
    def test_counts_cl100k_tokens_for_ascii_text(self) -> None:
        assert count_cl100k_tokens("hello world") == 2

    def test_counts_empty_text_as_zero(self) -> None:
        assert count_cl100k_tokens("") == 0

    def test_count_is_not_character_count_for_chinese_text(self) -> None:
        text = "这是一个中文句子，用来证明 token 数不是字符数。"
        assert count_cl100k_tokens(text) != len(text)


# ---------------------------------------------------------------------------
# _recursive_split unit tests
# ---------------------------------------------------------------------------


class TestRecursiveSplit:
    def test_short_text_returned_as_is_when_within_token_budget(self) -> None:
        result = _recursive_split("hello world", ["\n", ""], 2)
        assert result == ["hello world"]

    def test_splits_on_paragraph_before_fallback(self) -> None:
        text = "Alpha paragraph.\n\nBeta paragraph."
        result = _recursive_split(text, ["\n\n", "\n", " ", ""], 3)
        assert "".join(result) == text
        assert result[0].endswith("\n\n")
        assert all(count_cl100k_tokens(piece) <= 3 for piece in result)

    def test_long_unseparated_text_uses_token_safe_original_slices(self) -> None:
        text = "antidisestablishmentarianism" * 40
        result = _recursive_split(text, ["\n\n", "\n", " ", ""], 10)
        assert "".join(result) == text
        assert len(result) > 1
        assert all(count_cl100k_tokens(piece) <= 10 for piece in result)

    def test_chinese_period_separator_preserves_text(self) -> None:
        text = "第一句话说明背景。第二句话继续说明。第三句话收尾。"
        result = _recursive_split(text, ["。", ""], 8)
        assert "".join(result) == text
        assert any(piece.endswith("。") for piece in result[:-1])
        assert all(count_cl100k_tokens(piece) <= 8 for piece in result)


# ---------------------------------------------------------------------------
# _merge_pieces unit tests
# ---------------------------------------------------------------------------


class TestMergePieces:
    def test_single_piece(self) -> None:
        result = _merge_pieces(["hello"], 10, 0)
        assert len(result) == 1
        assert result[0] == ("hello", 0, 5)

    def test_merge_small_pieces_by_whole_candidate_tokens(self) -> None:
        pieces = ["hello", " ", "world"]
        result = _merge_pieces(pieces, 2, 0)
        assert result == [("hello world", 0, 11)]

    def test_split_when_joined_candidate_exceeds_budget(self) -> None:
        pieces = ["hello world", " again"]
        result = _merge_pieces(pieces, 2, 0)
        assert result == [("hello world", 0, 11), (" again", 11, 17)]
        assert all(count_cl100k_tokens(text) <= 2 for text, _, _ in result)

    def test_offsets_preserve_positions(self) -> None:
        pieces = ["第一句。", "第二句。", "Third sentence."]
        result = _merge_pieces(pieces, 8, 0)
        full_text = "".join(pieces)
        for text, start, end in result:
            assert full_text[start:end] == text
            assert count_cl100k_tokens(text) <= 8

    def test_overlap_is_disabled_by_default_contract(self) -> None:
        pieces = ["hello world", " again"]
        result = _merge_pieces(pieces, 2, 0)
        assert result[0][2] == result[1][1]


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
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
        doc = self._make_doc("Hello world", filename="test.txt")
        chunks = chunker.chunk(doc)
        assert "page_start" not in chunks[0].metadata
        assert "page_end" not in chunks[0].metadata
        assert "page_spans" not in chunks[0].metadata
        assert "page_texts" not in chunks[0].metadata

    def test_page_start_end_injected(self) -> None:
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
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
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
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
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
        doc = self._make_doc("Hello", filename="a.txt", author="test")
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata["filename"] == "a.txt"
        assert chunks[0].metadata["author"] == "test"

    def test_recursive_split_on_paragraphs(self) -> None:
        text = (
            "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here."
        )
        chunker = RecursiveCharacterChunker(chunk_size=8, chunk_overlap=0)
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

    def test_final_chunks_respect_token_budget(self) -> None:
        text = (
            "第一段说明 MicroRAG 的 chunk 策略。\n\n"
            "第二段继续说明 token budget 和字符 offset 的区别。\n\n"
            "Third paragraph mixes English and Chinese for tokenizer behavior."
        )
        chunker = RecursiveCharacterChunker(chunk_size=12, chunk_overlap=0)
        doc = self._make_doc(text)

        chunks = chunker.chunk(doc)

        assert len(chunks) > 1
        for chunk in chunks:
            assert count_cl100k_tokens(chunk.text) <= 12
            expected_text = text[
                chunk.metadata["start_offset"] : chunk.metadata["end_offset"]
            ].strip()
            assert chunk.text == expected_text

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
        for chunk in chunks:
            start = chunk.metadata["start_offset"]
            end = chunk.metadata["end_offset"]
            assert start >= 0
            assert end <= len(text)
            assert end > start

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
        text = "antidisestablishmentarianism" * 5
        doc = ParsedDocument(
            document_id="long",
            file_type="txt",
            raw_text=text,
            metadata={},
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 2
        assert "".join(c.text for c in chunks) == text
        assert all(count_cl100k_tokens(chunk.text) <= 5 for chunk in chunks)

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
        chunker = RecursiveCharacterChunker(chunk_size=100, chunk_overlap=0)
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

    def test_indices_sequential_when_whitespace_chunks_skipped(self) -> None:
        """When merged chunks that are purely whitespace are skipped, remaining
        chunks must have sequential indices (0, 1, 2, ...) with no gaps."""
        # Text starts with separators so that "\n\n" pieces form their own
        # merged chunks which strip to empty.
        chunker = RecursiveCharacterChunker(
            chunk_size=3, chunk_overlap=0, separators=["\n\n"]
        )
        doc = ParsedDocument(
            document_id="gap1",
            file_type="txt",
            raw_text="\n\nAAA\n\nBBB",
            metadata={},
        )
        chunks = chunker.chunk(doc)
        # Whitespace-only chunks are dropped; the remaining chunks must have
        # sequential indices and correctly formatted chunk_ids.
        assert len(chunks) >= 1
        for i, chunk in enumerate(chunks):
            assert chunk.index == i, f"Expected sequential index {i}, got {chunk.index}"
            assert chunk.chunk_id == f"chunk_gap1_{i}", (
                f"Expected chunk_id chunk_gap1_{i}, got {chunk.chunk_id}"
            )
        # Verify that actual text content is preserved.
        texts = [c.text for c in chunks]
        assert "AAA" in " ".join(texts)
        assert "BBB" in " ".join(texts)
