from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    RelationEvidence,
)


class LocalJsonGraphEvidenceStore:
    """Persist graph evidence as one JSON file per document."""

    def __init__(self, evidence_dir: Path) -> None:
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def upsert_document_evidence(
        self,
        batch: GraphEvidenceBatch,
    ) -> GraphEvidenceWriteResult:
        payload = _batch_to_payload(batch)
        target_path = self._path_for(batch.document_id)
        temp_path = None

        try:
            with NamedTemporaryFile(
                dir=self.evidence_dir,
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

        return GraphEvidenceWriteResult(
            document_id=batch.document_id,
            entity_count=len(batch.entities),
            relation_count=len(batch.relations),
        )

    def delete_document(self, document_id: str) -> None:
        self._path_for(document_id).unlink(missing_ok=True)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        path = self._path_for(document_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _batch_from_payload(payload)

    def _path_for(self, document_id: str) -> Path:
        return self.evidence_dir / f"{document_id}.json"


def _batch_to_payload(batch: GraphEvidenceBatch) -> dict[str, Any]:
    return {
        "document_id": batch.document_id,
        "entities": [
            {
                "entity_id": entity.entity_id,
                "document_id": entity.document_id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "description": entity.description,
                "source_chunk_ids": entity.source_chunk_ids,
                "metadata": entity.metadata,
            }
            for entity in batch.entities
        ],
        "relations": [
            {
                "relation_id": relation.relation_id,
                "document_id": relation.document_id,
                "source_entity_id": relation.source_entity_id,
                "target_entity_id": relation.target_entity_id,
                "source_entity_name": relation.source_entity_name,
                "target_entity_name": relation.target_entity_name,
                "description": relation.description,
                "keywords": relation.keywords,
                "weight": relation.weight,
                "source_chunk_ids": relation.source_chunk_ids,
                "metadata": relation.metadata,
            }
            for relation in batch.relations
        ],
        "metadata": batch.metadata,
    }


def _batch_from_payload(payload: dict[str, Any]) -> GraphEvidenceBatch:
    return GraphEvidenceBatch(
        document_id=payload["document_id"],
        entities=[
            EntityEvidence(
                entity_id=entity["entity_id"],
                document_id=entity["document_id"],
                name=entity["name"],
                entity_type=entity["entity_type"],
                description=entity["description"],
                source_chunk_ids=list(entity["source_chunk_ids"]),
                metadata=dict(entity.get("metadata", {})),
            )
            for entity in payload.get("entities", [])
        ],
        relations=[
            RelationEvidence(
                relation_id=relation["relation_id"],
                document_id=relation["document_id"],
                source_entity_id=relation["source_entity_id"],
                target_entity_id=relation["target_entity_id"],
                source_entity_name=relation["source_entity_name"],
                target_entity_name=relation["target_entity_name"],
                description=relation["description"],
                keywords=list(relation["keywords"]),
                weight=float(relation["weight"]),
                source_chunk_ids=list(relation["source_chunk_ids"]),
                metadata=dict(relation.get("metadata", {})),
            )
            for relation in payload.get("relations", [])
        ],
        metadata=dict(payload.get("metadata", {})),
    )
