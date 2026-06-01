from __future__ import annotations

from ragflow_lite.domain.models import ParsedDocument, ParsedPdfDocument, PdfElement
from ragflow_lite.infrastructure.chunkers.academic_pdf import AcademicPdfChunker
from ragflow_lite.infrastructure.chunkers.document_chunker import DocumentChunker
from ragflow_lite.infrastructure.chunkers.recursive_character import (
    RecursiveCharacterChunker,
)


def _payload() -> ParsedPdfDocument:
    return ParsedPdfDocument(
        document_id="doc_pdf",
        filename="paper.pdf",
        parser_strategy="docling_academic_pdf",
        title="Graph Retrieval for Papers",
        authors=["Ada Lovelace"],
        elements=[
            PdfElement(
                element_id="abs_1",
                element_type="paragraph",
                text="This paper studies graph retrieval.",
                page_start=1,
                page_end=1,
                section_path=["Abstract"],
                academic_role="abstract",
            ),
            PdfElement(
                element_id="tbl_1",
                element_type="table",
                text="| Method | Recall |\n| Base | 0.5 |",
                page_start=2,
                page_end=2,
                section_path=["Results"],
                academic_role="table",
                element_label="Table 1",
                caption="Retriever comparison.",
                context_before="We compare retriever variants.",
            ),
            PdfElement(
                element_id="fig_1",
                element_type="figure",
                text="",
                page_start=3,
                page_end=3,
                section_path=["Method"],
                academic_role="figure",
                element_label="Figure 1",
                caption="System overview.",
                media_asset_id="asset_fig_1",
                context_after="The figure shows retrieval and graph construction.",
                metadata={
                    "visual_description": "A pipeline diagram.",
                    "figure_description_status": "succeeded",
                },
            ),
        ],
    )


def test_academic_chunker_uses_stable_template_for_table_and_figure() -> None:
    document = ParsedDocument(
        document_id="doc_pdf",
        file_type="pdf",
        raw_text="ignored",
        metadata={"parser_strategy": "docling_academic_pdf"},
        structured_payload=_payload(),
    )

    chunks = AcademicPdfChunker().chunk(document)

    table = next(c for c in chunks if c.metadata.get("pdf_element_type") == "table")
    assert "Paper: Graph Retrieval for Papers" in table.text
    assert "Role: table" in table.text
    assert "Section: Results" in table.text
    assert "Element: Table 1" in table.text
    assert "Caption: Retriever comparison." in table.text
    assert "Context: We compare retriever variants." in table.text
    assert "Body:\n| Method | Recall |" in table.text
    assert table.metadata["paper_title"] == "Graph Retrieval for Papers"
    assert table.metadata["caption"] == "Retriever comparison."

    figure = next(c for c in chunks if c.metadata.get("pdf_element_type") == "figure")
    assert "Caption: System overview." in figure.text
    assert "Visual description: A pipeline diagram." in figure.text
    assert figure.metadata["visual_description"] == "A pipeline diagram."
    assert figure.metadata["figure_description_status"] == "succeeded"
    assert figure.metadata["asset_id"] == "asset_fig_1"


def test_document_chunker_routes_pdf_payload_to_academic_chunker() -> None:
    document = ParsedDocument(
        document_id="doc_pdf",
        file_type="pdf",
        raw_text="ignored",
        metadata={"parser_strategy": "docling_academic_pdf"},
        structured_payload=_payload(),
    )
    chunker = DocumentChunker(
        generic_chunker=RecursiveCharacterChunker(),
        academic_pdf_chunker=AcademicPdfChunker(),
    )

    chunks = chunker.chunk(document)

    assert chunks
    assert all(c.metadata["chunker_strategy"] == "academic_pdf" for c in chunks)


def test_document_chunker_routes_non_pdf_to_generic() -> None:
    document = ParsedDocument(
        document_id="doc_txt",
        file_type="txt",
        raw_text="Hello world",
        metadata={"parser_strategy": "plain_text"},
        structured_payload=None,
    )
    chunker = DocumentChunker(
        generic_chunker=RecursiveCharacterChunker(),
        academic_pdf_chunker=AcademicPdfChunker(),
    )

    chunks = chunker.chunk(document)

    assert chunks
    assert all(c.metadata.get("chunker_strategy") != "academic_pdf" for c in chunks)
