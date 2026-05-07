from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import infinity
import pytest
from infinity.common import ConflictType, NetworkAddress

from ragflow_lite.config import Settings
from ragflow_lite.domain.errors import DatasetAlreadyExistsError
from ragflow_lite.domain.models import DocumentAsset, EmbeddedChunk
from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    GraphCandidateInfinityConfig,
    InfinityGraphCandidateIndex,
)
from ragflow_lite.infrastructure.vector_indexes.infinity_dense_index import (
    InfinityDenseVectorIndex,
)

pytestmark = pytest.mark.live_infinity

_DIMS = 8
_SIGNATURE = {"provider": "test", "model": "live-infinity", "dimensions": _DIMS}


class _DeterministicEmbedder:
    signature = _SIGNATURE

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * _DIMS
        lowered = text.lower()
        if any(term in lowered for term in ("python", "django", "graph")):
            vector[0] = 4.0
            vector[1] = 1.0
        if any(term in lowered for term in ("dataset", "document", "chunk")):
            vector[2] = 4.0
            vector[3] = 1.0
        if not any(vector):
            vector[-1] = 1.0
        return vector


def _unique_table(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _connect(settings: Settings) -> Any:
    return infinity.connect(
        NetworkAddress(settings.infinity_host, settings.infinity_port),
    )


def _drop_tables(client: Any, database: str, table_names: list[str]) -> None:
    db = client.get_database(database)
    for table_name in table_names:
        try:
            db.drop_table(table_name, ConflictType.Ignore)
        except Exception:
            pass


def _asset(document_id: str, filename: str = "live.txt") -> DocumentAsset:
    return DocumentAsset(
        document_id=document_id,
        filename=filename,
        file_type="txt",
        storage_path=Path(f"/tmp/{filename}"),
        size_bytes=100,
        created_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
        metadata={"source": "live-test"},
    )


def _chunk(
    document_id: str,
    chunk_id: str,
    text: str,
    vector: list[float],
    index: int = 0,
) -> EmbeddedChunk:
    return EmbeddedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        index=index,
        vector=vector,
        metadata={"section": "live"},
    )


def test_live_dense_index_covers_document_dataset_and_retrieval_lifecycle(
    app_settings: Settings,
) -> None:
    document_table = _unique_table("documents_live")
    chunk_table = _unique_table("chunks_live")
    client = _connect(app_settings)
    index: InfinityDenseVectorIndex | None = None
    table_names = [
        document_table,
        chunk_table,
        f"{document_table}_datasets",
        f"{document_table}_dataset_bindings",
    ]

    try:
        index = InfinityDenseVectorIndex(
            host=app_settings.infinity_host,
            port=app_settings.infinity_port,
            database=app_settings.infinity_database,
            document_table=document_table,
            chunk_table=chunk_table,
            embedding_dimensions=_DIMS,
            embedding_signature=_SIGNATURE,
        )

        asset = _asset("doc_live")
        index.index_document(
            asset,
            [
                _chunk(
                    "doc_live",
                    "chunk_python",
                    "Python and Django graph retrieval",
                    [4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ),
                _chunk(
                    "doc_live",
                    "chunk_dataset",
                    "Dataset binding and document catalog",
                    [0.0, 0.0, 4.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                    index=1,
                ),
            ],
        )

        dense_results = index.search([4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2)
        assert dense_results
        assert dense_results[0].chunk_id == "chunk_python"

        hybrid_results = index.search_hybrid(
            "Python graph",
            [4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            top_k=2,
        )
        assert hybrid_results
        assert hybrid_results[0].chunk_id == "chunk_python"

        dataset = index.create_dataset("live dataset", "real Infinity dataset")
        with pytest.raises(DatasetAlreadyExistsError):
            index.create_dataset("live dataset", "duplicate")
        index.bind_document("doc_live", dataset.dataset_id)
        assert index.get_dataset_id_for_document("doc_live") == dataset.dataset_id
        assert index.get_document_ids_for_dataset(dataset.dataset_id) == ["doc_live"]
        assert index.get_dataset_document_count(dataset.dataset_id) == 1
        assert index.get_document("doc_live").dataset_id == dataset.dataset_id
        assert [doc.document_id for doc in index.list_documents()] == ["doc_live"]

        index.delete_document("doc_live")
        assert index.get_dataset_id_for_document("doc_live") is None
        assert index.search([4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2) == []
    finally:
        if index is not None:
            try:
                index.disconnect()
            except Exception:
                pass
        _drop_tables(client, app_settings.infinity_database, table_names)
        try:
            client.disconnect()
        except Exception:
            pass


def test_live_graph_candidate_index_covers_table_lifecycle_query_and_delete(
    app_settings: Settings,
) -> None:
    entity_table = _unique_table("graph_entities_live")
    relationship_table = _unique_table("graph_relationships_live")
    client = _connect(app_settings)
    embedder = _DeterministicEmbedder()
    index: InfinityGraphCandidateIndex | None = None

    try:
        index = InfinityGraphCandidateIndex(
            client=client,
            database=app_settings.infinity_database,
            embedder=embedder,
            config=GraphCandidateInfinityConfig(
                entity_table=entity_table,
                relationship_table=relationship_table,
                graph_initial_recall_n=16,
            ),
        )

        batch = GraphEvidenceBatch(
            document_id="graph_doc",
            entities=[
                EntityEvidence(
                    entity_id="entity_python",
                    document_id="graph_doc",
                    name="Python",
                    entity_type="language",
                    description="Python language",
                    source_chunk_ids=["chunk_python"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="relation_python_django",
                    document_id="graph_doc",
                    source_entity_id="entity_python",
                    target_entity_id="entity_django",
                    source_entity_name="Python",
                    target_entity_name="Django",
                    description="Python uses Django",
                    keywords=["framework"],
                    weight=1.0,
                    source_chunk_ids=["chunk_python"],
                ),
            ],
        )
        index.upsert_document_evidence(batch)

        entity_candidates = index.query_entities(["Python"], top_k=3)
        assert entity_candidates
        assert entity_candidates[0].entity.entity_id == "entity_python"
        assert entity_candidates[0].metadata["candidate_kind"] == "entity"

        relationship_candidates = index.query_relationships(
            "Python Django framework",
            ["framework"],
            top_k=3,
        )
        assert relationship_candidates
        assert (
            relationship_candidates[0].relation.relation_id == "relation_python_django"
        )
        assert relationship_candidates[0].metadata["candidate_kind"] == "relationship"

        relation = relationship_candidates[0].relation
        assert relation.source_entity_id == "entity_python"
        assert relation.target_entity_id == "entity_django"
        assert relation.source_entity_name == "Python"
        assert relation.target_entity_name == "Django"
        assert (
            relation.description == "python us django"
        )  # tks field: lowercased + tokenized
        assert relation.keywords == ["framework"]
        assert relation.weight == 1.0
        assert relation.source_chunk_ids == ["chunk_python"]

        index.delete_document("graph_doc")
        assert index.query_entities(["Python"], top_k=3) == []
        assert index.query_relationships("Python Django framework", [], top_k=3) == []
    finally:
        _drop_tables(
            client,
            app_settings.infinity_database,
            [entity_table, relationship_table],
        )
        try:
            client.disconnect()
        except Exception:
            pass
