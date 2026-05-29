"""Fielded text helpers for Infinity chunk hybrid retrieval."""

from __future__ import annotations

from ragflow_lite.infrastructure.nlp import fine_grained_tokenize, tokenize

ACADEMIC_CHUNK_TEXT_FIELDS = (
    "paper_title_tks",
    "academic_role_kwd",
    "section_tks",
    "caption_tks",
    "media_context_tks",
    "visual_description_tks",
    "element_type_kwd",
    "element_label_tks",
)

CHUNK_FIELD_MATCH_TEXT_FIELDS = (
    "filename_kwd^30,"
    "paper_title_tks^24,"
    "filename_tks^20,"
    "academic_role_kwd^18,"
    "section_tks^12,"
    "caption_tks^10,"
    "media_context_tks^9,"
    "visual_description_tks^8,"
    "element_type_kwd^8,"
    "element_label_tks^6,"
    "content_tks^2,"
    "content_sm_tks"
)


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
    paper_title = _metadata_text(metadata, "paper_title")
    section = _metadata_text(metadata, "section_path")
    caption = _metadata_text(metadata, "caption")
    media_context = _metadata_text(metadata, "media_context")
    visual_description = _metadata_text(metadata, "visual_description")
    element_label = _metadata_text(metadata, "element_label")
    academic_role = _metadata_text(metadata, "academic_role")
    element_type = _metadata_text(metadata, "pdf_element_type")
    return {
        "filename_kwd": filename,
        "filename_tks": filename_tks,
        "content_tks": content_tks,
        "content_sm_tks": fine_grained_tokenize(content_tks),
        "paper_title_tks": tokenize(paper_title) if paper_title else "",
        "academic_role_kwd": academic_role,
        "section_tks": tokenize(section) if section else "",
        "caption_tks": tokenize(caption) if caption else "",
        "media_context_tks": tokenize(media_context) if media_context else "",
        "visual_description_tks": tokenize(visual_description)
        if visual_description
        else "",
        "element_type_kwd": element_type,
        "element_label_tks": tokenize(element_label) if element_label else "",
    }
