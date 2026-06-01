from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.errors import DocumentParsingError
from ragflow_lite.domain.models import DocumentAsset, ParsedPdfDocument
from ragflow_lite.infrastructure.parsers.docling_pdf_adapter import (
    DoclingPdfBackend,
    DoclingPdfParser,
    RealDoclingPdfBackend,
)


class FakeDoclingBackend(DoclingPdfBackend):
    def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
        return ParsedPdfDocument(
            document_id="",
            filename=filename,
            parser_strategy="docling_academic_pdf",
            title="Graph Retrieval for Papers",
            authors=["Ada Lovelace"],
            elements=[],
            media_assets=[],
            warnings=[],
        )


def test_docling_pdf_parser_returns_structured_payload() -> None:
    parser = DoclingPdfParser(backend=FakeDoclingBackend())
    asset = DocumentAsset(
        document_id="doc_pdf",
        filename="paper.pdf",
        file_type="pdf",
        storage_path=Path("/tmp/paper.pdf"),
        size_bytes=100,
    )

    parsed = parser.parse(asset, b"%PDF")

    assert parsed.metadata["parser_strategy"] == "docling_academic_pdf"
    assert parsed.structured_payload is not None
    payload = parsed.structured_payload
    assert isinstance(payload, ParsedPdfDocument)
    assert payload.document_id == "doc_pdf"
    assert payload.filename == "paper.pdf"
    assert payload.title == "Graph Retrieval for Papers"


def test_docling_pdf_parser_raises_on_failure() -> None:
    class FailingBackend(DoclingPdfBackend):
        def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
            raise RuntimeError("Docling failed")

    parser = DoclingPdfParser(backend=FailingBackend())
    asset = DocumentAsset(
        document_id="doc_pdf",
        filename="bad.pdf",
        file_type="pdf",
        storage_path=Path("/tmp/bad.pdf"),
        size_bytes=100,
    )

    try:
        parser.parse(asset, b"not a pdf")
    except DocumentParsingError:
        pass
    else:
        raise AssertionError("Expected DocumentParsingError")


class _FakeProv:
    page_no = 1
    bbox = type("Bbox", (), {"l": 1, "t": 2, "r": 3, "b": 4})()


class _CaptionFailingItem:
    prov = [_FakeProv()]
    image = None

    def caption_text(self, doc: object) -> str:
        raise RuntimeError("caption failed")


def test_docling_backend_records_warning_when_table_caption_fails() -> None:
    backend = RealDoclingPdfBackend.__new__(RealDoclingPdfBackend)
    doc = type(
        "Doc",
        (),
        {
            "texts": [],
            "tables": [_CaptionFailingItem()],
            "pictures": [],
        },
    )()

    payload = backend._map_to_parsed_pdf(doc, "paper.pdf")

    assert "table_caption_extraction_failed" in payload.warnings


def test_docling_backend_records_warning_when_picture_caption_fails() -> None:
    backend = RealDoclingPdfBackend.__new__(RealDoclingPdfBackend)
    doc = type(
        "Doc",
        (),
        {
            "texts": [],
            "tables": [],
            "pictures": [_CaptionFailingItem()],
        },
    )()

    payload = backend._map_to_parsed_pdf(doc, "paper.pdf")

    assert "figure_caption_extraction_failed" in payload.warnings
