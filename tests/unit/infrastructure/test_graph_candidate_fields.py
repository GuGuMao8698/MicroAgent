"""graph_candidate_fields 的单元测试。

验证：
- entity 行包含 name_kwd / name_tks / type_tks / description_tks，
  但 description_tks 不出现在 ENTITY_MATCH_TEXT_FIELDS 中。
- relationship 行包含 endpoint_kwd / endpoint_tks / keyword_tks / description_tks，
  且 RELATIONSHIP_MATCH_TEXT_FIELDS 包含正确的 boost。
- embedding_text 格式符合预期。
- canonical_id 优先取 metadata.canonical_id，无则回退到 entity_id / relation_id。
"""

import json

from ragflow_lite.domain.models.entities import EntityEvidence, RelationEvidence
from ragflow_lite.infrastructure.evidence.graph_candidate_fields import (
    ENTITY_MATCH_TEXT_FIELDS,
    RELATIONSHIP_MATCH_TEXT_FIELDS,
    build_entity_candidate_row,
    build_relationship_candidate_row,
)

# ---------------------------------------------------------------------------
# 测试用确定性分词器
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> str:
    return f"tok::{text.lower()}"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_entity(**overrides) -> EntityEvidence:
    defaults = dict(
        entity_id="ent-001",
        document_id="doc-A",
        name="Python",
        entity_type="Programming Language",
        description="A high-level programming language.",
        source_chunk_ids=["chk-1", "chk-2"],
        metadata={},
    )
    defaults.update(overrides)
    return EntityEvidence(**defaults)


def _make_relation(**overrides) -> RelationEvidence:
    defaults = dict(
        relation_id="rel-001",
        document_id="doc-A",
        source_entity_id="ent-001",
        target_entity_id="ent-002",
        source_entity_name="Python",
        target_entity_name="Django",
        description="Python is the foundation of Django.",
        keywords=["framework", "web"],
        weight=0.85,
        source_chunk_ids=["chk-1"],
        metadata={},
    )
    defaults.update(overrides)
    return RelationEvidence(**defaults)


_VEC = [0.1, 0.2, 0.3]


# ===========================================================================
# Entity tests
# ===========================================================================


class TestEntityCandidateRow:
    """实体候选行构建测试。"""

    def test_entity_row_contains_required_fields(self):
        """行必须包含 candidate_id, canonical_id, document_id, candidate_kind 等基础字段。"""
        entity = _make_entity()
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["candidate_id"] == "ent-001"
        assert row["canonical_id"] == "ent-001"
        assert row["document_id"] == "doc-A"
        assert row["candidate_kind"] == "entity"

    def test_entity_row_name_fields_use_name_only(self):
        """name_kwd 保存原始 name；name_tks 保存分词结果。"""
        entity = _make_entity(name="Python")
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["entity_name_kwd"] == "Python"
        assert row["entity_name_tks"] == "tok::python"

    def test_entity_row_type_tks_is_tokenized(self):
        """entity_type_tks 保存 entity_type 的分词结果。"""
        entity = _make_entity(entity_type="Programming Language")
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["entity_type_tks"] == "tok::programming language"

    def test_entity_row_description_tks_present_in_row(self):
        """entity_description_tks 在行中存在（可被索引），但不在 ENTITY_MATCH_TEXT_FIELDS 中。"""
        entity = _make_entity(description="A high-level programming language.")
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert (
            row["entity_description_tks"] == "tok::a high-level programming language."
        )

    def test_entity_description_tks_not_in_match_fields(self):
        """entity_description_tks 不出现在 ENTITY_MATCH_TEXT_FIELDS 中（不参与默认文本匹配）。"""
        field_names = [f.split("^")[0] for f in ENTITY_MATCH_TEXT_FIELDS]
        assert "entity_description_tks" not in field_names

    def test_entity_match_fields_have_expected_names_and_boosts(self):
        """ENTITY_MATCH_TEXT_FIELDS 应包含 name_kwd^30, name_tks^20, type_tks^2。"""
        assert ENTITY_MATCH_TEXT_FIELDS == [
            "entity_name_kwd^30",
            "entity_name_tks^20",
            "entity_type_tks^2",
        ]

    def test_entity_embedding_text_is_name_only(self):
        """embedding_text 应只包含实体名称，不含 description。"""
        entity = _make_entity(name="Python", description="A high-level language.")
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["embedding_text"] == "Python"

    def test_entity_vec_and_source_chunk_ids(self):
        """vec 透传，source_chunk_ids 按 live Infinity varchar 契约写为 JSON。"""
        entity = _make_entity()
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["vec"] == [0.1, 0.2, 0.3]
        assert json.loads(row["source_chunk_ids"]) == ["chk-1", "chk-2"]

    def test_entity_metadata_copied(self):
        """metadata 按 live Infinity varchar 契约写为 JSON。"""
        entity = _make_entity(metadata={"canonical_id": "c-xyz"})
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert json.loads(row["metadata"]) == {"canonical_id": "c-xyz"}
        assert row["metadata"] != entity.metadata

    def test_entity_canonical_id_from_metadata(self):
        """canonical_id 应优先取 metadata.canonical_id。"""
        entity = _make_entity(metadata={"canonical_id": "canonical-python"})
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["canonical_id"] == "canonical-python"

    def test_entity_canonical_id_falls_back_to_entity_id(self):
        """metadata 无 canonical_id 时，回退到 entity_id。"""
        entity = _make_entity(metadata={})
        row = build_entity_candidate_row(entity, vector=_VEC, tokenize=_tokenize)

        assert row["canonical_id"] == "ent-001"


