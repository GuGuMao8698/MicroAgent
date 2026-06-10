from __future__ import annotations

import threading

import pytest

from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    GraphCandidateInfinityConfig,
    InfinityGraphCandidateIndex,
)


def test_graph_candidate_config_defaults_match_spec() -> None:
    config = GraphCandidateInfinityConfig()

    assert config.entity_table == "graph_entities"
    assert config.relationship_table == "graph_relationships"
    assert config.graph_initial_recall_n == 1024
    assert config.text_weight == 0.05
    assert config.dense_weight == 0.95
    assert config.minimum_should_match == 0.3
    assert config.dense_similarity_threshold == 0.2
    assert config.fusion_normalize == "atan"


def test_graph_candidate_config_is_frozen() -> None:
    config = GraphCandidateInfinityConfig()

    with pytest.raises(AttributeError):
        config.entity_table = "other"  # type: ignore[misc]


def test_graph_candidate_config_accepts_custom_values() -> None:
    config = GraphCandidateInfinityConfig(
        entity_table="my_entities",
        relationship_table="my_relationships",
        graph_initial_recall_n=512,
        text_weight=0.1,
        dense_weight=0.9,
    )

    assert config.entity_table == "my_entities"
    assert config.relationship_table == "my_relationships"
    assert config.graph_initial_recall_n == 512
    assert config.text_weight == 0.1
    assert config.dense_weight == 0.9


def test_relationship_output_fields_preserve_candidate_contract() -> None:
    from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
        RELATIONSHIP_OUTPUT_FIELDS,
    )

    assert "candidate_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "canonical_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "document_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "projection_build_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_entity_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "target_entity_id" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_entity_name" in RELATIONSHIP_OUTPUT_FIELDS
    assert "target_entity_name" in RELATIONSHIP_OUTPUT_FIELDS
    assert "relationship_description_tks" in RELATIONSHIP_OUTPUT_FIELDS
    assert "keywords" in RELATIONSHIP_OUTPUT_FIELDS
    assert "weight" in RELATIONSHIP_OUTPUT_FIELDS
    assert "source_chunk_ids" in RELATIONSHIP_OUTPUT_FIELDS
    assert "metadata" in RELATIONSHIP_OUTPUT_FIELDS
    assert "_score" in RELATIONSHIP_OUTPUT_FIELDS


def test_relationship_candidate_mapper_preserves_relation_fields() -> None:
    from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
        GraphCandidateInfinityConfig,
        _relationship_candidate_from_row,
    )

    candidate = _relationship_candidate_from_row(
        {
            "candidate_id": "relation_python_django_raw",
            "canonical_id": "relation_python_django",
            "document_id": "graph_doc",
            "source_entity_id": "entity_python",
            "target_entity_id": "entity_django",
            "source_entity_name": "Python",
            "target_entity_name": "Django",
            "relationship_description_tks": "Python uses Django",
            "keywords": '["framework"]',
            "weight": 1.0,
            "source_chunk_ids": '["chunk_python"]',
            "metadata": '{"canonical_id": "relation_python_django"}',
            "_score": 0.75,
        },
        GraphCandidateInfinityConfig(),
    )

    relation = candidate.relation
    assert relation.relation_id == "relation_python_django"
    assert relation.document_id == "graph_doc"
    assert relation.source_entity_id == "entity_python"
    assert relation.target_entity_id == "entity_django"
    assert relation.source_entity_name == "Python"
    assert relation.target_entity_name == "Django"
    assert relation.description == "Python uses Django"
    assert relation.keywords == ["framework"]
    assert relation.weight == 1.0
    assert relation.source_chunk_ids == ["chunk_python"]
    assert candidate.score == 0.75
    assert candidate.metadata["candidate_id"] == "relation_python_django_raw"
    assert candidate.metadata["candidate_kind"] == "relationship"


class _FakePolars:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def is_empty(self) -> bool:
        return not self._rows

    def iter_rows(self, *, named: bool = False):
        assert named is True
        return iter(self._rows)


class _FakeColumnsDataFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def iter_rows(self, *, named: bool = False):
        assert named is True
        return iter(self._rows)


