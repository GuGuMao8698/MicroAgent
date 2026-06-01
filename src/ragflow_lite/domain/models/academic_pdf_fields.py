from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TokenizerMode = Literal["raw", "ragflow"]


@dataclass(frozen=True, slots=True)
class AcademicSparseFieldDescriptor:
    metadata_key: str
    sparse_field: str
    tokenizer_mode: TokenizerMode
    match_weight: int
    fulltext_index: bool = True
    public_metadata: bool = True


ACADEMIC_SPARSE_FIELD_DESCRIPTORS = (
    AcademicSparseFieldDescriptor("paper_title", "paper_title_tks", "ragflow", 24),
    AcademicSparseFieldDescriptor("academic_role", "academic_role_kwd", "raw", 18),
    AcademicSparseFieldDescriptor("section_path", "section_tks", "ragflow", 12),
    AcademicSparseFieldDescriptor("caption", "caption_tks", "ragflow", 10),
    AcademicSparseFieldDescriptor("media_context", "media_context_tks", "ragflow", 9),
    AcademicSparseFieldDescriptor(
        "visual_description", "visual_description_tks", "ragflow", 8
    ),
    AcademicSparseFieldDescriptor("pdf_element_type", "element_type_kwd", "raw", 8),
    AcademicSparseFieldDescriptor("element_label", "element_label_tks", "ragflow", 6),
)


def academic_sparse_field_names() -> tuple[str, ...]:
    return tuple(field.sparse_field for field in ACADEMIC_SPARSE_FIELD_DESCRIPTORS)


def academic_fulltext_fields() -> tuple[str, ...]:
    return tuple(
        field.sparse_field
        for field in ACADEMIC_SPARSE_FIELD_DESCRIPTORS
        if field.fulltext_index
    )


def academic_weighted_match_fields() -> tuple[str, ...]:
    return tuple(
        f"{field.sparse_field}^{field.match_weight}"
        for field in ACADEMIC_SPARSE_FIELD_DESCRIPTORS
    )


def academic_public_metadata_keys() -> frozenset[str]:
    return frozenset(
        field.metadata_key
        for field in ACADEMIC_SPARSE_FIELD_DESCRIPTORS
        if field.public_metadata
    )
