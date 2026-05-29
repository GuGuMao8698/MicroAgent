"""Probe Docling PDF parsing signal quality on academic fixtures.

Usage:
    .venv/bin/python scripts/probe_docling_pdf.py \
        --input tests/fixtures/documents/academic_pdf/sample_academic.pdf \
        --output data/docling-probes/sample_academic.json

Outputs JSON with text samples, tables, pictures, document attributes,
and timing information.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def _preview(text: str, limit: int = 200) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def probe_pdf(input_path: Path, output_path: Path) -> dict[str, Any]:
    """Run Docling on a PDF and collect signal quality data."""
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        do_formula_enrichment=True,
        generate_picture_images=True,
        images_scale=2,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )

    t0 = time.perf_counter()
    result = converter.convert(str(input_path))
    wall_clock_s = time.perf_counter() - t0

    doc = result.document

    # Document-level attributes
    payload: dict[str, Any] = {
        "source_path": str(input_path),
        "source_size_bytes": input_path.stat().st_size,
        "wall_clock_s": round(wall_clock_s, 2),
        "docling_version": _docling_version(),
    }

    # Name and title
    payload["name"] = doc.name
    payload["title_text"] = None

    # Count items by label
    label_counts: dict[str, int] = {}
    text_samples: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    pictures: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    formulas: list[dict[str, Any]] = []

    for item, level in doc.iterate_items():
        label_name = (
            item.label.value if hasattr(item.label, "value") else str(item.label)
        )
        label_counts[label_name] = label_counts.get(label_name, 0) + 1

        item_info: dict[str, Any] = {
            "label": label_name,
            "level": level,
        }

        # Text content
        if hasattr(item, "text"):
            item_info["text_preview"] = _preview(item.text)

        # Provenance (page numbers, bounding box)
        prov = getattr(item, "prov", None)
        if prov:
            prov_list = []
            for p in prov:
                pe: dict[str, Any] = {}
                if hasattr(p, "page_no"):
                    pe["page_no"] = p.page_no
                if hasattr(p, "bbox"):
                    bbox = p.bbox
                    if hasattr(bbox, "l"):
                        pe["bbox"] = {
                            "l": round(bbox.l, 2),
                            "t": round(bbox.t, 2),
                            "r": round(bbox.r, 2),
                            "b": round(bbox.b, 2),
                        }
                    elif hasattr(bbox, "x0"):
                        pe["bbox"] = {
                            "x0": round(bbox.x0, 2),
                            "y0": round(bbox.y0, 2),
                            "x1": round(bbox.x1, 2),
                            "y1": round(bbox.y1, 2),
                        }
                prov_list.append(pe)
            item_info["provenance"] = prov_list

        # Classify item
        label_lower = label_name.lower() if label_name else ""

        if label_lower in ("title", "document_index"):
            payload["title_text"] = item.text if hasattr(item, "text") else None

        if label_lower in (
            "section_header",
            "section_header_level_1",
            "section_header_level_2",
        ):
            headings.append(item_info)

        if label_lower == "table":
            table_data: dict[str, Any] = {"label": label_name}
            if hasattr(item, "text"):
                table_data["text_preview"] = _preview(item.text)
            # Try markdown export
            try:
                md = item.export_to_markdown(doc=doc)
                table_data["markdown_preview"] = _preview(md, 500)
            except Exception as e:
                table_data["markdown_export_error"] = str(e)
            # Captions
            try:
                cap_text = item.caption_text(doc)
                if cap_text:
                    table_data["caption"] = cap_text
                    captions.append({"parent": "table", "text": cap_text})
            except Exception:
                pass
            # Provenance
            prov = getattr(item, "prov", None)
            if prov:
                table_data["provenance"] = [
                    {"page_no": getattr(p, "page_no", None)} for p in prov
                ]
            tables.append(table_data)
            continue  # Don't double-add

        if label_lower == "picture":
            pic_data: dict[str, Any] = {"label": label_name}
            if hasattr(item, "text"):
                pic_data["text_preview"] = _preview(item.text)
            # Captions
            try:
                cap_text = item.caption_text(doc)
                if cap_text:
                    pic_data["caption"] = cap_text
                    captions.append({"parent": "picture", "text": cap_text})
            except Exception:
                pass
            # Check for image data
            pic_data["has_image"] = False
            # Pictures may have image references through the document's body
            try:
                img_data = getattr(item, "image", None)
                if img_data is not None:
                    pic_data["has_image"] = True
                    pic_data["image_type"] = str(type(img_data))
            except Exception:
                pass
            # Provenance
            prov = getattr(item, "prov", None)
            if prov:
                pic_data["provenance"] = [
                    {"page_no": getattr(p, "page_no", None)} for p in prov
                ]
            pictures.append(pic_data)
            continue

        if "formula" in label_lower:
            formulas.append(item_info)
            continue

        if "caption" in label_lower:
            captions.append({**item_info, "parent": "standalone"})
            continue

        # General text samples (keep first 20)
        if len(text_samples) < 20:
            text_samples.append(item_info)

    # Check for pictures with generated images in the document body
    body_pictures = list(doc.pictures) if hasattr(doc, "pictures") else []
    for i, pic in enumerate(body_pictures):
        # Update picture records if we have them
        matched = False
        for pic_data in pictures:
            if (
                pic_data.get("text_preview") == _preview(pic.text)
                if hasattr(pic, "text")
                else False
            ):
                matched = True
                break
        if not matched and i >= len(pictures):
            # Additional picture not captured above
            extra_pic: dict[str, Any] = {"label": "picture_extra", "index": i}
            if hasattr(pic, "text"):
                extra_pic["text_preview"] = _preview(pic.text)
            try:
                cap_text = pic.caption_text(doc)
                if cap_text:
                    extra_pic["caption"] = cap_text
                    captions.append({"parent": "picture_extra", "text": cap_text})
            except Exception:
                pass
            img = getattr(pic, "image", None)
            extra_pic["has_image"] = img is not None
            pictures.append(extra_pic)

    payload["label_counts"] = label_counts
    payload["headings"] = headings
    payload["text_samples"] = text_samples
    payload["tables"] = tables
    payload["pictures"] = pictures
    payload["captions"] = captions
    payload["formulas"] = formulas
    payload["heading_count"] = len(headings)
    payload["table_count"] = len(tables)
    payload["picture_count"] = len(pictures)
    payload["caption_count"] = len(captions)
    payload["formula_count"] = len(formulas)

    # Reading order check: extract heading order for two-column fixture
    if headings:
        payload["reading_order_headings"] = [
            h.get("text_preview", "") for h in headings
        ]

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return payload


def _docling_version() -> str:
    try:
        from importlib.metadata import version

        return version("docling")
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe Docling PDF parsing on academic fixtures.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output

    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")

    print(f"Probing: {input_path.name}")
    payload = probe_pdf(input_path, output_path)

    print(f"  Wall-clock: {payload['wall_clock_s']}s")
    print(f"  Label counts: {payload['label_counts']}")
    print(f"  Tables: {payload['table_count']}")
    print(f"  Pictures: {payload['picture_count']}")
    print(f"  Captions: {payload['caption_count']}")
    print(f"  Title: {payload['title_text']}")
    print(f"  Output: {output_path}")
    print(f"  Output size: {output_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
