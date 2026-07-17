from __future__ import annotations

import json
from pathlib import Path

from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    GraphEvidenceWriteResult,
    RelationEvidence,
)
from ragflow_lite.domain.ports.interfaces import GraphEvidenceStore
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)


class SqliteGraphEvidenceStore(GraphEvidenceStore):
    def __init__(
        self,
        db_path: Path,
        *,
        registry: SqliteArtifactRegistry | None = None,
    ) -> None:
        self._db_path = db_path
        self._registry = registry or SqliteArtifactRegistry(db_path)

    def upsert_document_evidence(
        self,
        batch: GraphEvidenceBatch,
    ) -> GraphEvidenceWriteResult:
        build = self._registry.create_build(
            document_id=batch.document_id,
            artifact_type="graph_evidence",
            builder_version=str(
                batch.metadata.get("extractor_version", "graph-evidence-v1")
            ),
            embedding_signature=str(
                batch.metadata.get("embedding_signature", "unknown")
            ),
        )
        metadata_json = _to_json(batch.metadata)
        extractor_version = batch.metadata.get("extractor_version")
        try:
            with self._registry.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO graph_evidence_batches (
                        batch_id,
                        document_id,
                        build_id,
                        extractor_version,
                        metadata_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        build.build_id,
                        batch.document_id,
                        build.build_id,
                        None if extractor_version is None else str(extractor_version),
                        metadata_json,
                        build.created_at,
                    ),
                )
                for ordinal, entity in enumerate(batch.entities):
                    conn.execute(
                        """
                        INSERT INTO graph_entities (
                            entity_id,
                            document_id,
                            build_id,
                            ordinal,
                            name,
                            entity_type,
                            description,
                            metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entity.entity_id,
                            entity.document_id,
                            build.build_id,
                            ordinal,
                            entity.name,
                            entity.entity_type,
                            entity.description,
                            _to_json(entity.metadata),
                        ),
                    )
                    _insert_entity_source_chunks(
                        conn, entity=entity, build_id=build.build_id
                    )
                for ordinal, relation in enumerate(batch.relations):
                    conn.execute(
                        """
                        INSERT INTO graph_relationships (
                            relation_id,
                            document_id,
                            build_id,
                            ordinal,
                            source_entity_id,
                            target_entity_id,
                            source_entity_name,
                            target_entity_name,
                            description,
                            keywords_json,
                            weight,
                            metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            relation.relation_id,
                            relation.document_id,
                            build.build_id,
                            ordinal,
                            relation.source_entity_id,
                            relation.target_entity_id,
                            relation.source_entity_name,
                            relation.target_entity_name,
                            relation.description,
                            _to_json(relation.keywords),
                            relation.weight,
                            _to_json(relation.metadata),
                        ),
                    )
                    _insert_relation_source_chunks(
                        conn, relation=relation, build_id=build.build_id
                    )
        except Exception as exc:
            self._registry.mark_build_failed(
                build.build_id,
                failure_code="sqlite_write_failed",
                failure_stage="write_sqlite",
                retryable=True,
                error_message=str(exc),
            )
            raise

        self._registry.mark_payload_complete(build.build_id)
        return GraphEvidenceWriteResult(
            document_id=batch.document_id,
            entity_count=len(batch.entities),
            relation_count=len(batch.relations),
        )

    def delete_document(self, document_id: str) -> None:
        self._registry.mark_document_deleting(document_id)

    def get_document_evidence(self, document_id: str) -> GraphEvidenceBatch | None:
        active = self._registry.get_active_build("graph_evidence", document_id)
        if active is None or active.status != "active":
            return None
        return self.get_build_evidence(active.build_id)

    def get_build_evidence(self, build_id: str) -> GraphEvidenceBatch | None:
        with self._registry.connect() as conn:
            batch_row = conn.execute(
                """
                SELECT document_id, metadata_json
                FROM graph_evidence_batches
                WHERE build_id = ?
                """,
                (build_id,),
            ).fetchone()
            if batch_row is None:
                return None
            entity_rows = conn.execute(
                """
                SELECT
                    entity_id,
                    document_id,
                    ordinal,
                    name,
                    entity_type,
                    description,
                    metadata_json
                FROM graph_entities
                WHERE build_id = ?
                ORDER BY ordinal ASC, entity_id ASC
                """,
                (build_id,),
            ).fetchall()
            relation_rows = conn.execute(
                """
                SELECT
                    relation_id,
                    document_id,
                    ordinal,
                    source_entity_id,
                    target_entity_id,
                    source_entity_name,
                    target_entity_name,
                    description,
                    keywords_json,
                    weight,
                    metadata_json
                FROM graph_relationships
                WHERE build_id = ?
                ORDER BY ordinal ASC, relation_id ASC
                """,
                (build_id,),
            ).fetchall()

            entities = [
                EntityEvidence(
                    entity_id=str(row["entity_id"]),
                    document_id=str(row["document_id"]),
                    name=str(row["name"]),
                    entity_type=str(row["entity_type"]),
                    description=str(row["description"]),
                    source_chunk_ids=_load_entity_source_chunks(
                        conn,
                        build_id=build_id,
                        document_id=str(row["document_id"]),
                        entity_id=str(row["entity_id"]),
                    ),
                    metadata=_from_json_object(row["metadata_json"]),
                )
                for row in entity_rows
            ]
            relations = [
                RelationEvidence(
                    relation_id=str(row["relation_id"]),
                    document_id=str(row["document_id"]),
                    source_entity_id=str(row["source_entity_id"]),
                    target_entity_id=str(row["target_entity_id"]),
                    source_entity_name=str(row["source_entity_name"]),
                    target_entity_name=str(row["target_entity_name"]),
                    description=str(row["description"]),
                    keywords=_from_json_list(row["keywords_json"]),
                    weight=float(row["weight"]),
                    source_chunk_ids=_load_relation_source_chunks(
                        conn,
                        build_id=build_id,
                        document_id=str(row["document_id"]),
                        relation_id=str(row["relation_id"]),
                    ),
                    metadata=_from_json_object(row["metadata_json"]),
                )
                for row in relation_rows
            ]

        return GraphEvidenceBatch(
            document_id=str(batch_row["document_id"]),
            entities=entities,
            relations=relations,
            metadata=_from_json_object(batch_row["metadata_json"]),
        )


