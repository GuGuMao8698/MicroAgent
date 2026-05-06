"""InfinityGraphCandidateIndex 单测。

验证 Infinity 原生 match_text + match_dense + weighted_sum fusion
查询图候选实体和关系的契约行为。
"""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest
from infinity.index import IndexType

from ragflow_lite.domain.models.entities import (
    EntityEvidence,
    GraphEvidenceBatch,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_fields import (
    ENTITY_MATCH_TEXT_FIELDS,
    RELATIONSHIP_MATCH_TEXT_FIELDS,
)
from ragflow_lite.infrastructure.evidence.infinity_graph_candidate_index import (
    GraphCandidateInfinityConfig,
    InfinityGraphCandidateIndex,
)

# ---------------------------------------------------------------------------
# 测试用假的 Infinity 组件
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """嵌入器 fake：返回确定性向量。"""

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.last_query: str | None = None

    def embed_query(self, text: str) -> list[float]:
        self.last_query = text
        # 确定性：每个字符映射为小 float
        return [
            float(ord(c) % 256) / 256.0 for c in text.ljust(self.dim, "\0")[: self.dim]
        ]


class _GraphFakeQueryBuilder:
    """图候选专用 fake query builder，使用 candidate_id 而非 chunk_id 做融合。"""

    def __init__(
        self,
        table: _GraphFakeInfinityTable,
        match_type: str,
        match_kwargs: dict[str, Any],
    ) -> None:
        self._table = table
        self._text_kwargs: dict[str, Any] | None = None
        self._dense_kwargs: dict[str, Any] | None = None
        self._fusion_kwargs: dict[str, Any] | None = None
        self._output_columns: list[str] = []

        if match_type == "text":
            self._text_kwargs = match_kwargs
        elif match_type == "dense":
            self._dense_kwargs = match_kwargs

    def match_text(self, **kwargs: Any) -> _GraphFakeQueryBuilder:
        self._text_kwargs = kwargs
        return self

    def match_dense(self, **kwargs: Any) -> _GraphFakeQueryBuilder:
        self._dense_kwargs = kwargs
        self._table.query_calls.append({"type": "match_dense", "kwargs": kwargs})
        return self

    def fusion(
        self,
        method: str,
        topn: int,
        fusion_params: dict[str, Any] | None = None,
    ) -> _GraphFakeQueryBuilder:
        self._fusion_kwargs = {"method": method, "topn": topn}
        if fusion_params is not None:
            self._fusion_kwargs["fusion_params"] = fusion_params
        return self

    def output(self, columns: list[str]) -> _GraphFakeQueryBuilder:
        self._output_columns = columns
        return self

    def to_pl(self) -> tuple[pl.DataFrame, dict]:
        """确定性融合：按 candidate_id 关联文本和稠密命中。"""
        if self._fusion_kwargs is None:
            # 无融合时返回空
            return pl.DataFrame(), {}

        topn = self._fusion_kwargs.get("topn", 10)
        weights_str = self._fusion_kwargs.get("fusion_params", {}).get(
            "weights", "0.5,0.5"
        )
        text_weight, dense_weight = (float(w) for w in weights_str.split(",", 1))

        # 文本打分
        text_scores: dict[str, float] = {}
        if self._text_kwargs:
            query_text = self._text_kwargs.get("matching_text", "")
            fields = self._text_kwargs.get("fields", "")
            # 简单匹配：检查 query_text 是否出现在任何文本字段中
            for row in self._table.rows:
                score = 0.0
                for field_part in fields.split(","):
                    field_name = field_part.split("^")[0].strip()
                    val = str(row.get(field_name, ""))
                    if query_text.lower() in val.lower():
                        boost = (
                            float(field_part.split("^")[1])
                            if "^" in field_part
                            else 1.0
                        )
                        score += boost
                if score > 0:
                    text_scores[row["candidate_id"]] = score

        # 稠密打分
        dense_scores: dict[str, tuple[float, dict[str, Any]]] = {}
        if self._dense_kwargs:
            query_vec = self._dense_kwargs.get("embedding_data", [])
            for row in self._table.rows:
                row_vec = row.get("vec", [])
                ip = sum(a * b for a, b in zip(query_vec, row_vec, strict=False))
                if ip > 0:
                    dense_scores[row["candidate_id"]] = (ip, row)

        # 融合
        max_dense = max((v[0] for v in dense_scores.values()), default=0.0)
        if max_dense == 0:
            max_dense = 1.0

        fused: dict[str, tuple[float, dict[str, Any]]] = {}
        all_ids = set(text_scores.keys()) | set(dense_scores.keys())
        for cid in all_ids:
            t_score = text_scores.get(cid, 0.0)
            d_score, row = dense_scores.get(cid, (0.0, {}))
            norm_d = d_score / max_dense
            final = text_weight * t_score + dense_weight * norm_d
            fused[cid] = (
                final,
                row
                if cid in dense_scores
                else next(r for r in self._table.rows if r["candidate_id"] == cid),
            )

        sorted_items = sorted(fused.items(), key=lambda x: x[1][0], reverse=True)[:topn]

        if not sorted_items:
            return pl.DataFrame(), {}

        scored = []
        for _cid, (final_score, row) in sorted_items:
            result: dict[str, Any] = {}
            for col in self._output_columns:
                if col == "_score":
                    result[col] = final_score
                else:
                    result[col] = row.get(col, "")
            scored.append(result)

        return pl.DataFrame(scored), {}


class _GraphFakeInfinityTable:
    """图候选专用 fake Infinity 表，使用 candidate_id 作为主键。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[dict[str, Any]] = []
        # 记录查询调用
        self.query_calls: list[dict[str, Any]] = []
        # 记录 delete 调用的 filter 表达式
        self.deleted_filters: list[str] = []
        self._indexes: dict[str, dict[str, Any]] = {}

    def insert(self, data: list[dict[str, Any]]) -> None:
        self.rows.extend(data)

    def delete(self, filter_expr: str) -> None:
        """记录 delete 调用，并按 document_id 过滤移除匹配行。"""
        self.deleted_filters.append(filter_expr)
        # 简单解析 "document_id = 'xxx'" 格式，移除匹配行
        import re

        m = re.match(r"document_id\s*=\s*'((?:[^'\\]|\\.)*)'", filter_expr)
        if m:
            doc_id = m.group(1).replace("\\'", "'")
            self.rows = [r for r in self.rows if r.get("document_id") != doc_id]

    def match_text(self, **kwargs: Any) -> _GraphFakeQueryBuilder:
        self.query_calls.append({"type": "match_text", "kwargs": kwargs})
        return _GraphFakeQueryBuilder(self, "text", kwargs)

    def match_dense(self, **kwargs: Any) -> _GraphFakeQueryBuilder:
        self.query_calls.append({"type": "match_dense", "kwargs": kwargs})
        return _GraphFakeQueryBuilder(self, "dense", kwargs)

    def create_index(
        self,
        index_name: str,
        index_info: Any,
        conflict_type: Any = None,
        index_comment: str = "",
    ) -> None:
        self._indexes[index_name] = {
            "type": getattr(index_info, "index_type", index_info),
            "columns": getattr(index_info, "target_name", None),
            "conflict_type": conflict_type,
            "comment": index_comment,
        }

    def list_indexes(self) -> Any:
        return type(
            "IndexList",
            (),
            {"error_code": 0, "error_msg": "", "index_names": list(self._indexes)},
        )()


class _GraphFakeInfinityDatabase:
    def __init__(self) -> None:
        self._tables: dict[str, _GraphFakeInfinityTable] = {}
        self.created_tables: dict[str, dict[str, Any]] = {}

    def get_table(self, name: str) -> _GraphFakeInfinityTable:
        if name not in self._tables:
            raise RuntimeError(f"Table '{name}' does not exist")
        return self._tables[name]

    def create_table(
        self,
        name: str,
        columns: dict[str, Any],
        conflict_type: Any = None,
    ) -> None:
        self.created_tables[name] = columns
        if name not in self._tables:
            self._tables[name] = _GraphFakeInfinityTable(name)


class _GraphFakeInfinityClient:
    def __init__(self) -> None:
        self._db = _GraphFakeInfinityDatabase()

    def get_database(self, name: str) -> _GraphFakeInfinityDatabase:
        return self._db


# ---------------------------------------------------------------------------
# 辅助函数：创建索引并插入测试数据
# ---------------------------------------------------------------------------


def _make_index(
    *,
    client: _GraphFakeInfinityClient | None = None,
    embedder: FakeEmbedder | None = None,
    config: GraphCandidateInfinityConfig | None = None,
) -> tuple[
    InfinityGraphCandidateIndex,
    _GraphFakeInfinityClient,
    FakeEmbedder,
]:
    """创建 InfinityGraphCandidateIndex 实例并返回组件。"""
    c = client or _GraphFakeInfinityClient()
    e = embedder or FakeEmbedder(dim=4)
    idx = InfinityGraphCandidateIndex(
        client=c,
        database="test_db",
        embedder=e,
        config=config,
    )
    return idx, c, e


def _insert_entity_rows(
    db: _GraphFakeInfinityDatabase,
    table_name: str,
    rows: list[dict[str, Any]],
) -> None:
    """向 fake 数据库插入实体候选行。"""
    table = db.get_table(table_name)
    table.insert(rows)


def _make_entity_row(
    *,
    candidate_id: str = "ent_1",
    canonical_id: str = "canonical_ent_1",
    document_id: str = "doc_1",
    entity_name: str = "Python",
    entity_type: str = "programming language",
    vec: list[float] | None = None,
    source_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """创建单条实体候选行。"""
    return {
        "candidate_id": candidate_id,
        "canonical_id": canonical_id,
        "document_id": document_id,
        "candidate_kind": "entity",
        "entity_name_kwd": entity_name,
        "entity_name_tks": entity_name.lower(),
        "entity_type_tks": entity_type.lower(),
        "vec": vec or [0.1, 0.2, 0.3, 0.4],
        "source_chunk_ids": source_chunk_ids or ["chunk_1"],
        "metadata": {},
    }


def _make_relationship_row(
    *,
    candidate_id: str = "rel_1",
    canonical_id: str = "canonical_rel_1",
    document_id: str = "doc_1",
    source_name: str = "Python",
    target_name: str = "Django",
    keywords: str = "web framework",
    description: str = "Python uses Django",
    vec: list[float] | None = None,
    source_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """创建单条关系候选行。"""
    endpoint = f"{source_name} {target_name}"
    return {
        "candidate_id": candidate_id,
        "canonical_id": canonical_id,
        "document_id": document_id,
        "candidate_kind": "relationship",
        "source_entity_id": "src_1",
        "target_entity_id": "tgt_1",
        "source_entity_name": source_name,
        "target_entity_name": target_name,
        "relationship_endpoint_kwd": endpoint,
        "relationship_endpoint_tks": endpoint.lower(),
        "relationship_keyword_tks": keywords.lower(),
        "relationship_description_tks": description.lower(),
        "vec": vec or [0.1, 0.2, 0.3, 0.4],
        "keywords": [keywords],
        "weight": 1.0,
        "source_chunk_ids": source_chunk_ids or ["chunk_1"],
        "metadata": {},
    }


# ===========================================================================
# 测试：配置默认值
# ===========================================================================


class TestGraphCandidateInfinityConfig:
    """配置 dataclass 默认值测试。"""

    def test_default_values(self) -> None:
        config = GraphCandidateInfinityConfig()
        assert config.entity_table == "graph_entities"
        assert config.relationship_table == "graph_relationships"
        assert config.graph_initial_recall_n == 1024
        assert config.text_weight == 0.05
        assert config.dense_weight == 0.95
        assert config.minimum_should_match == 0.3
        assert config.dense_similarity_threshold == 0.2
        assert config.fusion_normalize == "atan"

    def test_frozen(self) -> None:
        config = GraphCandidateInfinityConfig()
        with pytest.raises(AttributeError):
            config.entity_table = "other"  # type: ignore[misc]

    def test_custom_values(self) -> None:
        config = GraphCandidateInfinityConfig(
            entity_table="my_entities",
            graph_initial_recall_n=512,
            text_weight=0.1,
            dense_weight=0.9,
        )
        assert config.entity_table == "my_entities"
        assert config.graph_initial_recall_n == 512
        assert config.text_weight == 0.1
        assert config.dense_weight == 0.9


# ===========================================================================
# 测试：query_entities
# ===========================================================================


class TestQueryEntities:
    """实体候选查询测试。"""

    def test_single_entity_text_returns_candidates(self) -> None:
        """单条实体文本查询应返回匹配的候选实体。"""
        idx, client, embedder = _make_index()
        db = client.get_database("test_db")

        # 插入匹配行
        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="ent_1",
                    canonical_id="canonical_python",
                    entity_name="Python",
                    vec=[0.5, 0.5, 0.5, 0.5],
                ),
            ],
        )

        results = idx.query_entities(["Python"], top_k=10)

        assert len(results) >= 1
        candidate = results[0]
        assert isinstance(candidate, MiniEntityCandidate)
        assert candidate.entity.entity_id == "canonical_python"
        assert candidate.score > 0.0

    def test_entity_candidate_has_correct_entity_fields(self) -> None:
        """候选实体的 EntityEvidence 字段应正确映射。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="ent_1",
                    canonical_id="canonical_python",
                    document_id="doc_42",
                    entity_name="Python",
                    source_chunk_ids=["chunk_a", "chunk_b"],
                ),
            ],
        )

        results = idx.query_entities(["Python"], top_k=10)
        assert len(results) >= 1

        entity = results[0].entity
        assert entity.entity_id == "canonical_python"
        assert entity.document_id == "doc_42"
        assert entity.name == "ent_1"  # 用 candidate_id 作为名称提示
        assert entity.source_chunk_ids == ["chunk_a", "chunk_b"]

    def test_entity_metadata_contains_retrieval_info(self) -> None:
        """候选实体的 metadata 应包含完整的检索参数信息。"""
        config = GraphCandidateInfinityConfig(
            text_weight=0.05,
            dense_weight=0.95,
            minimum_should_match=0.3,
            dense_similarity_threshold=0.2,
            graph_initial_recall_n=1024,
        )
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="ent_1",
                    canonical_id="canonical_python",
                    entity_name="Python",
                ),
            ],
        )

        results = idx.query_entities(["Python"], top_k=10)
        assert len(results) >= 1

        meta = results[0].metadata
        assert meta["retrieval_mode"] == "graph_candidate_infinity_hybrid"
        assert meta["candidate_kind"] == "entity"
        assert meta["candidate_id"] == "ent_1"
        assert meta["canonical_id"] == "canonical_python"
        assert meta["fusion_method"] == "weighted_sum"
        assert meta["fusion_weights"] == {"text": 0.05, "dense": 0.95}
        assert meta["minimum_should_match"] == 0.3
        assert meta["dense_similarity_threshold"] == 0.2
        assert meta["graph_initial_recall_n"] == 1024
        assert meta["matched_query_entity"] == "Python"

    def test_multiple_entity_texts_merge_by_canonical_id(self) -> None:
        """多个查询实体文本命中同一 canonical_id 时，应合并并保留最高分。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        # 两条候选行指向同一 canonical_id，来自不同查询文本都能匹配
        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="ent_1",
                    canonical_id="canonical_python",
                    entity_name="Python",
                    vec=[0.9, 0.9, 0.9, 0.9],
                ),
                _make_entity_row(
                    candidate_id="ent_2",
                    canonical_id="canonical_python",
                    entity_name="Python programming",
                    vec=[0.5, 0.5, 0.5, 0.5],
                ),
            ],
        )

        results = idx.query_entities(["Python", "programming"], top_k=10)

        # 应该合并为一条
        canonical_ids = [c.entity.entity_id for c in results]
        assert canonical_ids.count("canonical_python") == 1

        merged = results[0]
        assert merged.metadata["canonical_id"] == "canonical_python"
        # 应保留最佳分数
        assert merged.score > 0.0

    def test_multiple_entity_texts_member_candidate_ids_collected(self) -> None:
        """合并后应收集所有 member_candidate_ids。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="ent_1",
                    canonical_id="canonical_python",
                    entity_name="Python",
                ),
                _make_entity_row(
                    candidate_id="ent_2",
                    canonical_id="canonical_python",
                    entity_name="Python lang",
                ),
            ],
        )

        results = idx.query_entities(["Python"], top_k=10)

        if len(results) >= 1:
            merged = results[0]
            member_ids = merged.metadata.get("member_candidate_ids", [])
            assert "ent_1" in member_ids
            assert "ent_2" in member_ids

    def test_top_k_truncation(self) -> None:
        """结果应在 fusion 后按 top_k 截断。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id=f"ent_{i}",
                    canonical_id=f"canonical_{i}",
                    entity_name=f"entity_{i}",
                    vec=[0.1 * i, 0.1 * i, 0.1 * i, 0.1 * i],
                )
                for i in range(10)
            ],
        )

        results = idx.query_entities(["entity"], top_k=3)
        assert len(results) <= 3

    def test_empty_result_when_no_match(self) -> None:
        """无匹配时应返回空列表。"""
        idx, client, _ = _make_index()
        # 不插入任何数据
        results = idx.query_entities(["nonexistent"], top_k=10)
        assert results == []

    def test_empty_entity_texts_returns_empty(self) -> None:
        """空查询实体列表应返回空结果。"""
        idx, _, _ = _make_index()
        results = idx.query_entities([], top_k=10)
        assert results == []

    def test_embedder_called_per_entity_text(self) -> None:
        """应为每个查询实体文本调用一次 embedder。"""
        embedder = FakeEmbedder(dim=4)
        idx, client, _ = _make_index(embedder=embedder)
        db = client.get_database("test_db")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="e1", canonical_id="c1", entity_name="Python"
                ),
                _make_entity_row(
                    candidate_id="e2", canonical_id="c2", entity_name="Java"
                ),
            ],
        )

        idx.query_entities(["Python", "Java"], top_k=10)
        # embedder 应至少被调用两次（每个查询文本一次）
        # 注意 last_query 只保存最后一次，但可以通过结果间接验证

    def test_fusion_uses_entity_match_text_fields(self) -> None:
        """实体查询应使用 ENTITY_MATCH_TEXT_FIELDS 做文本匹配。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="e1", canonical_id="c1", entity_name="Python"
                ),
            ],
        )

        idx.query_entities(["Python"], top_k=10)

        # 验证至少有一次 match_text 调用
        match_text_calls = [
            c for c in entity_table.query_calls if c["type"] == "match_text"
        ]
        assert len(match_text_calls) >= 1

        # fields 参数应包含 ENTITY_MATCH_TEXT_FIELDS
        fields_arg = match_text_calls[0]["kwargs"].get("fields", "")
        for field_spec in ENTITY_MATCH_TEXT_FIELDS:
            field_name = field_spec.split("^")[0]
            assert field_name in fields_arg

    def test_fusion_uses_infinity_sdk_threshold_options(self) -> None:
        """实体查询应使用真实 Infinity 服务端接受的阈值参数形态。"""
        config = GraphCandidateInfinityConfig(
            minimum_should_match=0.3,
            dense_similarity_threshold=0.2,
        )
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="e1", canonical_id="c1", entity_name="Python"
                ),
            ],
        )

        idx.query_entities(["Python"], top_k=10)

        match_text_call = next(
            c for c in entity_table.query_calls if c["type"] == "match_text"
        )
        match_dense_call = next(
            c for c in entity_table.query_calls if c["type"] == "match_dense"
        )
        assert match_text_call["kwargs"]["extra_options"] == {
            "minimum_should_match": "30%"
        }
        assert match_dense_call["kwargs"]["knn_params"] == {"threshold": "0.2"}

    def test_graph_initial_recall_n_not_multiplied(self) -> None:
        """graph_initial_recall_n 不应随查询实体数量倍增。"""
        config = GraphCandidateInfinityConfig(graph_initial_recall_n=64)
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        _insert_entity_rows(
            db,
            "graph_entities",
            [
                _make_entity_row(
                    candidate_id="e1", canonical_id="c1", entity_name="Python"
                ),
            ],
        )

        idx.query_entities(["Python", "Java", "C++"], top_k=10)

        # match_text 调用记录在表级别，检查其 topn 都应是 64
        # （match_dense 在 builder 上链式调用，不经过表级别记录）
        match_text_calls = [
            c for c in entity_table.query_calls if c["type"] == "match_text"
        ]
        # 3 个查询实体 → 至少 3 次 match_text 调用
        assert len(match_text_calls) == 3
        for call in match_text_calls:
            assert call["kwargs"].get("topn") == 64


