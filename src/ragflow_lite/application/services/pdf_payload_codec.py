"""Typed codec for serializing, deserializing, and fingerprinting ParsedPdfDocument.

Handles base64 encoding of binary media asset data and reconstructs nested
dataclasses (PdfPage, PdfElement, PdfMediaAsset) instead of leaving them as
plain dicts.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ParsedPdfDocument,
    PdfElement,
    PdfMediaAsset,
    PdfPage,
)


def serialize_parsed_pdf_document(payload: ParsedPdfDocument) -> str:
    data = asdict(payload)
    for asset in data.get("media_assets", []):
        raw = asset.get("data")
        if raw is not None:
            asset["data"] = base64.b64encode(raw).decode("ascii")
            asset["data_encoding"] = "base64"
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def deserialize_parsed_pdf_document(raw: str) -> ParsedPdfDocument:
    try:
        data = json.loads(raw)
        pages = [_page(page) for page in data.get("pages", [])]
        elements = [_element(element) for element in data.get("elements", [])]
        media_assets = [_media_asset(asset) for asset in data.get("media_assets", [])]
        return ParsedPdfDocument(
            document_id=_required_str(data, "document_id"),
            filename=_required_str(data, "filename"),
            parser_strategy=_required_str(data, "parser_strategy"),
            title=_required_str(data, "title"),
            authors=list(data.get("authors", [])),
            pages=pages,
            elements=elements,
            media_assets=media_assets,
            warnings=list(data.get("warnings", [])),
            degradation_flags=list(data.get("degradation_flags", [])),
            metadata=dict(data.get("metadata", {})),
        )
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("Invalid cached academic PDF payload.") from exc


def fingerprint_parsed_pdf_document(payload: ParsedPdfDocument) -> str:
    return hashlib.sha256(
        serialize_parsed_pdf_document(payload).encode("utf-8")
    ).hexdigest()


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProcessingError(f"Invalid cached academic PDF payload: missing '{key}'.")
    return value


def _page(data: Any) -> PdfPage:
    if not isinstance(data, dict) or "page_number" not in data:
        raise ProcessingError("Invalid cached academic PDF page payload.")
    return PdfPage(
        page_number=int(data["page_number"]),
        width=data.get("width"),
        height=data.get("height"),
    )


def _element(data: Any) -> PdfElement:
    if not isinstance(data, dict):
        raise ProcessingError("Invalid cached academic PDF element payload.")
    return PdfElement(
        element_id=_required_str(data, "element_id"),
        element_type=_required_str(data, "element_type"),
        text=str(data.get("text", "")),
        page_start=data.get("page_start"),
        page_end=data.get("page_end"),
        bbox=tuple(data["bbox"]) if data.get("bbox") is not None else None,
        section_path=list(data.get("section_path", [])),
        academic_role=data.get("academic_role"),
        element_label=data.get("element_label"),
        caption=data.get("caption"),
        media_asset_id=data.get("media_asset_id"),
        context_before=data.get("context_before"),
        context_after=data.get("context_after"),
        metadata=dict(data.get("metadata", {})),
    )


def _media_asset(data: Any) -> PdfMediaAsset:
    if not isinstance(data, dict):
        raise ProcessingError("Invalid cached academic PDF media payload.")
    encoded = data.get("data")
    media_bytes = None
    if encoded is not None:
        if data.get("data_encoding") != "base64":
            raise ProcessingError("Invalid cached academic PDF media encoding.")
        media_bytes = base64.b64decode(str(encoded).encode("ascii"))
    return PdfMediaAsset(
        asset_id=_required_str(data, "asset_id"),
        element_id=_required_str(data, "element_id"),
        media_type=_required_str(data, "media_type"),
        extension=_required_str(data, "extension"),
        size_bytes=int(data.get("size_bytes", 0)),
        data=media_bytes,
        staged_path=data.get("staged_path"),
        metadata=dict(data.get("metadata", {})),
    )
