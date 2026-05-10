from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ragflow_lite.domain.errors import ProcessingError

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


# --- MiniRAG graph-first retrieval candidate models ---
# 图优先检索的候选实体/关系及 chunk 支撑模型


@dataclass(slots=True)
class MiniEntityCandidate:
    """实体名称匹配候选 —— 从 EntityNameIndex 查询得到。"""

    entity: EntityEvidence
    score: float
    matched_terms: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class MiniRelationshipCandidate:
    """关系匹配候选 —— 从 RelationshipIndex 查询得到。"""

    relation: RelationEvidence
    score: float
    matched_terms: list[str]
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class SourceChunkSupport:
    """chunk 级聚合支撑信息 —— 记录一个 chunk 被哪些实体/关系/路径命中。"""

    chunk_id: str
    score: float
    score_components: dict[str, float]
    supporting_entity_ids: list[str]
    supporting_relation_ids: list[str]
    supporting_path_ids: list[str]
    auxiliary_chunk_hit: bool = False
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class GraphFirstSource:
    """图优先检索命中的单个 source chunk，携带评分与选择决策。"""

    chunk_id: str
    rank: int
    score: float
    score_components: dict[str, float]
    supporting_entity_ids: list[str]
    supporting_relation_ids: list[str]
    supporting_path_ids: list[str]
    auxiliary_chunk_hit: bool
    selected_for_answer: bool
    selected_for_discourse: bool
    selection_reason: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class GraphFirstSourceSelection:
    """图优先检索的最终 source 选择结果 —— 含被选和被省略的 source 汇总。"""

    sources: list[GraphFirstSource]
    final_context_k: int
    discourse_selection_k: int
    context_token_budget: int | None
    omitted_source_count: int
    fallback_reason: str | None = None
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


# --- DiscoRAG intra-chunk discourse structure models ---


@dataclass(slots=True)
class DiscourseUnit:
    unit_id: str
    canonical_chunk_id: str
    text: str
    order: int
    role: str
    start_char: int | None = None
    end_char: int | None = None
    nuclearity: str | None = None
    rst_relation: str | None = None
    planning_role: str | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class IntraChunkDiscourseRelation:
    relation_id: str
    canonical_chunk_id: str
    source_unit_id: str
    target_unit_id: str
    relation_type: str
    weight: float
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class ChunkDiscourseStructure:
    canonical_chunk_id: str
    document_id: str
    units: list[DiscourseUnit] = field(default_factory=list)
    relations: list[IntraChunkDiscourseRelation] = field(default_factory=list)
    main_unit_ids: list[str] = field(default_factory=list)
    supporting_unit_ids: list[str] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class IntraChunkDiscoursePackage:
    query: str
    evidence_package: EvidencePackage
    structures: list[ChunkDiscourseStructure] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)


# --- DiscoRAG inter-chunk discourse graph models ---
# chunk 间稀疏话语关系，属于答案组织结构而非检索结构


@dataclass(slots=True)
class InterChunkDiscourseRelation:
    """跨 chunk 话语关系 —— 表达 qualifies / contradicts 等稀疏语义连接。"""

    source_chunk_id: str
    target_chunk_id: str
    relation_type: str
    rationale: str | None = None
    confidence: float | None = None
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_chunk_id == self.target_chunk_id:
            raise ProcessingError(
                "Inter-chunk discourse relation must use different chunks."
            )
        if not self.source_chunk_id.strip():
            raise ProcessingError("Inter-chunk source chunk id is required.")
        if not self.target_chunk_id.strip():
            raise ProcessingError("Inter-chunk target chunk id is required.")
        if not self.relation_type.strip():
            raise ProcessingError("Inter-chunk relation type is required.")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ProcessingError(
                "Inter-chunk relation confidence must be between 0 and 1."
            )


@dataclass(slots=True)
class InterChunkDiscourseGraph:
    """跨 chunk 话语图 —— 查询触发的 chunk 间稀疏关系集合。"""

    query: str
    chunk_ids: list[str]
    relations: list[InterChunkDiscourseRelation] = field(default_factory=list)
    metadata: Metadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        known_chunk_ids = set(self.chunk_ids)
        for relation in self.relations:
            if (
                relation.source_chunk_id not in known_chunk_ids
                or relation.target_chunk_id not in known_chunk_ids
            ):
                raise ProcessingError(
                    "Inter-chunk discourse graph contains relation for unknown chunk."
                )


@dataclass(slots=True)
class TopologyPath:
    path_id: str
    document_id: str
    entity_ids: list[str]
    relation_ids: list[str]
    source_chunk_ids: list[str]
    score: float
    candidate_group_id: str | None = None
    candidate_rank: int | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class TopologyRetrievalResult:
    query: str
    grounded_query: GroundedQuery
    chunks: list[RetrievedChunk]
    paths: list[TopologyPath]
    source_selection: GraphFirstSourceSelection | None = None
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
