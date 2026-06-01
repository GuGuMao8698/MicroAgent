from __future__ import annotations

from ragflow_lite.domain.models.academic_pdf_fields import (
    ACADEMIC_SPARSE_FIELD_DESCRIPTORS,
    academic_fulltext_fields,
    academic_public_metadata_keys,
    academic_sparse_field_names,
    academic_weighted_match_fields,
)


def test_academic_sparse_descriptor_names_match_contract() -> None:
    assert academic_sparse_field_names() == (
        "paper_title_tks",
        "academic_role_kwd",
        "section_tks",
        "caption_tks",
        "media_context_tks",
        "visual_description_tks",
        "element_type_kwd",
        "element_label_tks",
    )


def test_academic_match_fields_are_generated_from_descriptor() -> None:
    assert academic_weighted_match_fields() == (
        "paper_title_tks^24",
        "academic_role_kwd^18",
        "section_tks^12",
        "caption_tks^10",
        "media_context_tks^9",
        "visual_description_tks^8",
        "element_type_kwd^8",
        "element_label_tks^6",
    )


def test_academic_public_metadata_keys_are_generated_from_descriptor() -> None:
    keys = academic_public_metadata_keys()

    assert "paper_title" in keys
    assert "caption" in keys
    assert "visual_description" in keys
    assert "storage_path" not in keys


def test_every_descriptor_has_unique_sparse_field() -> None:
    fields = [
        descriptor.sparse_field for descriptor in ACADEMIC_SPARSE_FIELD_DESCRIPTORS
    ]

    assert len(fields) == len(set(fields))
    assert tuple(fields) == academic_fulltext_fields()
