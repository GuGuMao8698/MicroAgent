from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.errors import UnsupportedFileTypeError
from ragflow_lite.domain.models import DocumentAsset, ParsedPdfDocument
from ragflow_lite.infrastructure.parsers import (
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
    assert decoded == "hello�world"


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
