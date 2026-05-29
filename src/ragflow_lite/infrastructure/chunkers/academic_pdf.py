from __future__ import annotations

from ragflow_lite.domain.models import (
    Chunk,
    ParsedDocument,
    ParsedPdfDocument,
    PdfElement,
)

# 只处理这些语义明确的元素类型；header/footer/page-number 等噪声元素跳过
_HANDLED_ELEMENT_TYPES = frozenset(
    {"paragraph", "table", "figure", "reference", "formula"}
)


class AcademicPdfChunker:
    chunk_size = 512
    chunk_overlap = 0

    def chunk(self, document: ParsedDocument) -> list[Chunk]:
        payload = document.structured_payload
        if not isinstance(payload, ParsedPdfDocument):
            raise ValueError("AcademicPdfChunker requires ParsedPdfDocument payload.")

        chunks: list[Chunk] = []
        for element in payload.elements:
            if element.element_type not in _HANDLED_ELEMENT_TYPES:
                continue
            text = _academic_chunk_text(payload, element)
            if not text.strip():
                continue
            metadata = _academic_metadata(payload, element)
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{document.document_id}_{len(chunks)}",
                    document_id=document.document_id,
                    text=text,
                    index=len(chunks),
                    metadata=metadata,
                )
            )
        return chunks


def _section_path_text(section_path: list[str]) -> str:
    return " > ".join(part for part in section_path if part)


def _media_context(element: PdfElement) -> str:
    return " ".join(
        part
        for part in [element.context_before, element.context_after]
        if part and part.strip()
    ).strip()


def _academic_chunk_text(payload: ParsedPdfDocument, element: PdfElement) -> str:
    lines = [f"Paper: {payload.title}"]
    if payload.authors:
        lines.append(f"Authors: {', '.join(payload.authors)}")
    role = element.academic_role or element.element_type
    lines.append(f"Role: {role}")
    section = _section_path_text(element.section_path)
    if section:
        lines.append(f"Section: {section}")
    label = element.element_label or element.element_type
    lines.append(f"Element: {label}")
    if element.caption:
        lines.append(f"Caption: {element.caption}")
    context = _media_context(element)
    if context:
        lines.append(f"Context: {context}")
    visual_description = str(element.metadata.get("visual_description", "") or "")
    if visual_description:
        lines.append(f"Visual description: {visual_description}")
    lines.append("Body:")
    if element.text:
        lines.append(element.text)
    return "\n".join(lines)


def _academic_metadata(
    payload: ParsedPdfDocument, element: PdfElement
) -> dict[str, object]:
    context = _media_context(element)
    metadata: dict[str, object] = {
        "paper_title": payload.title,
        "authors": list(payload.authors),
        "pdf_element_type": element.element_type,
        "academic_role": element.academic_role or element.element_type,
        "section_path": list(element.section_path),
        "page_start": element.page_start,
        "page_end": element.page_end,
        "chunker_strategy": "academic_pdf",
    }
    if element.element_label:
        metadata["element_label"] = element.element_label
    if element.caption:
        metadata["caption"] = element.caption
    if context:
        metadata["media_context"] = context
    if element.media_asset_id:
        metadata["asset_id"] = element.media_asset_id
    if element.metadata.get("visual_description"):
        metadata["visual_description"] = element.metadata["visual_description"]
        metadata["figure_description_status"] = element.metadata.get(
            "figure_description_status",
            "succeeded",
        )
    return metadata
