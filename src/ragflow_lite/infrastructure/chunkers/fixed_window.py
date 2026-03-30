from __future__ import annotations

from ragflow_lite.domain.models import Chunk, ParsedDocument


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
                        metadata={
                            **document.metadata,
                            "start_offset": start,
                            "end_offset": end,
                        },
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break
            start += step

        return chunks
