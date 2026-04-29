from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
    dataset_id: str | None = None


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
class AnswerBlueprint:
    ordered_chunk_ids: list[str]
    chunk_roles: dict[str, str]
    answer_constraints: list[str]
    plan_steps: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class AnswerRequest:
    query: str
    contexts: list[RetrievedChunk]
    mode: Literal["standard", "discorag"] = "standard"
    blueprint: AnswerBlueprint | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class AnswerResult:
    answer: str
    contexts: list[RetrievedChunk]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class Dataset:
    dataset_id: str
    name: str
    description: str
    created_at: str


@dataclass(slots=True)
class IngestionResult:
    document_id: str
    file_type: str
    chunk_count: int
    status: str
    dataset_id: str | None = None


# ---------------------------------------------------------------------------
# Graph evidence models (MiniRAG)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EntityEvidence:
    entity_id: str
    document_id: str
    name: str
    entity_type: str
    description: str
    source_chunk_ids: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class RelationEvidence:
    relation_id: str
    document_id: str
    source_entity_id: str
    target_entity_id: str
    source_entity_name: str
    target_entity_name: str
    description: str
    keywords: list[str]
    weight: float
    source_chunk_ids: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class GraphEvidenceBatch:
    document_id: str
    entities: list[EntityEvidence]
    relations: list[RelationEvidence]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class GraphEvidenceWriteResult:
    document_id: str
    entity_count: int
    relation_count: int


@dataclass(slots=True)
class GroundedQuery:
    query: str
    answer_type_keywords: list[str]
    entities_from_query: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceProvenance:
    document_id: str
    filename: str | None = None
    file_type: str | None = None
    chunk_index: int | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceItem:
    canonical_chunk_id: str
    text: str
    score: float
    order: int
    provenance: EvidenceProvenance
    retained_reasons: list[str] = field(default_factory=list)
    grounded_entities: list[str] = field(default_factory=list)
    answer_type_keywords: list[str] = field(default_factory=list)
    topology_path_ids: list[str] = field(default_factory=list)
    topology_relation_ids: list[str] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class EvidencePackage:
    query: str
    grounded_query: GroundedQuery
    items: list[EvidenceItem] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class TopologyPath:
    path_id: str
    document_id: str
    entity_ids: list[str]
    relation_ids: list[str]
    source_chunk_ids: list[str]
    score: float
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class TopologyRetrievalResult:
    query: str
    grounded_query: GroundedQuery
    chunks: list[RetrievedChunk]
    paths: list[TopologyPath]
    metadata: Metadata = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Async ingestion task snapshot
# ---------------------------------------------------------------------------

# Task status values
TASK_QUEUED = "queued"
TASK_PROCESSING = "processing"
TASK_INDEXED = "indexed"
TASK_FAILED = "failed"

# Processing step values
STEP_PARSING = "parsing"
STEP_NORMALIZING = "normalizing"
STEP_CHUNKING = "chunking"
STEP_GRAPH_EVIDENCE = "graph_evidence"
STEP_EMBEDDING = "embedding"
STEP_INDEXING = "indexing"
STEP_BINDING = "binding"

# Fixed progress mapping per step
STEP_PROGRESS: dict[str, int] = {
    STEP_PARSING: 15,
    STEP_NORMALIZING: 30,
    STEP_CHUNKING: 45,
    STEP_EMBEDDING: 60,
    STEP_INDEXING: 80,
    STEP_BINDING: 95,
}

MAX_ATTEMPTS = 2


@dataclass(slots=True)
class IngestionTaskSnapshot:
    """异步 ingestion 任务的不可变快照。"""

    document_id: str
    idempotency_key: str
    status: str
    step: str | None
    progress_percent: int
    attempt: int
    file_type: str
    dataset_id: str | None
    chunk_count: int | None
    error: str | None
    filename: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
