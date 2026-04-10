from __future__ import annotations

from typing import Any

from ragflow_lite.domain.models import Chunk, ParsedDocument

# 内部位置键，不应进入 chunk metadata。
_INTERNAL_METADATA_KEYS = frozenset({"page_spans", "page_texts"})


def _overlapping_pages(
    page_spans: list[dict[str, Any]], chunk_start: int, chunk_end: int
) -> list[int]:
    """返回与 chunk 区间 ``[chunk_start, chunk_end)`` 有重叠的页号（升序）。"""
    pages: list[int] = []
    for span in page_spans:
        if chunk_start < span["end"] and span["start"] < chunk_end:
            pages.append(span["page_number"])
    return sorted(pages)


def _chunk_metadata(
    document: ParsedDocument,
    chunk_start: int,
    chunk_end: int,
) -> dict[str, Any]:
    metadata = {
        k: v for k, v in document.metadata.items() if k not in _INTERNAL_METADATA_KEYS
    }
    metadata["start_offset"] = chunk_start
    metadata["end_offset"] = chunk_end

    page_spans = document.metadata.get("page_spans")
    if page_spans:
        pages = _overlapping_pages(page_spans, chunk_start, chunk_end)
        if pages:
            metadata["page_start"] = pages[0]
            metadata["page_end"] = pages[-1]

    return metadata


class FixedWindowChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        chunk_index = 0
        text = document.raw_text

        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        chunk_id=f"chunk_{document.document_id}_{chunk_index}",
                        document_id=document.document_id,
                        text=chunk_text,
                        index=chunk_index,
                        metadata=_chunk_metadata(document, start, end),
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break
            start += step

        return chunks
