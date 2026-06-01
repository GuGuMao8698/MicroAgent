from __future__ import annotations

import pytest

from ragflow_lite.application.services.pdf_payload_codec import (
    deserialize_parsed_pdf_document,
    fingerprint_parsed_pdf_document,
    serialize_parsed_pdf_document,
)
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ParsedPdfDocument,
    PdfElement,
    PdfMediaAsset,
    PdfPage,
)


def _payload() -> ParsedPdfDocument:
    return ParsedPdfDocument(
        document_id="doc_pdf",
        filename="paper.pdf",
        parser_strategy="docling_academic_pdf",
        title="Graph Retrieval for Papers",
        authors=["Ada Lovelace"],
        pages=[PdfPage(page_number=1, width=612.0, height=792.0)],
        elements=[
            PdfElement(
                element_id="fig_1",
                element_type="figure",
                text="",
                page_start=1,
                page_end=1,
                bbox=(1.0, 2.0, 3.0, 4.0),
                section_path=["Method"],
                academic_role="figure",
                element_label="Figure 1",
                caption="System overview.",
                media_asset_id="asset_fig_1",
                context_before="Before.",
                context_after="After.",
                metadata={"visual_description": "A pipeline diagram."},
            )
        ],
        media_assets=[
            PdfMediaAsset(
                asset_id="asset_fig_1",
                element_id="fig_1",
                media_type="image/png",
                extension=".png",
                size_bytes=4,
                data=b"data",
                metadata={"source": "docling"},
            )
        ],
        warnings=["pdf_title_missing"],
        degradation_flags=["caption_ambiguous"],
        metadata={"probe": True},
    )


def test_pdf_payload_codec_round_trips_nested_dataclasses() -> None:
    restored = deserialize_parsed_pdf_document(
        serialize_parsed_pdf_document(_payload())
    )

    assert isinstance(restored, ParsedPdfDocument)
    assert isinstance(restored.pages[0], PdfPage)
    assert isinstance(restored.elements[0], PdfElement)
    assert isinstance(restored.media_assets[0], PdfMediaAsset)
    assert restored.media_assets[0].data == b"data"
    assert restored.elements[0].bbox == (1.0, 2.0, 3.0, 4.0)
    assert restored.elements[0].section_path == ["Method"]


def test_pdf_payload_fingerprint_is_stable_across_round_trip() -> None:
    payload = _payload()
    restored = deserialize_parsed_pdf_document(serialize_parsed_pdf_document(payload))

    assert fingerprint_parsed_pdf_document(payload) == fingerprint_parsed_pdf_document(
        restored
    )


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"document_id": "doc", "filename": "paper.pdf", "parser_strategy": "docling_academic_pdf", "title": "Paper", "elements": [{"bad": "shape"}]}',
        '{"document_id": "doc", "filename": "paper.pdf", "parser_strategy": "docling_academic_pdf", "title": "Paper", "media_assets": [{"asset_id": "a"}]}',
    ],
)
def test_pdf_payload_codec_rejects_invalid_cached_shape(raw: str) -> None:
    with pytest.raises(ProcessingError):
        deserialize_parsed_pdf_document(raw)
