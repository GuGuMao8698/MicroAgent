from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_evidence_index import (
    LocalJsonGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.evidence.local_json_store import (
    LocalJsonGraphEvidenceStore,
)
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_index import (
    SqliteGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_store import (
    SqliteGraphEvidenceStore,
)


def _activate_latest_graph_build(db_path: Path, document_id: str) -> None:
    registry = SqliteArtifactRegistry(db_path)
    build = registry.get_latest_build("graph_evidence", document_id)

    assert build is not None

    projection = registry.create_projection(
        build_id=build.build_id,
        target="infinity_graph_candidate",
        target_table="graph_candidates",
    )
    registry.mark_projection_projected(projection.projection_id)
    registry.activate_build(build.build_id)


def _write_batch(
    store: SqliteGraphEvidenceStore,
    db_path: Path,
    batch: GraphEvidenceBatch,
) -> None:
    store.upsert_document_evidence(batch)
    _activate_latest_graph_build(db_path, batch.document_id)


def _write_pending_batch(
    store: SqliteGraphEvidenceStore,
    batch: GraphEvidenceBatch,
) -> None:
    store.upsert_document_evidence(batch)


def _fixture_batch() -> GraphEvidenceBatch:
    return GraphEvidenceBatch(
        document_id="doc-1",
        entities=[
            EntityEvidence(
                entity_id="entity-a",
                document_id="doc-1",
                name="Alpha",
                entity_type="concept",
                description="First concept",
                source_chunk_ids=["chunk-a"],
            ),
            EntityEvidence(
                entity_id="entity-b",
                document_id="doc-1",
                name="Beta",
                entity_type="mechanism",
                description="Second concept",
                source_chunk_ids=["chunk-b"],
            ),
        ],
        relations=[
            RelationEvidence(
                relation_id="rel-ab",
                document_id="doc-1",
                source_entity_id="entity-a",
                target_entity_id="entity-b",
                source_entity_name="Alpha",
                target_entity_name="Beta",
                description="Alpha depends on Beta",
                keywords=["depends", "beta"],
                weight=0.8,
                source_chunk_ids=["chunk-rel"],
            )
        ],
    )


def _cross_document_batches() -> list[GraphEvidenceBatch]:
    return [
        GraphEvidenceBatch(
            document_id="doc-a",
            entities=[
                EntityEvidence(
                    entity_id="doc-a-alpha",
                    document_id="doc-a",
                    name="Alpha",
                    entity_type="concept",
                    description="Entry concept.",
                    source_chunk_ids=["chunk-alpha"],
                ),
                EntityEvidence(
                    entity_id="doc-a-minirag",
                    document_id="doc-a",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval.",
                    source_chunk_ids=["chunk-minirag-a"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc-a-alpha-minirag",
                    document_id="doc-a",
                    source_entity_id="doc-a-alpha",
                    target_entity_id="doc-a-minirag",
                    source_entity_name="Alpha",
                    target_entity_name="MiniRAG",
                    description="Alpha introduces MiniRAG.",
                    keywords=["entry"],
                    weight=1.0,
                    source_chunk_ids=["chunk-rel-a"],
                )
            ],
        ),
        GraphEvidenceBatch(
            document_id="doc-b",
            entities=[
                EntityEvidence(
                    entity_id="doc-b-minirag",
                    document_id="doc-b",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph retrieval mode.",
                    source_chunk_ids=["chunk-minirag-b"],
                ),
                EntityEvidence(
                    entity_id="doc-b-sources",
                    document_id="doc-b",
                    name="Source Chunks",
                    entity_type="evidence",
                    description="Recovered source chunks.",
                    source_chunk_ids=["chunk-sources"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc-b-minirag-sources",
                    document_id="doc-b",
                    source_entity_id="doc-b-minirag",
                    target_entity_id="doc-b-sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Source Chunks",
                    description="MiniRAG recovers source chunks.",
                    keywords=["recovery"],
                    weight=1.0,
                    source_chunk_ids=["chunk-rel-b"],
                )
            ],
        ),
    ]


def _write_cross_document_batches(store: SqliteGraphEvidenceStore, db_path: Path) -> None:
    for batch in _cross_document_batches():
        _write_batch(store, db_path, batch)


def _write_json_batches(evidence_dir: Path, batches: list[GraphEvidenceBatch]) -> None:
    store = LocalJsonGraphEvidenceStore(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for batch in batches:
        store.upsert_document_evidence(batch)


def _build_sqlite_and_json_indexes(
    tmp_path: Path,
    batches: list[GraphEvidenceBatch],
    *,
    canonicalize_cross_document: bool = False,
) -> tuple[SqliteGraphEvidenceIndex, LocalJsonGraphEvidenceIndex]:
    db_path = tmp_path / "artifacts.sqlite3"
    json_dir = tmp_path / "json"
    sqlite_store = SqliteGraphEvidenceStore(db_path)
    for batch in batches:
        _write_batch(sqlite_store, db_path, batch)
    _write_json_batches(json_dir, batches)
    return (
        SqliteGraphEvidenceIndex(
            db_path,
            canonicalize_cross_document=canonicalize_cross_document,
        ),
        LocalJsonGraphEvidenceIndex(
            json_dir,
            reload_on_query=True,
            canonicalize_cross_document=canonicalize_cross_document,
        ),
    )


def test_query_entities_matches_name_type_and_description(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    _write_batch(store, db_path, _fixture_batch())
    index = SqliteGraphEvidenceIndex(db_path)

    name_candidates = index.query_entities(["Alpha"], top_k=5)
    type_candidates = index.query_entities(["mechanism"], top_k=5)
    description_candidates = index.query_entities(["second concept"], top_k=5)

    assert [candidate.entity.entity_id for candidate in name_candidates] == ["entity-a"]
    assert name_candidates[0].matched_terms == ["alpha"]
    assert [candidate.entity.entity_id for candidate in type_candidates] == ["entity-b"]
    assert description_candidates[0].entity.entity_id == "entity-b"
    assert description_candidates[0].matched_terms == ["second concept"]


def test_query_relationships_matches_keywords_and_answer_type_terms(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    _write_batch(store, db_path, _fixture_batch())
    index = SqliteGraphEvidenceIndex(db_path)

    candidates = index.query_relationships(
        query="unrelated beta",
        answer_type_keywords=["depends"],
        top_k=5,
    )

    assert [candidate.relation.relation_id for candidate in candidates] == ["rel-ab"]
    assert candidates[0].matched_terms == ["beta", "depends"]


def test_sqlite_index_explicit_build_allowlist_is_conservative(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    _write_batch(store, db_path, _fixture_batch())
    index = SqliteGraphEvidenceIndex(db_path)

    assert index.query_entities(["Alpha"], top_k=5, allowed_build_ids=[]) == []
    assert index.query_entities(["Alpha"], top_k=5, allowed_build_ids=["build-1"]) == []
    assert (
        index.query_relationships(
            "unrelated beta",
            ["depends"],
            top_k=5,
            allowed_build_ids=[],
        )
        == []
    )
    assert (
        index.query_relationships(
            "unrelated beta",
            ["depends"],
            top_k=5,
            allowed_build_ids=["build-1"],
        )
        == []
    )


def test_same_index_instance_refreshes_after_active_build_switch(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    index = SqliteGraphEvidenceIndex(db_path)

    _write_batch(store, db_path, _fixture_batch())

    initial_candidates = index.query_entities(["Alpha"], top_k=5)

    assert [candidate.entity.entity_id for candidate in initial_candidates] == [
        "entity-a"
    ]

    _write_batch(
        store,
        db_path,
        GraphEvidenceBatch(
            document_id="doc-1",
            entities=[
                EntityEvidence(
                    entity_id="entity-c",
                    document_id="doc-1",
                    name="Gamma",
                    entity_type="concept",
                    description="Replacement concept",
                    source_chunk_ids=["chunk-c"],
                )
            ],
            relations=[],
        ),
    )

    refreshed_candidates = index.query_entities(["Gamma"], top_k=5)
    stale_candidates = index.query_entities(["Alpha"], top_k=5)

    assert [candidate.entity.entity_id for candidate in refreshed_candidates] == [
        "entity-c"
    ]
    assert stale_candidates == []


def test_pending_build_is_not_visible_to_queries(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    _write_batch(store, db_path, _fixture_batch())
    _write_pending_batch(
        store,
        GraphEvidenceBatch(
            document_id="doc-1",
            entities=[
                EntityEvidence(
                    entity_id="entity-c",
                    document_id="doc-1",
                    name="Gamma",
                    entity_type="concept",
                    description="Pending concept",
                    source_chunk_ids=["chunk-c"],
                )
            ],
            relations=[],
        ),
    )
    index = SqliteGraphEvidenceIndex(db_path)

    active_candidates = index.query_entities(["Alpha"], top_k=5)
    pending_candidates = index.query_entities(["Gamma"], top_k=5)

    assert [candidate.entity.entity_id for candidate in active_candidates] == [
        "entity-a"
    ]
    assert pending_candidates == []


def test_expand_paths_preserves_source_chunk_union_and_metadata(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    _write_batch(store, db_path, _fixture_batch())
    index = SqliteGraphEvidenceIndex(db_path)

    paths = index.expand_paths(
        seed_entity_ids=["entity-a"],
        seed_relation_ids=["rel-ab"],
        max_hops=1,
    )

    assert paths
    assert paths[0].document_id == "doc-1"
    assert paths[0].candidate_group_id == "entity-a"
    assert paths[0].candidate_rank == 0
    assert paths[0].entity_ids == ["entity-a", "entity-b"]
    assert paths[0].relation_ids == ["rel-ab"]
    assert paths[0].source_chunk_ids == ["chunk-a", "chunk-b", "chunk-rel"]
    assert paths[0].metadata["hop_count"] == 1


def test_cross_document_canonicalization_merges_duplicate_named_entities(tmp_path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    store = SqliteGraphEvidenceStore(db_path)
    for document_id, entity_id, chunk_id in [
        ("doc-a", "entity-a", "chunk-a"),
        ("doc-b", "entity-b", "chunk-b"),
    ]:
        _write_batch(
            store,
            db_path,
            GraphEvidenceBatch(
                document_id=document_id,
                entities=[
                    EntityEvidence(
                        entity_id=entity_id,
                        document_id=document_id,
                        name="Shared Entity",
                        entity_type="concept",
                        description="Same name",
                        source_chunk_ids=[chunk_id],
                    )
                ],
                relations=[],
            ),
        )

    index = SqliteGraphEvidenceIndex(db_path, canonicalize_cross_document=True)
    candidates = index.query_entities(["Shared Entity"], top_k=5)

    assert candidates
    assert candidates[0].entity.name == "Shared Entity"
    assert candidates[0].entity.document_id == "__canonical__"
    assert candidates[0].entity.source_chunk_ids == ["chunk-a", "chunk-b"]


def test_sqlite_and_json_entity_lookup_parity(tmp_path) -> None:
    sqlite_index, json_index = _build_sqlite_and_json_indexes(
        tmp_path,
        [_fixture_batch()],
    )

    sqlite_candidates = sqlite_index.query_entities(
        [" Alpha ", "mechanism", "second concept"],
        top_k=5,
    )
    json_candidates = json_index.query_entities(
        [" Alpha ", "mechanism", "second concept"],
        top_k=5,
    )

    assert [
        (
            candidate.entity.entity_id,
            candidate.matched_terms,
            candidate.score,
        )
        for candidate in sqlite_candidates
    ] == [
        (
            candidate.entity.entity_id,
            candidate.matched_terms,
            candidate.score,
        )
        for candidate in json_candidates
    ]


def test_sqlite_and_json_relationship_lookup_parity(tmp_path) -> None:
    sqlite_index, json_index = _build_sqlite_and_json_indexes(
        tmp_path,
        [_fixture_batch()],
    )

    sqlite_candidates = sqlite_index.query_relationships(
        query="Alpha beta unrelated",
        answer_type_keywords=["depends", "beta"],
        top_k=5,
    )
    json_candidates = json_index.query_relationships(
        query="Alpha beta unrelated",
        answer_type_keywords=["depends", "beta"],
        top_k=5,
    )

    assert [
        (
            candidate.relation.relation_id,
            candidate.matched_terms,
            candidate.score,
        )
        for candidate in sqlite_candidates
    ] == [
        (
            candidate.relation.relation_id,
            candidate.matched_terms,
            candidate.score,
        )
        for candidate in json_candidates
    ]


def test_sqlite_and_json_path_expander_parity(tmp_path) -> None:
    sqlite_index, json_index = _build_sqlite_and_json_indexes(
        tmp_path,
        _cross_document_batches(),
        canonicalize_cross_document=True,
    )

    sqlite_paths = sqlite_index.expand_paths(
        seed_entity_ids=[sqlite_index.query_entities(["Alpha"], top_k=1)[0].entity.entity_id],
        seed_relation_ids=[],
        max_hops=2,
    )
    json_paths = json_index.expand_paths(
        seed_entity_ids=[json_index.query_entities(["Alpha"], top_k=1)[0].entity.entity_id],
        seed_relation_ids=[],
        max_hops=2,
    )

    assert [(path.path_id, path.source_chunk_ids) for path in sqlite_paths] == [
        (path.path_id, path.source_chunk_ids) for path in json_paths
    ]
    assert [
        (
            path.document_id,
            path.score,
            path.candidate_group_id,
            path.candidate_rank,
            path.metadata["hop_count"],
        )
        for path in sqlite_paths
    ] == [
        (
            path.document_id,
            path.score,
            path.candidate_group_id,
            path.candidate_rank,
            path.metadata["hop_count"],
        )
        for path in json_paths
    ]


def test_sqlite_and_json_path_expander_parity_for_overlapping_seeds(tmp_path) -> None:
    sqlite_index, json_index = _build_sqlite_and_json_indexes(
        tmp_path,
        [_fixture_batch()],
    )

    sqlite_paths = sqlite_index.expand_paths(
        seed_entity_ids=["entity-a", "entity-b"],
        seed_relation_ids=["rel-ab"],
        max_hops=1,
    )
    json_paths = json_index.expand_paths(
        seed_entity_ids=["entity-a", "entity-b"],
        seed_relation_ids=["rel-ab"],
        max_hops=1,
    )

    assert [
        (
            path.path_id,
            path.document_id,
            path.score,
            path.candidate_group_id,
            path.candidate_rank,
            path.metadata["hop_count"],
        )
        for path in sqlite_paths
    ] == [
        (
            path.path_id,
            path.document_id,
            path.score,
            path.candidate_group_id,
            path.candidate_rank,
            path.metadata["hop_count"],
        )
        for path in json_paths
    ]
    assert [path.candidate_group_id for path in sqlite_paths] == ["entity-a"]
