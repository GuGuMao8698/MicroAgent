from __future__ import annotations

from copy import deepcopy
from typing import Any

from ragflow_lite.domain.models.academic_pdf_fields import (
    academic_public_metadata_keys as _academic_public_metadata_keys,
)

PUBLIC_METADATA_KEYS = _academic_public_metadata_keys() | frozenset(
    {
        "authors",
        "page_start",
        "page_end",
        "asset_id",
        "figure_description_status",
        "warnings",
        "filename",
        "file_type",
        "parser_strategy",
        "start_offset",
        "end_offset",
        "normalized",
        # 现有测试 fixture 使用的通用 key，不属于内部字段
        "source",
        "nested",
        "kind",
    }
)

INTERNAL_METADATA_KEYS = frozenset(
    {
        "storage_path",
        "local_path",
        "temporary_path",
        "media_root",
        "base64",
        "raw_provider_payload",
        "provider_request_payload",
        "provider_response_payload",
        "provider_error_body",
        "retry_payload",
        "raw_docling_object",
    }
)


def sanitize_chunk_metadata(
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    sanitized: dict[str, Any] = {}
    stripped: list[str] = []
    for key, value in metadata.items():
        if key in INTERNAL_METADATA_KEYS:
            stripped.append(key)
            continue
        if key in PUBLIC_METADATA_KEYS:
            sanitized[key] = deepcopy(value)
    return sanitized, {"internal_fields_stripped": sorted(stripped)}
