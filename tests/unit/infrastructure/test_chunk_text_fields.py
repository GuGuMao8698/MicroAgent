from __future__ import annotations

from ragflow_lite.infrastructure.vector_indexes import chunk_text_fields as fields
from ragflow_lite.infrastructure.vector_indexes.chunk_text_fields import (
    ACADEMIC_CHUNK_TEXT_FIELDS,
    CHUNK_FIELD_MATCH_TEXT_FIELDS,
    build_chunk_text_fields,
)


def test_build_chunk_text_fields_uses_filename_and_text(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_tokenize(text: str) -> str:
        calls.append(("tokenize", text))
        return f"tok({text})"

    def fake_fine(tokens: str) -> str:
        calls.append(("fine", tokens))
        return f"fine({tokens})"

    monkeypatch.setattr(fields, "tokenize", fake_tokenize)
    monkeypatch.setattr(fields, "fine_grained_tokenize", fake_fine)

    row_fields = fields.build_chunk_text_fields(
        filename="MiniRAG Notes.md",
        text="TypeScript and C++ notes",
    )

    assert row_fields == {
        "filename_kwd": "MiniRAG Notes.md",
        "filename_tks": "tok(MiniRAG Notes.md)",
        "content_tks": "tok(TypeScript and C++ notes)",
        "content_sm_tks": "fine(tok(TypeScript and C++ notes))",
        "paper_title_tks": "",
        "academic_role_kwd": "",
        "section_tks": "",
        "caption_tks": "",
        "media_context_tks": "",
        "visual_description_tks": "",
        "element_type_kwd": "",
        "element_label_tks": "",
    }
    assert calls == [
        ("tokenize", "MiniRAG Notes.md"),
        ("tokenize", "TypeScript and C++ notes"),
        ("fine", "tok(TypeScript and C++ notes)"),
    ]


def test_chunk_match_text_fields_are_localized_ragflow_boosts() -> None:
    assert (
        fields.CHUNK_FIELD_MATCH_TEXT_FIELDS
        == "filename_kwd^30,paper_title_tks^24,filename_tks^20,academic_role_kwd^18,section_tks^12,caption_tks^10,media_context_tks^9,visual_description_tks^8,element_type_kwd^8,element_label_tks^6,content_tks^2,content_sm_tks"
    )


def test_academic_sparse_fields_are_derived_from_metadata() -> None:
    row_fields = build_chunk_text_fields(
        filename="paper.pdf",
        text="Body text",
        metadata={
            "paper_title": "Graph Retrieval for Papers",
            "academic_role": "figure",
            "section_path": ["Method", "Architecture"],
            "caption": "Overview of the pipeline.",
            "media_context": "The figure explains the graph construction step.",
            "visual_description": "A pipeline diagram.",
            "pdf_element_type": "figure",
            "element_label": "Figure 1",
        },
    )

    for field_name in ACADEMIC_CHUNK_TEXT_FIELDS:
        assert field_name in row_fields

    assert row_fields["paper_title_tks"]
    assert row_fields["academic_role_kwd"] == "figure"
    assert row_fields["section_tks"]
    assert row_fields["caption_tks"]
    assert row_fields["media_context_tks"]
    assert row_fields["visual_description_tks"]
    assert row_fields["element_type_kwd"] == "figure"
    assert row_fields["element_label_tks"]


def test_non_pdf_chunks_get_empty_academic_sparse_fields() -> None:
    row_fields = build_chunk_text_fields(filename="note.txt", text="hello", metadata={})

    for field_name in ACADEMIC_CHUNK_TEXT_FIELDS:
        assert row_fields[field_name] == ""


def test_match_text_includes_academic_fields_with_expected_weights() -> None:
    assert "paper_title_tks^24" in CHUNK_FIELD_MATCH_TEXT_FIELDS
    assert "caption_tks^10" in CHUNK_FIELD_MATCH_TEXT_FIELDS
    assert "media_context_tks^9" in CHUNK_FIELD_MATCH_TEXT_FIELDS