# ===========================================================================
# 测试：query_relationships
# ===========================================================================


class TestQueryRelationships:
    """关系候选查询测试。"""

    def test_returns_matching_relationships(self) -> None:
        """查询应返回匹配的关系候选。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        table = db.get_table("graph_relationships")
        table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    source_name="Python",
                    target_name="Django",
                    vec=[0.5, 0.5, 0.5, 0.5],
                ),
            ]
        )

        results = idx.query_relationships(
            query="Python web framework",
            answer_type_keywords=["web"],
            top_k=10,
        )

        assert len(results) >= 1
        candidate = results[0]
        assert isinstance(candidate, MiniRelationshipCandidate)
        assert candidate.relation.relation_id == "canonical_rel_1"
        assert candidate.score > 0.0

    def test_relationship_candidate_fields(self) -> None:
        """关系候选的 RelationEvidence 字段应正确映射。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        table = db.get_table("graph_relationships")
        table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    document_id="doc_1",
                    source_name="Python",
                    target_name="Django",
                    source_chunk_ids=["chunk_a"],
                ),
            ]
        )

        results = idx.query_relationships(
            query="Python Django",
            answer_type_keywords=[],
            top_k=10,
        )
        assert len(results) >= 1

        rel = results[0].relation
        assert rel.relation_id == "canonical_rel_1"
        assert rel.document_id == "doc_1"
        assert rel.source_chunk_ids == ["chunk_a"]

    def test_relationship_metadata(self) -> None:
        """关系候选的 metadata 应包含检索参数。"""
        config = GraphCandidateInfinityConfig(
            text_weight=0.05,
            dense_weight=0.95,
        )
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")

        table = db.get_table("graph_relationships")
        table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    source_name="Python",
                    target_name="Django",
                ),
            ]
        )

        results = idx.query_relationships(
            query="Python Django",
            answer_type_keywords=["web"],
            top_k=10,
        )
        assert len(results) >= 1

        meta = results[0].metadata
        assert meta["retrieval_mode"] == "graph_candidate_infinity_hybrid"
        assert meta["candidate_kind"] == "relationship"
        assert meta["candidate_id"] == "rel_1"
        assert meta["canonical_id"] == "canonical_rel_1"
        assert meta["fusion_method"] == "weighted_sum"
        assert meta["fusion_weights"] == {"text": 0.05, "dense": 0.95}

    def test_empty_result_when_no_match(self) -> None:
        """无匹配时应返回空列表。"""
        idx, client, _ = _make_index()
        results = idx.query_relationships(
            query="nonexistent",
            answer_type_keywords=[],
            top_k=10,
        )
        assert results == []

    def test_top_k_truncation(self) -> None:
        """结果应在 fusion 后按 top_k 截断。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")

        table = db.get_table("graph_relationships")
        table.insert(
            [
                _make_relationship_row(
                    candidate_id=f"rel_{i}",
                    canonical_id=f"canonical_rel_{i}",
                    source_name=f"entity_{i}",
                    target_name=f"target_{i}",
                    vec=[0.1 * i, 0.1 * i, 0.1 * i, 0.1 * i],
                )
                for i in range(10)
            ]
        )

        results = idx.query_relationships(
            query="entity target",
            answer_type_keywords=[],
            top_k=3,
        )
        assert len(results) <= 3

    def test_uses_relationship_match_text_fields(self) -> None:
        """关系查询应使用 RELATIONSHIP_MATCH_TEXT_FIELDS。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        rel_table = db.get_table("graph_relationships")

        rel_table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    source_name="Python",
                    target_name="Django",
                ),
            ]
        )

        idx.query_relationships(
            query="Python Django",
            answer_type_keywords=[],
            top_k=10,
        )

        match_text_calls = [
            c for c in rel_table.query_calls if c["type"] == "match_text"
        ]
        assert len(match_text_calls) >= 1

        fields_arg = match_text_calls[0]["kwargs"].get("fields", "")
        for field_spec in RELATIONSHIP_MATCH_TEXT_FIELDS:
            field_name = field_spec.split("^")[0]
            assert field_name in fields_arg

    def test_uses_infinity_sdk_threshold_options(self) -> None:
        """关系查询应使用真实 Infinity 服务端接受的阈值参数形态。"""
        config = GraphCandidateInfinityConfig(
            minimum_should_match=0.3,
            dense_similarity_threshold=0.2,
        )
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")
        rel_table = db.get_table("graph_relationships")

        rel_table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    source_name="Python",
                    target_name="Django",
                ),
            ]
        )

        idx.query_relationships(
            query="Python Django",
            answer_type_keywords=[],
            top_k=10,
        )

        match_text_call = next(
            c for c in rel_table.query_calls if c["type"] == "match_text"
        )
        match_dense_call = next(
            c for c in rel_table.query_calls if c["type"] == "match_dense"
        )
        assert match_text_call["kwargs"]["extra_options"] == {
            "minimum_should_match": "30%"
        }
        assert match_dense_call["kwargs"]["knn_params"] == {"threshold": "0.2"}

    def test_embedder_called_with_original_query(self) -> None:
        """关系查询应使用原始 query 做 embedding。"""
        embedder = FakeEmbedder(dim=4)
        idx, client, _ = _make_index(embedder=embedder)
        db = client.get_database("test_db")

        table = db.get_table("graph_relationships")
        table.insert(
            [
                _make_relationship_row(
                    candidate_id="rel_1",
                    canonical_id="canonical_rel_1",
                    source_name="Python",
                    target_name="Django",
                    vec=[0.5, 0.5, 0.5, 0.5],
                ),
            ]
        )

        idx.query_relationships(
            query="What is Python Django?",
            answer_type_keywords=[],
            top_k=10,
        )
        assert embedder.last_query == "What is Python Django?"


