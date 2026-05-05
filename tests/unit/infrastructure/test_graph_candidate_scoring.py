"""graph_candidate_scoring 模块的单元测试。

覆盖：
1. tokenize_query_terms — 符号保留与去重
2. score_entity_lexical — name > description > entity_type 优先级
3. minimum_should_match 门控
4. cosine_similarity — 全同 / 正交 / 零向量
5. fuse_candidate_scores — 归一化 + 加权融合 + 确定性排序
"""

from __future__ import annotations

from ragflow_lite.domain.models import EntityEvidence, RelationEvidence
from ragflow_lite.infrastructure.evidence.graph_candidate_scoring import (
    GraphCandidateRetrievalConfig,
    cosine_similarity,
    fuse_candidate_scores,
    score_entity_lexical,
    score_relationship_lexical,
    tokenize_query_terms,
)

# ---------------------------------------------------------------------------
# 1. tokenize_query_terms
# ---------------------------------------------------------------------------


def test_tokenize_query_terms_preserves_symbolic_terms() -> None:
    """["ts", "C++", "API v1"] -> ["ts", "c++", "api", "v1"]

    验证：
    - 小写化
    - C++ 保留 + 符号（token pattern 允许 +）
    - 空格拆分
    - 去重并保序
    """
    result = tokenize_query_terms(["ts", "C++", "API v1"])
    assert result == ["ts", "c++", "api", "v1"]


def test_tokenize_query_terms_deduplicates_preserving_order() -> None:
    """重复词项去重，保留首次出现顺序。"""
    result = tokenize_query_terms(["python API", "api design", "Python"])
    assert result == ["python", "api", "design"]


# ---------------------------------------------------------------------------
# 2. Entity lexical scoring — name > description > entity_type
# ---------------------------------------------------------------------------


def _make_entity(
    name: str = "",
    entity_type: str = "",
    description: str = "",
) -> EntityEvidence:
    """创建测试用 EntityEvidence，填充必要字段。"""
    return EntityEvidence(
        entity_id="test-id",
        document_id="test-doc",
        name=name,
        entity_type=entity_type,
        description=description,
        source_chunk_ids=[],
    )


def test_entity_lexical_scoring_prioritizes_name_description_type() -> None:
    """名称匹配得分 > 描述匹配得分 > 类型匹配得分。

    使用三个仅命中单一字段的实体，验证分值排序：
    - name exact = 1.0
    - description exact = 0.45
    - entity_type exact = 0.3
    """
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.0)
    terms = ["python"]

    # 仅 name 精确匹配
    score_name = score_entity_lexical(
        entity=_make_entity(
            name="python",
            entity_type="language",
            description="A general-purpose programming language.",
        ),
        query_terms=terms,
        config=cfg,
    )
    # name 精确匹配给 1.0 分，但 entity_type="language" 不含 "python"
    # description 包含 "programming" 但不含 "python"，所以无匹配
    # 结果：name exact -> 1.0
    assert score_name.score == 1.0

    # 仅 description 精确匹配
    # name="foo" 不含 "python"，entity_type="bar" 不含 "python"
    # description="python" 精确匹配 -> 0.45
    score_desc = score_entity_lexical(
        entity=_make_entity(
            name="foo",
            entity_type="bar",
            description="python",
        ),
        query_terms=terms,
        config=cfg,
    )
    assert score_desc.score == 0.45

    # 仅 entity_type 精确匹配
    score_type = score_entity_lexical(
        entity=_make_entity(
            name="foo",
            entity_type="python",
            description="some description text",
        ),
        query_terms=terms,
        config=cfg,
    )
    assert score_type.score == 0.3

    # 排序：name > desc > type
    assert score_name.score > score_desc.score > score_type.score


