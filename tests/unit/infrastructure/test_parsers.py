from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.errors import DocumentParsingError
from ragflow_lite.domain.models import DocumentAsset
from ragflow_lite.infrastructure.parsers import (
    BasicPdfParser,
    MarkdownParser,
    PlainTextParser,
    decode_text,
    flatten_markdown,
)


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


def test_basic_pdf_parser_raises_on_corrupted_input() -> None:
    parser = BasicPdfParser()
    asset = make_asset("corrupted.pdf", "pdf")

    try:
        parser.parse(asset, b"This is not a valid PDF file content at all")
    except DocumentParsingError:
        pass
    else:
        raise AssertionError("Expected DocumentParsingError for corrupted PDF")


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