class _FakeQuery:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self._output_fields: list[str] | None = None

    def match_text(self, **_: object) -> _FakeQuery:
        return self

    def match_dense(self, **_: object) -> _FakeQuery:
        return self

    def fusion(self, *_: object, **__: object) -> _FakeQuery:
        return self

    def filter(self, expression: str) -> _FakeQuery:
        if " IN " not in expression:
            raise AssertionError(f"unexpected filter expression: {expression}")
        raw_values = expression.split("(", 1)[1].rsplit(")", 1)[0]
        allowed = {
            value.strip().strip("'")
            for value in raw_values.split(",")
            if value.strip()
        }
        self._rows = [
            row
            for row in self._rows
            if str(row.get("projection_build_id")) in allowed
        ]
        return self

    def output(self, fields: list[str]) -> _FakeQuery:
        self._output_fields = fields
        return self

    def to_pl(self) -> tuple[_FakePolars, dict[str, object]]:
        rows = self._rows
        if self._output_fields is not None:
            rows = [
                {field: row.get(field) for field in self._output_fields}
                for row in self._rows
            ]
        return _FakePolars(rows), {}


class _FakeTable:
    def __init__(
        self,
        *,
        columns: list[str] | None = None,
        show_columns_result: object | None = None,
    ) -> None:
        self.rows: list[dict[str, object]] = []
        self.columns = list(columns or [])
        self.show_columns_result = show_columns_result

    def insert(self, rows: list[dict[str, object]]) -> None:
        self.rows.extend(rows)
        for row in rows:
            for key in row:
                if key not in self.columns:
                    self.columns.append(key)

    def delete(self, expression: str) -> None:
        self.rows = [
            row for row in self.rows if not _matches_expression(row, expression)
        ]

    def match_text(self, **_: object) -> _FakeQuery:
        return _FakeQuery(list(self.rows))

    def show_columns(self) -> list[dict[str, object]]:
        if self.show_columns_result is not None:
            return self.show_columns_result
        return [{"name": column} for column in self.columns]

    def create_index(self, *_: object, **__: object) -> None:
        return None


class _FakeDb:
    def __init__(self, tables: dict[str, _FakeTable] | None = None) -> None:
        self.tables = tables or {
            "graph_entities": _FakeTable(),
            "graph_relationships": _FakeTable(),
        }

    def get_table(self, name: str) -> _FakeTable:
        return self.tables[name]

    def create_table(
        self,
        name: str,
        columns: dict[str, dict[str, object]],
        _conflict_type: object,
    ) -> None:
        if name not in self.tables:
            self.tables[name] = _FakeTable(columns=list(columns))