def test_entity_lexical_scoring_containment_scores() -> None:
    """验证包含匹配的分数低于精确匹配。"""
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.0)
    terms = ["py"]

    # name containment: "py" in "python" -> 0.75
    score = score_entity_lexical(
        entity=_make_entity(
            name="python",
            entity_type="language",
            description="A programming language.",
        ),
        query_terms=terms,
        config=cfg,
    )
    assert score.score == 0.75

    # description containment: "py" in "cpython interpreter" -> 0.25
    score = score_entity_lexical(
        entity=_make_entity(
            name="foo",
            entity_type="bar",
            description="cpython interpreter",
        ),
        query_terms=terms,
        config=cfg,
    )
    assert score.score == 0.25


# ---------------------------------------------------------------------------
# 3. minimum_should_match gate
# ---------------------------------------------------------------------------


def test_minimum_should_match_blocks_weak_description_overlap() -> None:
    """4 个查询词中只有 1 个命中描述 -> 门控阻断（threshold=0.75）。

    matched_distinct_terms / query_distinct_terms = 1/4 = 0.25 < 0.75
    -> score=0.0, matched_terms=[]
    """
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.75)
    # 4 个查询词，只有 "graph" 出现在 description 中
    # name="FooBar" 不匹配任何查询词
    # entity_type="concept" 不匹配任何查询词
    # description 中 "graph" 被 containment 命中
    result = score_entity_lexical(
        entity=_make_entity(
            name="FooBar",
            entity_type="concept",
            description="A graph-first approach.",
        ),
        query_terms=["minirag", "graph", "retrieval", "mode"],
        config=cfg,
    )
    # 只有 "graph" 命中了 description（containment），1/4 = 0.25 < 0.75
    assert result.score == 0.0
    assert result.matched_terms == []


def test_minimum_should_match_allows_strong_overlap() -> None:
    """4 个查询词中有 3 个命中 -> 门控通过（threshold=0.75）。

    3/4 = 0.75 >= 0.75 -> 通过
    """
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.75)
    # "minirag" -> name exact, "graph" -> description containment,
    # "retrieval" -> description containment
    result = score_entity_lexical(
        entity=_make_entity(
            name="MiniRAG",
            entity_type="concept",
            description="A graph-first retrieval approach.",
        ),
        query_terms=["minirag", "graph", "retrieval", "mode"],
        config=cfg,
    )
    # 3/4 = 0.75 >= 0.75 -> 门控通过
    assert result.score > 0.0
    assert len(result.matched_terms) == 3


# ---------------------------------------------------------------------------
# 4. cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_and_dense_threshold() -> None:
    """验证余弦相似度的三种情况：全同、正交、零向量。"""
    # 全同向量 -> 1.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0

    # 正交向量 -> 0.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    # 零向量 -> 0.0（避免除零）
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_mismatched_lengths() -> None:
    """不匹配长度的向量返回 0.0。"""
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_similarity_empty_vectors() -> None:
    """空向量返回 0.0。"""
    assert cosine_similarity([], []) == 0.0


# ---------------------------------------------------------------------------
# 5. Fusion — normalize + weighted sum + deterministic sort
# ---------------------------------------------------------------------------


