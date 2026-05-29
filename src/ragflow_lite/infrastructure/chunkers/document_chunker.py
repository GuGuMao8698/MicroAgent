from __future__ import annotations

from ragflow_lite.domain.models import Chunk, ParsedDocument, ParsedPdfDocument
from ragflow_lite.infrastructure.chunkers.academic_pdf import AcademicPdfChunker
from ragflow_lite.infrastructure.chunkers.recursive_character import (
    RecursiveCharacterChunker,
)


class DocumentChunker:
    def __init__(
        self,
        *,
        generic_chunker: RecursiveCharacterChunker,
        academic_pdf_chunker: AcademicPdfChunker,
    ) -> None:
        self.generic_chunker = generic_chunker
        self.academic_pdf_chunker = academic_pdf_chunker
        self.chunk_size = generic_chunker.chunk_size
        self.chunk_overlap = generic_chunker.chunk_overlap
        self.separators = generic_chunker.separators

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        if isinstance(document.structured_payload, ParsedPdfDocument):
            return self.academic_pdf_chunker.chunk(document)
        return self.generic_chunker.chunk(document)
