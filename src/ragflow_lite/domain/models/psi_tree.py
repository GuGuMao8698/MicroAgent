from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ragflow_lite.domain.models.entities import Metadata

PsiNodeType = Literal["root", "internal", "leaf"]
PsiAbstractType = Literal["summative", "keyword"]
PsiEvidenceRole = Literal["leaf", "descendant", "summary_source"]


@dataclass(slots=True)
class PsiTree:
    build_id: str
    document_id: str
    max_layer: int
    highest_queryable_layer: int | None
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class PsiNode:
    node_id: str
    build_id: str
    layer: int
    node_type: PsiNodeType
    abstract_type: PsiAbstractType | None
    text: str
    summary_text: str | None
    keyword_text: str | None
    source_document_id: str
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class PsiTreeEdge:
    build_id: str
    parent_node_id: str
    child_node_id: str
    child_rank: int
    edge_score: float
    metadata: Metadata = field(default_factory=dict)


@dataclass(slots=True)
class PsiNodeSourceMapping:
    build_id: str
    node_id: str
    source_chunk_id: str
    source_rank: int
    evidence_role: PsiEvidenceRole
