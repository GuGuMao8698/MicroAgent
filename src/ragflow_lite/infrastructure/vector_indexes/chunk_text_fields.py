"""Fielded text helpers for Infinity chunk hybrid retrieval."""

from __future__ import annotations

from ragflow_lite.domain.models.academic_pdf_fields import (
    ACADEMIC_SPARSE_FIELD_DESCRIPTORS,
    academic_weighted_match_fields,
)
from ragflow_lite.infrastructure.nlp import fine_grained_tokenize, tokenize

ACADEMIC_CHUNK_TEXT_FIELDS = tuple(
    field.sparse_field for field in ACADEMIC_SPARSE_FIELD_DESCRIPTORS
)


def _build_match_text_fields() -> str:
    """Build the ordered match-text-fields string from canonical descriptors.

    The interleaving order is:
      filename_kwd^30, paper_title_tks^24, filename_tks^20,
      academic_role_kwd^18, section_tks^12, caption_tks^10,
      media_context_tks^9, visual_description_tks^8,
      element_type_kwd^8, element_label_tks^6,
      content_tks^2, content_sm_tks
    """
    academic_weighted = academic_weighted_match_fields()
    parts = [
        "filename_kwd^30",
        academic_weighted[0],  # paper_title_tks^24
        "filename_tks^20",
        academic_weighted[1],  # academic_role_kwd^18
        academic_weighted[2],  # section_tks^12
        academic_weighted[3],  # caption_tks^10
        academic_weighted[4],  # media_context_tks^9
        academic_weighted[5],  # visual_description_tks^8
        academic_weighted[6],  # element_type_kwd^8
        academic_weighted[7],  # element_label_tks^6
        "content_tks^2",
        "content_sm_tks",
    ]
    return ",".join(parts)


CHUNK_FIELD_MATCH_TEXT_FIELDS = _build_match_text_fields()


def _metadata_text(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if str(item).strip())
    return str(value)


def build_chunk_text_fields(
    *,
    filename: str,
    text: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, str]:
    """Build deterministic RAGFlow-tokenized text fields for chunk rows.

    Raises:
        RAGFlowTokenizerUnavailableError: tokenizer 不可用时直接失败，
            不 fallback 成语义不一致的伪 tks 字段。
    """
    metadata = metadata or {}
    filename_tks = tokenize(filename)
    content_tks = tokenize(text)
    return {
        "filename_kwd": filename,
        "filename_tks": filename_tks,
        "content_tks": content_tks,
        "content_sm_tks": fine_grained_tokenize(content_tks),
        **_build_academic_fields(metadata),
    }


def _build_academic_fields(metadata: dict[str, object]) -> dict[str, str]:
    """Derive all academic sparse fields from metadata using the descriptor."""
    fields: dict[str, str] = {}
    for descriptor in ACADEMIC_SPARSE_FIELD_DESCRIPTORS:
        raw = _metadata_text(metadata, descriptor.metadata_key)
        if descriptor.tokenizer_mode == "ragflow" and raw:
            fields[descriptor.sparse_field] = tokenize(raw)
        else:
            fields[descriptor.sparse_field] = raw
    return fields
