"""Fielded text helpers for Infinity chunk hybrid retrieval."""

from __future__ import annotations

from ragflow_lite.infrastructure.nlp import fine_grained_tokenize, tokenize

# 迁移窗口：旧行只有 filename / text，保留稀疏召回。
CHUNK_LEGACY_MATCH_TEXT_FIELDS = "filename^10,text"

CHUNK_FIELD_MATCH_TEXT_FIELDS = (
    "filename_kwd^30,filename_tks^20,content_tks^2,content_sm_tks,"
    f"{CHUNK_LEGACY_MATCH_TEXT_FIELDS}"
)


def build_chunk_text_fields(*, filename: str, text: str) -> dict[str, str]:
    """Build deterministic RAGFlow-tokenized text fields for chunk rows.

    Raises:
        RAGFlowTokenizerUnavailableError: tokenizer 不可用时直接失败，
            不 fallback 成语义不一致的伪 tks 字段。
    """
    filename_tks = tokenize(filename)
    content_tks = tokenize(text)
    return {
        "filename_kwd": filename,
        "filename_tks": filename_tks,
        "content_tks": content_tks,
        "content_sm_tks": fine_grained_tokenize(content_tks),
    }