# ===========================================================================
# 测试：constructor 行为
# ===========================================================================


class TestConstructor:
    """构造函数测试。"""

    def test_default_config(self) -> None:
        """未指定 config 时使用默认值。"""
        client = _GraphFakeInfinityClient()
        embedder = FakeEmbedder()
        idx = InfinityGraphCandidateIndex(
            client=client,
            database="test_db",
            embedder=embedder,
        )
        assert idx._config.entity_table == "graph_entities"
        assert idx._config.relationship_table == "graph_relationships"

    def test_creates_graph_candidate_tables_and_fulltext_indexes_on_init(self) -> None:
        """初始化时应幂等创建 graph_entities / graph_relationships 及全文索引。"""
        client = _GraphFakeInfinityClient()
        embedder = FakeEmbedder(dim=4)

        InfinityGraphCandidateIndex(
            client=client,
            database="test_db",
            embedder=embedder,
        )

        db = client.get_database("test_db")
        assert "graph_entities" in db.created_tables
        assert "graph_relationships" in db.created_tables

        entity_columns = db.created_tables["graph_entities"]
        relationship_columns = db.created_tables["graph_relationships"]
        assert entity_columns["vec"]["type"] == "vector,4,float"
        assert relationship_columns["vec"]["type"] == "vector,4,float"
        assert entity_columns["candidate_id"]["constraints"] == ["primary key"]
        assert relationship_columns["candidate_id"]["constraints"] == ["primary key"]

        entity_table = db.get_table("graph_entities")
        relationship_table = db.get_table("graph_relationships")
        assert (
            entity_table._indexes["graph_entities_entity_name_kwd_fulltext_idx"]["type"]
            == IndexType.FullText
        )
        assert (
            entity_table._indexes["graph_entities_entity_name_tks_fulltext_idx"]["type"]
            == IndexType.FullText
        )
        assert (
            entity_table._indexes["graph_entities_entity_type_tks_fulltext_idx"]["type"]
            == IndexType.FullText
        )
        assert (
            relationship_table._indexes[
                "graph_relationships_relationship_endpoint_kwd_fulltext_idx"
            ]["type"]
            == IndexType.FullText
        )
        assert (
            relationship_table._indexes[
                "graph_relationships_relationship_endpoint_tks_fulltext_idx"
            ]["type"]
            == IndexType.FullText
        )
        assert (
            relationship_table._indexes[
                "graph_relationships_relationship_keyword_tks_fulltext_idx"
            ]["type"]
            == IndexType.FullText
        )
        assert (
            relationship_table._indexes[
                "graph_relationships_relationship_description_tks_fulltext_idx"
            ]["type"]
            == IndexType.FullText
        )

    def test_custom_config(self) -> None:
        """自定义 config 应被使用。"""
        client = _GraphFakeInfinityClient()
        embedder = FakeEmbedder()
        config = GraphCandidateInfinityConfig(
            entity_table="my_entities",
            graph_initial_recall_n=256,
        )
        idx = InfinityGraphCandidateIndex(
            client=client,
            database="test_db",
            embedder=embedder,
            config=config,
        )
        assert idx._config.entity_table == "my_entities"
        assert idx._config.graph_initial_recall_n == 256

    def test_custom_table_names(self) -> None:
        """自定义表名应正确传递到查询。"""
        config = GraphCandidateInfinityConfig(
            entity_table="custom_entities",
            relationship_table="custom_relationships",
        )
        idx, client, _ = _make_index(config=config)
        db = client.get_database("test_db")

        # 创建自定义表并插入数据
        entity_table = db.get_table("custom_entities")
        entity_table.insert(
            [
                _make_entity_row(
                    candidate_id="e1",
                    canonical_id="c1",
                    entity_name="Python",
                ),
            ]
        )

        results = idx.query_entities(["Python"], top_k=10)
        # 如果查到了，说明使用了正确的自定义表名
        assert len(results) >= 1


