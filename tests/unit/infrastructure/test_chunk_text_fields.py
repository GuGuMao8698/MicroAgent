from __future__ import annotations

from ragflow_lite.infrastructure.vector_indexes import chunk_text_fields as fields


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
    }
    assert calls == [
        ("tokenize", "MiniRAG Notes.md"),
        ("tokenize", "TypeScript and C++ notes"),
        ("fine", "tok(TypeScript and C++ notes)"),
    ]


def test_chunk_match_text_fields_are_localized_ragflow_boosts() -> None:
    assert (
        fields.CHUNK_FIELD_MATCH_TEXT_FIELDS
        == "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks"
    )
