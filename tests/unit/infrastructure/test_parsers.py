from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ragflow_lite.domain.errors import DocumentParsingError, UnsupportedFileTypeError
from ragflow_lite.domain.models import DocumentAsset, ParsedPdfDocument
from ragflow_lite.infrastructure.parsers import (
    BasicPdfParser,
    CompositeParser,
    MarkdownParser,
    PlainTextParser,
    decode_text,
    flatten_markdown,
)
from ragflow_lite.infrastructure.parsers.docling_pdf_adapter import DoclingPdfBackend


def make_asset(filename: str, file_type: str) -> DocumentAsset:
    return DocumentAsset(
        document_id="doc_test",
        filename=filename,
        file_type=file_type,
        storage_path=Path("/tmp") / filename,
        size_bytes=0,
    )


def test_plain_text_parser_supports_utf8_bom() -> None:
    parser = PlainTextParser()
    asset = make_asset("sample.txt", "txt")

    parsed = parser.parse(asset, "ragflow-lite".encode("utf-8-sig"))

    assert parsed.raw_text == "ragflow-lite"
    assert parsed.metadata["filename"] == "sample.txt"
    assert parsed.metadata["parser_strategy"] == "plain_text"


def test_decode_text_falls_back_with_replacement() -> None:
    decoded = decode_text(b"hello\xffworld")
    assert decoded == "hello\ufffdworld"


def test_markdown_parser_flattens_heading_list_link_and_code_fence() -> None:
    parser = MarkdownParser()
    asset = make_asset("guide.md", "md")
    raw_bytes = (
        "# Title\n"
        "- item one\n"
        "Visit [Docs](https://example.com)\n"
        "```python\nprint('hi')\n```\n"
    ).encode("utf-8")

    parsed = parser.parse(asset, raw_bytes)

    assert "Title" in parsed.raw_text
    assert "item one" in parsed.raw_text
    assert "Docs https://example.com" in parsed.raw_text
    assert "print('hi')" in parsed.raw_text
    assert "#" not in parsed.raw_text
    assert "```" not in parsed.raw_text
    assert parsed.metadata["parser_strategy"] == "markdown_flatten"


def test_flatten_markdown_preserves_underscored_identifiers_and_code() -> None:
    flattened = flatten_markdown(
        (
            "Use _italic_, **bold**, and ~~strike~~.\n"
            "Inline `ragflow_lite.app:app` and foo_bar_baz stay literal.\n"
            "```bash\nuvicorn ragflow_lite.app:app --reload\n```\n"
        )
    )

    assert "italic" in flattened
    assert "bold" in flattened
    assert "strike" in flattened
    assert "_italic_" not in flattened
    assert "**bold**" not in flattened
    assert "~~strike~~" not in flattened
    assert "ragflow_lite.app:app" in flattened
    assert "foo_bar_baz" in flattened
    assert "uvicorn ragflow_lite.app:app --reload" in flattened
    assert "ragflowlite.app" not in flattened


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "documents"
PARSER_LOGGER = "ragflow_lite.infrastructure.parsers.document_parsers"


def test_basic_pdf_parser_extracts_text_from_native_pdf() -> None:
    parser = BasicPdfParser()
    asset = make_asset("sample.pdf", "pdf")
    raw_bytes = (FIXTURES_DIR / "sample.pdf").read_bytes()

    parsed = parser.parse(asset, raw_bytes)

    assert "Hello from PDF test page" in parsed.raw_text
    assert parsed.file_type == "pdf"
    assert parsed.metadata["format"] == "pdf"
    assert parsed.metadata["page_count"] == 1
    assert parsed.metadata["filename"] == "sample.pdf"
    assert parsed.metadata["parser_strategy"] == "docling_academic_pdf"
    page_texts = parsed.metadata["page_texts"]
    assert len(page_texts) == 1
    assert page_texts[0]["page_number"] == 1
    assert "Hello from PDF test page" in page_texts[0]["text"]


