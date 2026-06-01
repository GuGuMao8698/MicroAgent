from __future__ import annotations

from dataclasses import asdict

from ragflow_lite.domain.models import (
    AcademicPdfIngestionSummary,
    ParsedDocument,
    ParsedPdfDocument,
    PdfElement,
    PdfMediaAsset,
    PdfPage,
)


def test_parsed_document_carries_optional_structured_payload() -> None:
    parsed = ParsedDocument(
        document_id="doc_pdf",
        file_type="pdf",
        raw_text="Paper text",
        metadata={"parser_strategy": "docling_academic_pdf"},
        structured_payload=None,
    )

    assert parsed.structured_payload is None


def test_parsed_pdf_document_is_dataclass_serializable() -> None:
    payload = ParsedPdfDocument(
        document_id="doc_pdf",
        filename="paper.pdf",
        parser_strategy="docling_academic_pdf",
        title="A Useful Paper",
        authors=["Ada Lovelace"],
        pages=[PdfPage(page_number=1, width=600.0, height=800.0)],
        elements=[
            PdfElement(
                element_id="el_1",
                element_type="paragraph",
                text="Body text",
                page_start=1,
                page_end=1,
                bbox=None,
                section_path=["Introduction"],
                academic_role="body",
            )
        ],
        media_assets=[
            PdfMediaAsset(
                asset_id="asset_fig_1",
                element_id="fig_1",
                media_type="image/png",
                extension=".png",
                size_bytes=10,
                data=b"0123456789",
            )
        ],
        warnings=["pdf_author_missing"],
        degradation_flags=[],
    )

    dumped = asdict(payload)

    assert dumped["title"] == "A Useful Paper"
    assert dumped["elements"][0]["element_type"] == "paragraph"
    assert dumped["media_assets"][0]["data"] == b"0123456789"


def test_academic_pdf_ingestion_summary_has_stable_status_fields() -> None:
    summary = AcademicPdfIngestionSummary(
        document_id="doc_pdf",
        status="success",
        parser_strategy="docling_academic_pdf",
        parse_source="cold",
        structured_payload_present=True,
        structured_payload_fingerprint_present=True,
        chunker_strategy="academic_pdf",
    )

    assert summary.status == "success"
    assert summary.chunker_strategy == "academic_pdf"
    assert summary.warning_codes == []