# ===========================================================================
# Relationship tests
# ===========================================================================


class TestRelationshipCandidateRow:
    """关系候选行构建测试。"""

    def test_relationship_row_contains_required_fields(self):
        """行必须包含 candidate_id, canonical_id, document_id, candidate_kind 等。"""
        rel = _make_relation()
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["candidate_id"] == "rel-001"
        assert row["canonical_id"] == "rel-001"
        assert row["document_id"] == "doc-A"
        assert row["candidate_kind"] == "relationship"

    def test_relationship_row_entity_ids_and_names(self):
        """source/target entity id 和 name 正确透传。"""
        rel = _make_relation()
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["source_entity_id"] == "ent-001"
        assert row["target_entity_id"] == "ent-002"
        assert row["source_entity_name"] == "Python"
        assert row["target_entity_name"] == "Django"

    def test_relationship_endpoint_fields(self):
        """endpoint_kwd = 'source_name target_name'；endpoint_tks 为其分词结果。"""
        rel = _make_relation()
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["relationship_endpoint_kwd"] == "Python Django"
        assert row["relationship_endpoint_tks"] == "tok::python django"

    def test_relationship_keyword_tks(self):
        """keyword_tks 为 keywords 空格拼接后的分词结果。"""
        rel = _make_relation(keywords=["framework", "web"])
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["relationship_keyword_tks"] == "tok::framework web"

    def test_relationship_description_tks(self):
        """description_tks 为 description 的分词结果。"""
        rel = _make_relation(description="Python is the foundation of Django.")
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert (
            row["relationship_description_tks"]
            == "tok::python is the foundation of django."
        )

    def test_relationship_match_fields_have_expected_names_and_boosts(self):
        """RELATIONSHIP_MATCH_TEXT_FIELDS 应包含四个字段及正确 boost。"""
        assert RELATIONSHIP_MATCH_TEXT_FIELDS == [
            "relationship_endpoint_kwd^30",
            "relationship_endpoint_tks^20",
            "relationship_keyword_tks^20",
            "relationship_description_tks^2",
        ]

    def test_relationship_embedding_text_format(self):
        """embedding_text 应按 source/target/keywords/description 四行格式构建。"""
        rel = _make_relation(
            source_entity_name="Python",
            target_entity_name="Django",
            keywords=["framework", "web"],
            description="Python is the foundation of Django.",
        )
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        expected = (
            "source: Python\n"
            "target: Django\n"
            "keywords: framework web\n"
            "description: Python is the foundation of Django."
        )
        assert row["embedding_text"] == expected

    def test_relationship_vec_weight_keywords_source_chunk_ids(self):
        """数组字段按 live Infinity varchar 契约写为 JSON。"""
        rel = _make_relation(
            weight=0.85, keywords=["a", "b"], source_chunk_ids=["chk-3"]
        )
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["vec"] == [0.1, 0.2, 0.3]
        assert row["weight"] == 0.85
        assert json.loads(row["keywords"]) == ["a", "b"]
        assert json.loads(row["source_chunk_ids"]) == ["chk-3"]

    def test_relationship_metadata_copied(self):
        """metadata 按 live Infinity varchar 契约写为 JSON。"""
        rel = _make_relation(metadata={"canonical_id": "c-rel"})
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert json.loads(row["metadata"]) == {"canonical_id": "c-rel"}
        assert row["metadata"] != rel.metadata

    def test_relationship_canonical_id_from_metadata(self):
        """canonical_id 应优先取 metadata.canonical_id。"""
        rel = _make_relation(metadata={"canonical_id": "canonical-rel"})
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["canonical_id"] == "canonical-rel"

    def test_relationship_canonical_id_falls_back_to_relation_id(self):
        """metadata 无 canonical_id 时，回退到 relation_id。"""
        rel = _make_relation(metadata={})
        row = build_relationship_candidate_row(rel, vector=_VEC, tokenize=_tokenize)

        assert row["canonical_id"] == "rel-001"
