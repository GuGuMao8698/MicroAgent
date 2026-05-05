"""图候选向量旁路存储：为实体和关系候选提供确定性嵌入文本构建与 JSON 持久化。

每个文档的候选向量独立存储为 ``{document_id}.json``，支持：
- rebuild_document: 重建单个文档的候选向量
- delete_document: 删除单个文档的候选向量
- load_all: 加载全部文档的候选向量，并在加载时校验嵌入签名
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GraphCandidateVectorRecord:
    """单条候选向量记录（实体或关系）。"""

    candidate_id: str
    document_id: str
    candidate_kind: str  # "entity" 或 "relationship"
    embedding_text: str
    vector: list[float]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class GraphCandidateVectorSnapshot:
    """load_all 返回的快照，包含所有实体和关系候选向量。"""

    entities: list[GraphCandidateVectorRecord]
    relationships: list[GraphCandidateVectorRecord]


# ---------------------------------------------------------------------------
# 本地协议：只要求 embed_query
# ---------------------------------------------------------------------------


class QueryEmbedder(Protocol):
    """旁路存储使用的嵌入协议，仅需 embed_query 方法。"""

    def embed_query(self, query: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# 嵌入文本构建
# ---------------------------------------------------------------------------


def build_entity_embedding_text(entity: EntityEvidence) -> str:
    """实体嵌入文本只使用 entity.name，不含 description 和 type。"""
    return entity.name


def build_relationship_embedding_text(relation: RelationEvidence) -> str:
    """关系嵌入文本由 source_name、target_name、keywords、description 四部分以换行拼接。"""
    keywords_text = " ".join(relation.keywords)
    return (
        f"{relation.source_entity_name}\n"
        f"{relation.target_entity_name}\n"
        f"{keywords_text}\n"
        f"{relation.description}"
    )


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


def _record_to_payload(record: GraphCandidateVectorRecord) -> dict:
    return {
        "candidate_id": record.candidate_id,
        "document_id": record.document_id,
        "candidate_kind": record.candidate_kind,
        "embedding_text": record.embedding_text,
        "vector": record.vector,
        "metadata": record.metadata,
    }


def _record_from_payload(payload: dict) -> GraphCandidateVectorRecord:
    return GraphCandidateVectorRecord(
        candidate_id=payload["candidate_id"],
        document_id=payload["document_id"],
        candidate_kind=payload["candidate_kind"],
        embedding_text=payload["embedding_text"],
        vector=list(payload["vector"]),
        metadata=dict(payload.get("metadata", {})),
    )


class GraphCandidateSidecar:
    """图候选向量旁路存储，管理每文档的 JSON 持久化和嵌入签名校验。

    Parameters
    ----------
    sidecar_dir:
        存储 JSON 文件的目录。
    embedding_signature:
        嵌入签名字典，写入 JSON 时记录，加载时校验一致性。
    """

    def __init__(
        self,
        sidecar_dir: Path,
        embedding_signature: dict[str, str | int | None],
    ) -> None:
        self._sidecar_dir = sidecar_dir
        self._sidecar_dir.mkdir(parents=True, exist_ok=True)
        self._embedding_signature = embedding_signature

    # ----- 公共接口 -----

    def rebuild_document(
        self, batch: GraphEvidenceBatch, embedder: QueryEmbedder
    ) -> None:
        """重建指定文档的候选向量并持久化。"""
        entities = [self._build_entity_record(ent, embedder) for ent in batch.entities]
        relationships = [
            self._build_relationship_record(rel, embedder) for rel in batch.relations
        ]
        self._write_document(batch.document_id, entities, relationships)

    def delete_document(self, document_id: str) -> None:
        """删除指定文档的候选向量文件。"""
        path = self._path_for(document_id)
        path.unlink(missing_ok=True)

    def load_all(self) -> GraphCandidateVectorSnapshot:
        """加载所有文档的候选向量，校验嵌入签名。

        Raises
        ------
        ProcessingError
            如果任何 JSON 文件的嵌入签名与构造时签名不匹配。
        """
        all_entities: list[GraphCandidateVectorRecord] = []
        all_relationships: list[GraphCandidateVectorRecord] = []

        for path in sorted(self._sidecar_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))

            # 签名校验
            file_sig = payload.get("embedding_signature")
            if file_sig != self._embedding_signature:
                raise ProcessingError(
                    f"Embedding signature mismatch in {path.name}: "
                    f"expected {self._embedding_signature}, got {file_sig}"
                )

            for ent_payload in payload.get("entities", []):
                all_entities.append(_record_from_payload(ent_payload))
            for rel_payload in payload.get("relationships", []):
                all_relationships.append(_record_from_payload(rel_payload))

        return GraphCandidateVectorSnapshot(
            entities=all_entities,
            relationships=all_relationships,
        )

    # ----- 内部方法 -----

    def _build_entity_record(
        self, entity: EntityEvidence, embedder: QueryEmbedder
    ) -> GraphCandidateVectorRecord:
        """为单个实体构建向量记录。"""
        text = build_entity_embedding_text(entity)
        vector = embedder.embed_query(text)
        return GraphCandidateVectorRecord(
            candidate_id=entity.entity_id,
            document_id=entity.document_id,
            candidate_kind="entity",
            embedding_text=text,
            vector=vector,
            metadata={
                "entity_type": entity.entity_type,
                "name": entity.name,
            },
        )

    def _build_relationship_record(
        self, relation: RelationEvidence, embedder: QueryEmbedder
    ) -> GraphCandidateVectorRecord:
        """为单个关系构建向量记录。"""
        text = build_relationship_embedding_text(relation)
        vector = embedder.embed_query(text)
        return GraphCandidateVectorRecord(
            candidate_id=relation.relation_id,
            document_id=relation.document_id,
            candidate_kind="relationship",
            embedding_text=text,
            vector=vector,
            metadata={
                "source_entity_name": relation.source_entity_name,
                "target_entity_name": relation.target_entity_name,
                "keywords": list(relation.keywords),
            },
        )

    def _write_document(
        self,
        document_id: str,
        entities: list[GraphCandidateVectorRecord],
        relationships: list[GraphCandidateVectorRecord],
    ) -> None:
        """原子写入单个文档的候选向量 JSON 文件。"""
        payload = {
            "embedding_signature": self._embedding_signature,
            "entities": [_record_to_payload(r) for r in entities],
            "relationships": [_record_to_payload(r) for r in relationships],
        }
        target_path = self._path_for(document_id)
        temp_path = None

        try:
            with NamedTemporaryFile(
                dir=self._sidecar_dir,
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False)
                temp_path = Path(handle.name)
            os.replace(temp_path, target_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def _path_for(self, document_id: str) -> Path:
        """返回指定文档的 JSON 文件路径。"""
        return self._sidecar_dir / f"{document_id}.json"
