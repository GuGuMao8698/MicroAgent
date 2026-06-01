from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class _AcademicElementView:
    paper_title: str
    authors: list[str]
    role: str
    section_path: list[str]
    section: str
    label: str
    caption: str | None
    media_context: str
    visual_description: str
    asset_id: str | None
    element_type: str
    page_start: int | None
    page_end: int | None


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
            view = _element_view(payload, element)
            text = _academic_chunk_text(view, element)
            if not text.strip():
                continue
            metadata = _academic_metadata(view, element)
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


def _element_view(
    payload: ParsedPdfDocument, element: PdfElement
) -> _AcademicElementView:
    return _AcademicElementView(
        paper_title=payload.title,
        authors=list(payload.authors),
        role=element.academic_role or element.element_type,
        section_path=list(element.section_path),
        section=_section_path_text(element.section_path),
        label=element.element_label or element.element_type,
        caption=element.caption,
        media_context=_media_context(element),
        visual_description=str(element.metadata.get("visual_description", "") or ""),
        asset_id=element.media_asset_id,
        element_type=element.element_type,
        page_start=element.page_start,
        page_end=element.page_end,
    )


def _academic_chunk_text(view: _AcademicElementView, element: PdfElement) -> str:
    lines = [f"Paper: {view.paper_title}"]
    if view.authors:
        lines.append(f"Authors: {', '.join(view.authors)}")
    lines.append(f"Role: {view.role}")
    if view.section:
        lines.append(f"Section: {view.section}")
    lines.append(f"Element: {view.label}")
    if view.caption:
        lines.append(f"Caption: {view.caption}")
    if view.media_context:
        lines.append(f"Context: {view.media_context}")
    if view.visual_description:
        lines.append(f"Visual description: {view.visual_description}")
    lines.append("Body:")
    if element.text:
        lines.append(element.text)
    return "\n".join(lines)


def _academic_metadata(
    view: _AcademicElementView, element: PdfElement
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "paper_title": view.paper_title,
        "authors": list(view.authors),
        "pdf_element_type": view.element_type,
        "academic_role": view.role,
        "section_path": list(view.section_path),
        "page_start": view.page_start,
        "page_end": view.page_end,
        "chunker_strategy": "academic_pdf",
    }
    if view.label:
        metadata["element_label"] = view.label
    if view.caption:
        metadata["caption"] = view.caption
    if view.media_context:
        metadata["media_context"] = view.media_context
    if view.asset_id:
        metadata["asset_id"] = view.asset_id
    if view.visual_description:
        metadata["visual_description"] = view.visual_description
    if element.metadata.get("figure_description_status"):
        metadata["figure_description_status"] = element.metadata[
            "figure_description_status"
        ]
    if element.metadata.get("figure_description_error_type"):
        metadata["figure_description_error_type"] = element.metadata[
            "figure_description_error_type"
        ]
    return metadata