def test_fusion_normalizes_branch_scores_and_sorts_by_id() -> None:
    """验证融合数学和确定性排序。

    设置：
    - candidate_a: lexical=0.9, dense=0.3
    - candidate_b: lexical=0.6, dense=0.9
    - candidate_c: lexical=0.0, dense=0.6 (only in dense)
    - lexical_weight=0.3, dense_weight=0.7

    归一化（按各自最大值）：
    - lexical max = 0.9 -> norm_a_lex = 1.0, norm_b_lex = 0.6667
    - dense max = 0.9 -> norm_a_dense = 0.3333, norm_b_dense = 1.0, norm_c_dense = 0.6667

    fusion_a = 0.3*1.0 + 0.7*0.3333 = 0.5333
    fusion_b = 0.3*0.6667 + 0.7*1.0 = 0.9
    fusion_c = 0.3*0.0 + 0.7*0.6667 = 0.4667

    排序：b > a > c（融合分降序）
    """
    cfg = GraphCandidateRetrievalConfig(
        lexical_weight=0.3,
        dense_weight=0.7,
    )
    lexical = {"candidate_a": 0.9, "candidate_b": 0.6}
    dense = {"candidate_a": 0.3, "candidate_b": 0.9, "candidate_c": 0.6}

    results = fuse_candidate_scores(lexical, dense, cfg)

    # 候选 ID 的集合应该是三个的并集
    ids = [r.candidate_id for r in results]
    assert set(ids) == {"candidate_a", "candidate_b", "candidate_c"}

    # 融合分降序
    assert results[0].candidate_id == "candidate_b"
    assert results[1].candidate_id == "candidate_a"
    assert results[2].candidate_id == "candidate_c"

    # 验证 candidate_b 的融合数学
    b = results[0]
    assert b.lexical_score == 0.6
    assert b.dense_score == 0.9
    # 归一化：lexical 0.6/0.9 = 0.6667, dense 0.9/0.9 = 1.0
    assert abs(b.normalized_lexical_score - 0.6 / 0.9) < 1e-6
    assert abs(b.normalized_dense_score - 1.0) < 1e-6
    # 融合：0.3 * 0.6667 + 0.7 * 1.0 = 0.9
    assert abs(b.fusion_score - 0.9) < 1e-6

    # candidate_c 只在 dense 中，lexical 应为 0.0
    c = results[2]
    assert c.lexical_score == 0.0
    assert c.dense_score == 0.6


def test_fusion_deterministic_sort_by_id_on_tie() -> None:
    """融合分相同时按 candidate_id 升序排列（确定性排序）。"""
    cfg = GraphCandidateRetrievalConfig(
        lexical_weight=0.5,
        dense_weight=0.5,
    )
    # 两个候选 lexical+dense 完全相同，融合分相同
    lexical = {"alpha": 0.5, "beta": 0.5}
    dense = {"alpha": 0.5, "beta": 0.5}

    results = fuse_candidate_scores(lexical, dense, cfg)
    assert results[0].candidate_id == "alpha"
    assert results[1].candidate_id == "beta"


def test_fusion_handles_all_zero_scores() -> None:
    """所有分数为零时，归一化应避免除零（max=0 时视为 1.0）。"""
    cfg = GraphCandidateRetrievalConfig()
    results = fuse_candidate_scores(
        {"x": 0.0, "y": 0.0},
        {"x": 0.0, "y": 0.0},
        cfg,
    )
    for r in results:
        assert r.fusion_score == 0.0


# ---------------------------------------------------------------------------
# Relationship lexical scoring
# ---------------------------------------------------------------------------


def _make_relation(
    source_entity_name: str = "",
    target_entity_name: str = "",
    keywords: list[str] | None = None,
    description: str = "",
) -> RelationEvidence:
    """创建测试用 RelationEvidence，填充必要字段。"""
    return RelationEvidence(
        relation_id="test-relation-id",
        document_id="test-doc",
        source_entity_id="src-id",
        target_entity_id="tgt-id",
        source_entity_name=source_entity_name,
        target_entity_name=target_entity_name,
        description=description,
        keywords=keywords or [],
        weight=1.0,
        source_chunk_ids=[],
    )


def test_relationship_lexical_scoring_endpoint_exact_match() -> None:
    """端点实体名称精确匹配得分最高（1.0）。"""
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.0)
    result = score_relationship_lexical(
        relation=_make_relation(
            source_entity_name="python",
            target_entity_name="django",
            keywords=["web", "framework"],
            description="Python is a web framework using Django.",
        ),
        query_terms=["python"],
        config=cfg,
    )
    # source entity name exact -> 1.0
    assert result.score == 1.0
    assert "python" in result.matched_terms


def test_relationship_lexical_scoring_keywords_match() -> None:
    """关键词匹配使用 relationship keywords 字段。"""
    cfg = GraphCandidateRetrievalConfig(minimum_should_match=0.0)
    result = score_relationship_lexical(
        relation=_make_relation(
            source_entity_name="foo",
            target_entity_name="bar",
            keywords=["framework", "web"],
            description="Something about design.",
        ),
        query_terms=["framework"],
        config=cfg,
    )
    # keywords exact -> 0.8
    assert result.score == 0.8
