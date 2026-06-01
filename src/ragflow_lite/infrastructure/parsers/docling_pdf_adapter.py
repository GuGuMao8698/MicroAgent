"""Docling-backed PDF parser producing structured ParsedPdfDocument."""

from __future__ import annotations

import logging
from pathlib import Path

from ragflow_lite.domain.errors import DocumentParsingError
from ragflow_lite.domain.models import (
    DocumentAsset,
    ParsedDocument,
    ParsedPdfDocument,
    PdfElement,
    PdfMediaAsset,
    PdfPage,
)
from ragflow_lite.shared.observability import log_event

logger = logging.getLogger(__name__)

PARSER_STRATEGY = "docling_academic_pdf"


class DoclingPdfBackend:
    """Abstract backend for Docling conversion. Subclass or inject for testing."""

    def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
        raise NotImplementedError


class RealDoclingPdfBackend(DoclingPdfBackend):
    """Production backend that calls Docling's DocumentConverter."""

    def __init__(self) -> None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = True
        options.do_table_structure = True
        options.do_formula_enrichment = True
        options.generate_picture_images = True
        options.images_scale = 2

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
            }
        )

    def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)

        try:
            result = self._converter.convert(tmp_path)
            doc = result.document
            return self._map_to_parsed_pdf(doc, filename)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _map_to_parsed_pdf(self, doc: object, filename: str) -> ParsedPdfDocument:
        """Map Docling document to MicroRAG ParsedPdfDocument.

        Docling doc structure:
        - doc.texts: list of text items with label, text, prov (provenance)
        - doc.tables: list of table items with data (grid), caption_text()
        - doc.pictures: list of picture items with image, caption_text()
        - Items have .label (string), .text (string), .prov (list of provenance)
        - Provenance has .page_no, .bbox (with l, t, r, b attributes)
        """
        elements: list[PdfElement] = []
        media_assets: list[PdfMediaAsset] = []
        pages_seen: set[int] = set()
        warnings: list[str] = []
        title = ""
        authors: list[str] = []
        section_stack: list[str] = []

        for item in getattr(doc, "texts", []):
            label = str(getattr(item, "label", ""))
            text = str(getattr(item, "text", "")).strip()
            prov = getattr(item, "prov", [])
            page_no = prov[0].page_no if prov else None

            if label == "section_header" and page_no == 1 and not title:
                # 首页首个 section_header 作为标题启发式
                if (
                    text
                    and not text.lower().startswith("abstract")
                    and not text[0].isdigit()
                ):
                    title = text
                    continue

            if label == "section_header":
                level = getattr(getattr(item, "heading", None), "level", 1) or 1
                if level <= len(section_stack):
                    section_stack = section_stack[: level - 1]
                section_stack.append(text)

            element_type = self._label_to_element_type(label)
            if not text and element_type not in ("table", "figure"):
                continue

            element = PdfElement(
                element_id=f"el_{len(elements)}",
                element_type=element_type,
                text=text,
                page_start=page_no,
                page_end=page_no,
                bbox=self._extract_bbox(prov[0] if prov else None),
                section_path=list(section_stack),
                academic_role=self._label_to_academic_role(label),
            )
            elements.append(element)

            if page_no is not None:
                pages_seen.add(page_no)

        # Process tables
        for i, table_item in enumerate(getattr(doc, "tables", [])):
            md_text = ""
            if hasattr(table_item, "export_to_markdown"):
                md_text = table_item.export_to_markdown(doc)
            elif hasattr(table_item, "data") and hasattr(table_item.data, "grid"):
                md_text = self._table_grid_to_markdown(table_item.data.grid)

            prov = self._first_provenance(table_item)
            page_no = self._page_no(prov)
            caption = self._safe_caption(
                table_item, doc, warnings, "table_caption_extraction_failed"
            )

            element = PdfElement(
                element_id=f"tbl_{i}",
                element_type="table",
                text=md_text,
                page_start=page_no,
                page_end=page_no,
                bbox=self._extract_bbox(prov),
                section_path=list(section_stack),
                academic_role="table",
                element_label=f"Table {i + 1}",
                caption=caption if caption else None,
            )
            elements.append(element)
            if page_no is not None:
                pages_seen.add(page_no)

        # Process pictures
        for i, pic_item in enumerate(getattr(doc, "pictures", [])):
            prov = self._first_provenance(pic_item)
            page_no = self._page_no(prov)
            caption = self._safe_caption(
                pic_item, doc, warnings, "figure_caption_extraction_failed"
            )

            media_asset_id = f"pic_{i}"
            img_data = None
            img_ref = getattr(pic_item, "image", None)
            if img_ref is not None:
                try:
                    import io

                    buf = io.BytesIO()
                    img_ref.save(buf, format="PNG")
                    img_data = buf.getvalue()
                except Exception:
                    warnings.append("figure_image_extraction_failed")

            if img_data:
                media_asset = PdfMediaAsset(
                    asset_id=media_asset_id,
                    element_id=f"fig_{i}",
                    media_type="image/png",
                    extension=".png",
                    size_bytes=len(img_data),
                    data=img_data,
                )
                media_assets.append(media_asset)

            element = PdfElement(
                element_id=f"fig_{i}",
                element_type="figure",
                text="",
                page_start=page_no,
                page_end=page_no,
                bbox=self._extract_bbox(prov),
                section_path=list(section_stack),
                academic_role="figure",
                element_label=f"Figure {i + 1}",
                caption=caption if caption else None,
                media_asset_id=media_asset_id if img_data else None,
            )
            elements.append(element)
            if page_no is not None:
                pages_seen.add(page_no)

        pages = [PdfPage(page_number=p) for p in sorted(pages_seen)]

        if not title:
            warnings.append("pdf_title_missing")

        return ParsedPdfDocument(
            document_id="",
            filename=filename,
            parser_strategy=PARSER_STRATEGY,
            title=title,
            authors=authors,
            pages=pages,
            elements=elements,
            media_assets=media_assets,
            warnings=warnings,
        )

    @staticmethod
    def _label_to_element_type(label: str) -> str:
        mapping = {
            "title": "title",
            "section_header": "section_heading",
            "paragraph": "paragraph",
            "text": "paragraph",
            "table": "table",
            "picture": "figure",
            "figure": "figure",
            "caption": "caption",
            "formula": "formula",
            "reference": "reference",
            "list_item": "paragraph",
            "page_header": "paragraph",
            "page_footer": "paragraph",
            "footnote": "paragraph",
        }
        return mapping.get(label, "paragraph")

    @staticmethod
    def _label_to_academic_role(label: str) -> str:
        mapping = {
            "section_header": "section_heading",
            "paragraph": "body",
            "text": "body",
            "table": "table",
            "picture": "figure",
            "figure": "figure",
            "caption": "caption",
            "formula": "formula",
            "reference": "reference",
            "list_item": "body",
        }
        return mapping.get(label, "body")

    @staticmethod
    def _first_provenance(item: object) -> object | None:
        prov = getattr(item, "provenance", [])
        if not prov:
            prov = getattr(item, "prov", [])
        return prov[0] if prov else None

    @staticmethod
    def _page_no(prov: object | None) -> int | None:
        return getattr(prov, "page_no", None) if prov is not None else None

    @staticmethod
    def _safe_caption(
        item: object,
        doc: object,
        warnings: list[str],
        warning_code: str,
    ) -> str:
        if not hasattr(item, "caption_text"):
            return ""
        try:
            return str(item.caption_text(doc) or "").strip()
        except Exception:
            warnings.append(warning_code)
            return ""

    @staticmethod
    def _extract_bbox(prov: object | None) -> tuple[float, float, float, float] | None:
        if prov is None:
            return None
        bbox = getattr(prov, "bbox", None)
        if bbox is None:
            return None
        return (
            float(getattr(bbox, "l", 0)),
            float(getattr(bbox, "t", 0)),
            float(getattr(bbox, "r", 0)),
            float(getattr(bbox, "b", 0)),
        )

    @staticmethod
    def _table_grid_to_markdown(grid: object) -> str:
        """Convert Docling table grid to simple markdown."""
        rows = getattr(grid, "rows", []) if grid else []
        if not rows:
            return ""
        lines: list[str] = []
        for row_idx, row in enumerate(rows):
            cells: list[str] = []
            for cell in getattr(row, "cells", []):
                cell_text = str(getattr(cell, "text", "")).strip()
                cells.append(cell_text)
            line = "| " + " | ".join(cells) + " |"
            lines.append(line)
            if row_idx == 0:
                lines.append("| " + " | ".join("---" for _ in cells) + " |")
        return "\n".join(lines)


class DoclingPdfParser:
    """PDF parser backed by Docling, emitting structured ParsedPdfDocument."""

    def __init__(self, backend: DoclingPdfBackend | None = None) -> None:
        self.backend = backend or RealDoclingPdfBackend()

    def parse(self, asset: DocumentAsset, raw_bytes: bytes) -> ParsedDocument:
        try:
            payload = self.backend.convert(raw_bytes, asset.filename)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "parser_failed",
                document_filename=asset.filename,
                file_type=asset.file_type,
                parser_strategy=PARSER_STRATEGY,
                error_type=type(exc).__name__,
            )
            raise DocumentParsingError(asset.filename) from exc

        payload.document_id = asset.document_id
        payload.filename = asset.filename
        payload.parser_strategy = PARSER_STRATEGY
        return ParsedDocument(
            document_id=asset.document_id,
            file_type=asset.file_type,
            raw_text="\n\n".join(
                element.text for element in payload.elements if element.text
            ).strip(),
            metadata={
                "filename": asset.filename,
                "format": "pdf",
                "parser_strategy": PARSER_STRATEGY,
                "paper_title": payload.title,
                "authors": payload.authors,
                "warnings": payload.warnings,
            },
            structured_payload=payload,
        )