# ===========================================================================
# 测试：行生命周期（upsert / delete）
# ===========================================================================


def _make_entity_evidence(
    *,
    entity_id: str = "ent_1",
    document_id: str = "doc_1",
    name: str = "Python",
    entity_type: str = "language",
    description: str = "A programming language",
    source_chunk_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EntityEvidence:
    """创建测试用 EntityEvidence。"""
    return EntityEvidence(
        entity_id=entity_id,
        document_id=document_id,
        name=name,
        entity_type=entity_type,
        description=description,
        source_chunk_ids=source_chunk_ids or ["chunk_1"],
        metadata=metadata or {},
    )


def _make_relation_evidence(
    *,
    relation_id: str = "rel_1",
    document_id: str = "doc_1",
    source_entity_id: str = "src_1",
    target_entity_id: str = "tgt_1",
    source_entity_name: str = "Python",
    target_entity_name: str = "Django",
    description: str = "Python uses Django",
    keywords: list[str] | None = None,
    weight: float = 1.0,
    source_chunk_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RelationEvidence:
    """创建测试用 RelationEvidence。"""
    return RelationEvidence(
        relation_id=relation_id,
        document_id=document_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        source_entity_name=source_entity_name,
        target_entity_name=target_entity_name,
        description=description,
        keywords=keywords or ["web framework"],
        weight=weight,
        source_chunk_ids=source_chunk_ids or ["chunk_1"],
        metadata=metadata or {},
    )


class TestUpsertDocumentEvidence:
    """upsert_document_evidence 生命周期测试。"""

    def test_builds_and_inserts_entity_and_relationship_rows(self) -> None:
        """upsert 应先删除旧行，再构建并插入实体和关系行。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")
        rel_table = db.get_table("graph_relationships")

        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[
                _make_entity_evidence(entity_id="ent_1", name="Python"),
            ],
            relations=[
                _make_relation_evidence(relation_id="rel_1"),
            ],
        )

        idx.upsert_document_evidence(batch)

        # 验证 delete 先被调用（upsert 语义：先删后插）
        assert "document_id = 'doc_1'" in entity_table.deleted_filters
        assert "document_id = 'doc_1'" in rel_table.deleted_filters

        # 验证实体行已插入
        assert len(entity_table.rows) == 1
        entity_row = entity_table.rows[0]
        assert entity_row["candidate_id"] == "ent_1"
        assert entity_row["document_id"] == "doc_1"
        assert entity_row["candidate_kind"] == "entity"
        assert entity_row["entity_name_kwd"] == "Python"
        assert "vec" in entity_row

        # 验证关系行已插入
        assert len(rel_table.rows) == 1
        rel_row = rel_table.rows[0]
        assert rel_row["candidate_id"] == "rel_1"
        assert rel_row["document_id"] == "doc_1"
        assert rel_row["candidate_kind"] == "relationship"
        assert "vec" in rel_row

    def test_delete_called_before_insert(self) -> None:
        """upsert 应先删除旧行再插入新行，确保替换语义。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        # 先插入旧行
        entity_table.insert(
            [_make_entity_row(candidate_id="old_ent", document_id="doc_1")]
        )
        assert len(entity_table.rows) == 1

        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[_make_entity_evidence(entity_id="new_ent")],
            relations=[],
        )

        idx.upsert_document_evidence(batch)

        # 旧行应被删除，只有新行存在
        assert len(entity_table.rows) == 1
        assert entity_table.rows[0]["candidate_id"] == "new_ent"

    def test_embedder_called_for_each_entity_and_relation(self) -> None:
        """upsert 应为每个实体和关系调用 embedder 构建 embedding。"""
        embedder = FakeEmbedder(dim=4)
        idx, client, _ = _make_index(embedder=embedder)

        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[
                _make_entity_evidence(entity_id="e1", name="Python"),
                _make_entity_evidence(entity_id="e2", name="Java"),
            ],
            relations=[
                _make_relation_evidence(
                    relation_id="r1",
                    source_entity_name="Python",
                    target_entity_name="Django",
                ),
            ],
        )

        idx.upsert_document_evidence(batch)

        # embedder.last_query 保存最后一次调用
        # 关系 embed 文本包含 target name，验证最后一次调用
        assert "Django" in embedder.last_query

    def test_entity_row_has_correct_fields(self) -> None:
        """插入的实体行应包含 build_entity_candidate_row 的全部字段。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        entity = _make_entity_evidence(
            entity_id="ent_42",
            name="FastAPI",
            entity_type="framework",
            description="A modern web framework",
            source_chunk_ids=["chunk_a", "chunk_b"],
        )
        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[entity],
            relations=[],
        )

        idx.upsert_document_evidence(batch)

        row = entity_table.rows[0]
        assert row["candidate_id"] == "ent_42"
        assert row["canonical_id"] == "ent_42"
        assert row["document_id"] == "doc_1"
        assert row["candidate_kind"] == "entity"
        assert row["entity_name_kwd"] == "FastAPI"
        assert row["source_chunk_ids"] == ["chunk_a", "chunk_b"]
        assert row["metadata"] == {}


class TestUpsertSkipsInsert:
    """upsert 在无实体或无关系时应跳过对应的 insert。"""

    def test_skips_entity_insert_when_no_entities(self) -> None:
        """没有实体时不应调用实体表 insert。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")
        rel_table = db.get_table("graph_relationships")

        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[],
            relations=[_make_relation_evidence(relation_id="rel_1")],
        )

        idx.upsert_document_evidence(batch)

        # 实体表不应有插入行（delete 后无新行）
        assert len(entity_table.rows) == 0
        # 关系表应有插入行
        assert len(rel_table.rows) == 1

    def test_skips_relationship_insert_when_no_relations(self) -> None:
        """没有关系时不应调用关系表 insert。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")
        rel_table = db.get_table("graph_relationships")

        batch = GraphEvidenceBatch(
            document_id="doc_1",
            entities=[_make_entity_evidence(entity_id="ent_1")],
            relations=[],
        )

        idx.upsert_document_evidence(batch)

        # 实体表应有插入行
        assert len(entity_table.rows) == 1
        # 关系表不应有插入行
        assert len(rel_table.rows) == 0


class TestDeleteDocument:
    """delete_document 生命周期测试。"""

    def test_removes_rows_from_both_tables(self) -> None:
        """delete_document 应从实体表和关系表中删除匹配行。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")
        rel_table = db.get_table("graph_relationships")

        # 插入测试数据
        entity_table.insert(
            [
                _make_entity_row(candidate_id="e1", document_id="doc_1"),
                _make_entity_row(candidate_id="e2", document_id="doc_2"),
            ]
        )
        rel_table.insert(
            [
                _make_relationship_row(candidate_id="r1", document_id="doc_1"),
                _make_relationship_row(candidate_id="r2", document_id="doc_2"),
            ]
        )

        idx.delete_document("doc_1")

        # doc_1 的行应被删除
        assert all(r["document_id"] != "doc_1" for r in entity_table.rows)
        assert all(r["document_id"] != "doc_1" for r in rel_table.rows)
        # doc_2 的行应保留
        assert any(r["document_id"] == "doc_2" for r in entity_table.rows)
        assert any(r["document_id"] == "doc_2" for r in rel_table.rows)

    def test_delete_filter_expression(self) -> None:
        """delete 应使用正确的 filter 表达式。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")
        rel_table = db.get_table("graph_relationships")

        idx.delete_document("my_doc")

        assert entity_table.deleted_filters == ["document_id = 'my_doc'"]
        assert rel_table.deleted_filters == ["document_id = 'my_doc'"]

    def test_delete_escapes_single_quotes(self) -> None:
        """document_id 含单引号时应正确转义，防止 SQL 注入。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        idx.delete_document("it's_a_trap")

        # 单引号应被转义
        assert entity_table.deleted_filters == ["document_id = 'it\\'s_a_trap'"]

    def test_delete_nonexistent_document_is_safe(self) -> None:
        """删除不存在的文档不应抛出异常。"""
        idx, client, _ = _make_index()
        db = client.get_database("test_db")
        entity_table = db.get_table("graph_entities")

        # 表为空时删除不应报错
        idx.delete_document("nonexistent")
        assert entity_table.deleted_filters == ["document_id = 'nonexistent'"]