class _FakeEmbedder:
    signature = {"dimensions": 3}

    def embed_query(self, _: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _NonReentrantLock:
    def __init__(self) -> None:
        self._locked = False

    def __enter__(self) -> None:
        if self._locked:
            raise AssertionError("reentrant acquire")
        self._locked = True
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        self._locked = False
        return None


def _matches_expression(row: dict[str, object], expression: str) -> bool:
    if " IN " in expression:
        field, raw_values = expression.split(" IN ", 1)
        values = {
            value.strip().strip("'")
            for value in raw_values.strip()[1:-1].split(",")
            if value.strip()
        }
        return str(row.get(field.strip())) in values
    field, raw_value = expression.split("=", 1)
    return str(row.get(field.strip())) == raw_value.strip().strip("'")


def _batch(document_id: str, suffix: str) -> GraphEvidenceBatch:
    entity = EntityEvidence(
        entity_id=f"entity-{suffix}",
        document_id=document_id,
        name=f"Entity {suffix}",
        entity_type="type",
        description=f"Description {suffix}",
        source_chunk_ids=[f"chunk-{suffix}"],
    )
    relation = RelationEvidence(
        relation_id=f"relation-{suffix}",
        document_id=document_id,
        source_entity_id=entity.entity_id,
        target_entity_id=f"target-{suffix}",
        source_entity_name=entity.name,
        target_entity_name=f"Target {suffix}",
        description=f"Relation {suffix}",
        keywords=[f"keyword-{suffix}"],
        weight=1.0,
        source_chunk_ids=[f"chunk-{suffix}"],
    )
    return GraphEvidenceBatch(
        document_id=document_id,
        entities=[entity],
        relations=[relation],
    )


def _build_index() -> tuple[InfinityGraphCandidateIndex, _FakeDb]:
    index = object.__new__(InfinityGraphCandidateIndex)
    fake_db = _FakeDb()
    index._db = fake_db
    index._embedder = _FakeEmbedder()
    index._config = GraphCandidateInfinityConfig()
    index._lock = threading.RLock()
    return index, fake_db


def test_ensure_tables_rejects_legacy_schema_without_projection_build_id() -> None:
    entity_columns = [
        "candidate_id",
        "canonical_id",
        "document_id",
        "candidate_kind",
        "entity_name_kwd",
        "entity_name_tks",
        "entity_type_tks",
        "entity_description_tks",
        "embedding_text",
        "vec",
        "source_chunk_ids",
        "metadata",
    ]
    relationship_columns = [
        "candidate_id",
        "canonical_id",
        "document_id",
        "candidate_kind",
        "source_entity_id",
        "target_entity_id",
        "source_entity_name",
        "target_entity_name",
        "relationship_endpoint_kwd",
        "relationship_endpoint_tks",
        "relationship_keyword_tks",
        "relationship_description_tks",
        "embedding_text",
        "vec",
        "keywords",
        "weight",
        "source_chunk_ids",
        "metadata",
    ]
    fake_db = _FakeDb(
        tables={
            "graph_entities": _FakeTable(columns=entity_columns),
            "graph_relationships": _FakeTable(columns=relationship_columns),
        }
    )

    index = object.__new__(InfinityGraphCandidateIndex)
    index._db = fake_db
    index._embedder = _FakeEmbedder()
    index._config = GraphCandidateInfinityConfig()
    index._lock = threading.RLock()

    with pytest.raises(RuntimeError, match="projection_build_id"):
        index._ensure_tables()


def test_ensure_tables_accepts_dataframe_like_show_columns_shape() -> None:
    entity_df = _FakeColumnsDataFrame(
        [{"column_name": column} for column in ["projection_build_id", "candidate_id"]]
    )
    relationship_df = _FakeColumnsDataFrame(
        [{"column_name": column} for column in ["projection_build_id", "candidate_id"]]
    )
    fake_db = _FakeDb(
        tables={
            "graph_entities": _FakeTable(show_columns_result=(entity_df, {"extra": 1})),
            "graph_relationships": _FakeTable(show_columns_result=relationship_df),
        }
    )

    index = object.__new__(InfinityGraphCandidateIndex)
    index._db = fake_db
    index._embedder = _FakeEmbedder()
    index._config = GraphCandidateInfinityConfig()
    index._lock = threading.RLock()

    index._ensure_tables()


def test_ensure_tables_accepts_top_level_dict_show_columns_shape() -> None:
    fake_db = _FakeDb(
        tables={
            "graph_entities": _FakeTable(
                show_columns_result={"column_name": "projection_build_id"}
            ),
            "graph_relationships": _FakeTable(
                show_columns_result={"name": "projection_build_id"}
            ),
        }
    )

    index = object.__new__(InfinityGraphCandidateIndex)
    index._db = fake_db
    index._embedder = _FakeEmbedder()
    index._config = GraphCandidateInfinityConfig()
    index._lock = threading.RLock()

    index._ensure_tables()


def test_upsert_build_evidence_isolated_by_build_id() -> None:
    index, fake_db = _build_index()

    index.upsert_build_evidence("build-old", _batch("doc-1", "old"))
    index.upsert_build_evidence("build-new", _batch("doc-1", "new"))

    entity_rows = fake_db.get_table("graph_entities").rows
    relationship_rows = fake_db.get_table("graph_relationships").rows
    assert {row["projection_build_id"] for row in entity_rows} == {
        "build-old",
        "build-new",
    }
    assert {row["projection_build_id"] for row in relationship_rows} == {
        "build-old",
        "build-new",
    }


def test_delete_build_removes_only_target_build_rows() -> None:
    index, fake_db = _build_index()
    index.upsert_build_evidence("build-old", _batch("doc-1", "old"))
    index.upsert_build_evidence("build-new", _batch("doc-1", "new"))

    index.delete_build("build-old")

    assert {
        row["projection_build_id"] for row in fake_db.get_table("graph_entities").rows
    } == {"build-new"}
    assert {
        row["projection_build_id"]
        for row in fake_db.get_table("graph_relationships").rows
    } == {"build-new"}


def test_upsert_build_evidence_does_not_require_reentrant_lock() -> None:
    index, fake_db = _build_index()
    index._lock = _NonReentrantLock()

    index.upsert_build_evidence("build-1", _batch("doc-1", "one"))
    index.upsert_build_evidence("build-1", _batch("doc-1", "two"))

    entity_rows = fake_db.get_table("graph_entities").rows
    relationship_rows = fake_db.get_table("graph_relationships").rows
    assert {row["projection_build_id"] for row in entity_rows} == {"build-1"}
    assert {row["projection_build_id"] for row in relationship_rows} == {"build-1"}
    assert {row["candidate_id"] for row in entity_rows} == {"build-1:entity-two"}


def test_query_entities_can_filter_inactive_build_rows() -> None:
    index, fake_db = _build_index()
    fake_db.get_table("graph_entities").rows = [
        {
            "candidate_id": "build-old:entity-1",
            "canonical_id": "entity-1",
            "document_id": "doc-1",
            "entity_name_kwd": "Python old",
            "source_chunk_ids": '["chunk-old"]',
            "metadata": '{"raw_candidate_id":"entity-1","projection_build_id":"build-old"}',
            "projection_build_id": "build-old",
            "_score": 0.9,
        },
        {
            "candidate_id": "build-new:entity-1",
            "canonical_id": "entity-1",
            "document_id": "doc-1",
            "entity_name_kwd": "Python new",
            "source_chunk_ids": '["chunk-new"]',
            "metadata": '{"raw_candidate_id":"entity-1","projection_build_id":"build-new"}',
            "projection_build_id": "build-new",
            "_score": 0.8,
        },
    ]

    filtered = index.query_entities(["python"], top_k=5, allowed_build_ids=["build-new"])
    unfiltered = index.query_entities(["python"], top_k=5)

    assert [candidate.metadata["projection_build_id"] for candidate in filtered] == [
        "build-new"
    ]
    assert [candidate.metadata["raw_candidate_id"] for candidate in filtered] == [
        "entity-1"
    ]
    assert unfiltered[0].metadata["projection_build_id"] == "build-old"


def test_query_entities_with_empty_allowlist_returns_no_candidates() -> None:
    index, fake_db = _build_index()
    fake_db.get_table("graph_entities").rows = [
        {
            "candidate_id": "build-old:entity-1",
            "canonical_id": "entity-1",
            "document_id": "doc-1",
            "entity_name_kwd": "Python old",
            "source_chunk_ids": '["chunk-old"]',
            "metadata": '{"raw_candidate_id":"entity-1","projection_build_id":"build-old"}',
            "projection_build_id": "build-old",
            "_score": 0.9,
        }
    ]

    assert index.query_entities(["python"], top_k=5, allowed_build_ids=[]) == []


def test_query_relationships_can_filter_inactive_build_rows() -> None:
    index, fake_db = _build_index()
    fake_db.get_table("graph_relationships").rows = [
        {
            "candidate_id": "build-old:relation-1",
            "canonical_id": "relation-1",
            "document_id": "doc-1",
            "projection_build_id": "build-old",
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "source_entity_name": "Python",
            "target_entity_name": "Django",
            "relationship_description_tks": "old relation",
            "keywords": '["framework"]',
            "weight": 1.0,
            "source_chunk_ids": '["chunk-old"]',
            "metadata": '{"raw_candidate_id":"relation-1","projection_build_id":"build-old"}',
            "_score": 0.9,
        },
        {
            "candidate_id": "build-new:relation-1",
            "canonical_id": "relation-1",
            "document_id": "doc-1",
            "projection_build_id": "build-new",
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "source_entity_name": "Python",
            "target_entity_name": "Django",
            "relationship_description_tks": "new relation",
            "keywords": '["framework"]',
            "weight": 1.0,
            "source_chunk_ids": '["chunk-new"]',
            "metadata": '{"raw_candidate_id":"relation-1","projection_build_id":"build-new"}',
            "_score": 0.8,
        },
    ]

    filtered = index.query_relationships(
        "python django",
        ["framework"],
        top_k=5,
        allowed_build_ids=["build-new"],
    )
    unfiltered = index.query_relationships("python django", ["framework"], top_k=5)

    assert [candidate.metadata["projection_build_id"] for candidate in filtered] == [
        "build-new"
    ]
    assert [candidate.metadata["raw_candidate_id"] for candidate in filtered] == [
        "relation-1"
    ]
    assert unfiltered[0].metadata["projection_build_id"] == "build-old"


def test_query_relationships_with_empty_allowlist_returns_no_candidates() -> None:
    index, fake_db = _build_index()
    fake_db.get_table("graph_relationships").rows = [
        {
            "candidate_id": "build-old:relation-1",
            "canonical_id": "relation-1",
            "document_id": "doc-1",
            "projection_build_id": "build-old",
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "source_entity_name": "Python",
            "target_entity_name": "Django",
            "relationship_description_tks": "old relation",
            "keywords": '["framework"]',
            "weight": 1.0,
            "source_chunk_ids": '["chunk-old"]',
            "metadata": '{"raw_candidate_id":"relation-1","projection_build_id":"build-old"}',
            "_score": 0.9,
        }
    ]

    assert (
        index.query_relationships(
            "python django",
            ["framework"],
            top_k=5,
            allowed_build_ids=[],
        )
        == []
    )