def test_basic_pdf_parser_returns_page_texts_for_two_page_pdf() -> None:
    parser = BasicPdfParser()
    asset = make_asset("two_pages.pdf", "pdf")
    raw_bytes = (FIXTURES_DIR / "two_pages.pdf").read_bytes()

    parsed = parser.parse(asset, raw_bytes)

    assert parsed.metadata["page_count"] == 2
    page_texts = parsed.metadata["page_texts"]
    assert len(page_texts) == 2
    assert page_texts[0]["page_number"] == 1
    assert "alpha" in page_texts[0]["text"]
    assert page_texts[1]["page_number"] == 2
    assert "beta" in page_texts[1]["text"]


def test_basic_pdf_parser_raises_on_corrupted_input() -> None:
    parser = BasicPdfParser()
    asset = make_asset("corrupted.pdf", "pdf")

    try:
        parser.parse(asset, b"This is not a valid PDF file content at all")
    except DocumentParsingError:
        pass
    else:
        raise AssertionError("Expected DocumentParsingError for corrupted PDF")


def test_parser_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    parser = BasicPdfParser()
    asset = make_asset("corrupted.pdf", "pdf")

    with caplog.at_level(logging.ERROR, logger=PARSER_LOGGER):
        with pytest.raises(DocumentParsingError):
            parser.parse(asset, b"this is not pdf")

    record = next(
        record for record in caplog.records if record.event == "parser_failed"
    )
    assert record.document_filename == "corrupted.pdf"
    assert record.file_type == "pdf"
    assert record.parser_strategy == "docling_academic_pdf"
    assert record.error_type


def test_basic_pdf_parser_returns_empty_text_for_blank_pdf() -> None:
    parser = BasicPdfParser()
    asset = make_asset("empty.pdf", "pdf")
    raw_bytes = (FIXTURES_DIR / "empty.pdf").read_bytes()

    parsed = parser.parse(asset, raw_bytes)

    assert parsed.raw_text == ""
    assert parsed.metadata["page_count"] == 1


def test_basic_pdf_parser_raises_on_encrypted_pdf() -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret")
    buf = BytesIO()
    writer.write(buf)
    encrypted_bytes = buf.getvalue()

    parser = BasicPdfParser()
    asset = make_asset("encrypted.pdf", "pdf")

    try:
        parser.parse(asset, encrypted_bytes)
    except DocumentParsingError:
        pass
    else:
        raise AssertionError("Expected DocumentParsingError for encrypted PDF")


def test_composite_parser_dispatches_by_file_type() -> None:
    class _StubBackend(DoclingPdfBackend):
        def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
            return ParsedPdfDocument(
                document_id="",
                filename=filename,
                parser_strategy="docling_academic_pdf",
                title="",
                elements=[],
                media_assets=[],
                warnings=[],
            )

    parser = CompositeParser(pdf_backend=_StubBackend())

    txt_asset = make_asset("test.txt", "txt")
    parsed = parser.parse(txt_asset, b"hello")
    assert parsed.metadata["parser_strategy"] == "plain_text"

    md_asset = make_asset("test.md", "md")
    parsed = parser.parse(md_asset, b"# Hello")
    assert parsed.metadata["parser_strategy"] == "markdown_flatten"

    pdf_asset = make_asset("sample.pdf", "pdf")
    pdf_bytes = (FIXTURES_DIR / "sample.pdf").read_bytes()
    parsed = parser.parse(pdf_asset, pdf_bytes)
    assert parsed.metadata["parser_strategy"] == "docling_academic_pdf"


def test_composite_parser_raises_on_unsupported_file_type() -> None:
    class _StubBackend(DoclingPdfBackend):
        def convert(self, raw_bytes: bytes, filename: str) -> ParsedPdfDocument:
            return ParsedPdfDocument(
                document_id="",
                filename=filename,
                parser_strategy="docling_academic_pdf",
                title="",
                elements=[],
                media_assets=[],
                warnings=[],
            )

    parser = CompositeParser(pdf_backend=_StubBackend())
    asset = make_asset("test.xyz", "xyz")

    try:
        parser.parse(asset, b"content")
    except UnsupportedFileTypeError:
        pass
    else:
        raise AssertionError(
            "Expected UnsupportedFileTypeError for unsupported file type"
        )
