from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

Metadata = dict[str, Any]
Vector = list[float]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class DocumentAsset:
    document_id: str
    filename: str
    file_type: str
    storage_path: Path
    size_bytes: int
    created_at: datetime = field(default_factory=utc_now)
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class IndexedDocument:
    document_id: str
    filename: str
    file_type: str
    size_bytes: int
    created_at: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    document_id: str
    file_type: str
    raw_text: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    index: int
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddedChunk:
    chunk_id: str
    document_id: str
    text: str
    index: int
    vector: Vector
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class AnswerResult:
    answer: str
    contexts: list[RetrievedChunk]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class IngestionResult:
    document_id: str
    file_type: str
    chunk_count: int
    status: str