def _insert_entity_source_chunks(
    conn: object,
    *,
    entity: EntityEvidence,
    build_id: str,
) -> None:
    for ordinal, chunk_id in enumerate(entity.source_chunk_ids):
        conn.execute(
            """
            INSERT INTO graph_entity_source_chunks (
                entity_id,
                document_id,
                build_id,
                chunk_id,
                ordinal
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (entity.entity_id, entity.document_id, build_id, chunk_id, ordinal),
        )


def _insert_relation_source_chunks(
    conn: object,
    *,
    relation: RelationEvidence,
    build_id: str,
) -> None:
    for ordinal, chunk_id in enumerate(relation.source_chunk_ids):
        conn.execute(
            """
            INSERT INTO graph_relationship_source_chunks (
                relation_id,
                document_id,
                build_id,
                chunk_id,
                ordinal
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (relation.relation_id, relation.document_id, build_id, chunk_id, ordinal),
        )


def _load_entity_source_chunks(
    conn: object,
    *,
    build_id: str,
    document_id: str,
    entity_id: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT chunk_id
        FROM graph_entity_source_chunks
        WHERE build_id = ? AND document_id = ? AND entity_id = ?
        ORDER BY ordinal ASC, chunk_id ASC
        """,
        (build_id, document_id, entity_id),
    ).fetchall()
    return [str(row["chunk_id"]) for row in rows]


def _load_relation_source_chunks(
    conn: object,
    *,
    build_id: str,
    document_id: str,
    relation_id: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT chunk_id
        FROM graph_relationship_source_chunks
        WHERE build_id = ? AND document_id = ? AND relation_id = ?
        ORDER BY ordinal ASC, chunk_id ASC
        """,
        (build_id, document_id, relation_id),
    ).fetchall()
    return [str(row["chunk_id"]) for row in rows]


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json_object(value: object) -> dict[str, object]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, dict):
        msg = "expected JSON object payload"
        raise ValueError(msg)
    return loaded


def _from_json_list(value: object) -> list[str]:
    loaded = json.loads(str(value))
    if not isinstance(loaded, list):
        msg = "expected JSON list payload"
        raise ValueError(msg)
    return [str(item) for item in loaded]
