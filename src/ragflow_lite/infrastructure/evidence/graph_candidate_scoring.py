"""图候选评分的纯函数模块。

提供字段感知的词法评分、最小匹配门控、稠密余弦相似度、
加权分数融合以及确定性排序。所有函数无副作用、无 I/O。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphCandidateRetrievalConfig:
    """图候选检索的评分配置。"""

    lexical_weight: float = 0.3
    dense_weight: float = 0.7
    minimum_should_match: float = 0.3
    dense_similarity_threshold: float = 0.2
    graph_initial_candidate_k: int = 1024


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LexicalScore:
    """词法评分结果，包含分数和匹配到的词项列表。"""

    score: float
    matched_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FusedCandidateScore:
    """融合评分结果，包含词法、稠密和融合分数。"""

    candidate_id: str
    lexical_score: float
    dense_score: float
    normalized_lexical_score: float
    normalized_dense_score: float
    fusion_score: float


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------

# 匹配小写字母、数字、_ + # . 的 token
_TOKEN_RE = re.compile(r"[a-z0-9_+#.]+")


def tokenize_query_terms(values: list[str]) -> list[str]:
    """将输入字符串列表拆分为小写 token，去重并保留首次出现顺序。

    Args:
        values: 待分词的字符串列表（如查询词、关键词等）。

    Returns:
        去重后的小写 token 列表。
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for token in _TOKEN_RE.findall(value.lower()):
            if token not in seen:
                seen.add(token)
                result.append(token)
    return result


# ---------------------------------------------------------------------------
# 字段感知词法评分 — 内部辅助
# ---------------------------------------------------------------------------

# 实体字段权重：(精确匹配, 包含匹配)
_ENTITY_FIELD_WEIGHTS: dict[str, tuple[float, float]] = {
    "name": (1.0, 0.75),
    "description": (0.45, 0.25),
    "entity_type": (0.3, 0.15),
}

# 关系字段权重
_RELATIONSHIP_FIELD_WEIGHTS: dict[str, tuple[float, float]] = {
    "endpoint": (1.0, 0.75),
    "keywords": (0.8, 0.55),
    "description": (0.45, 0.25),
}


def _score_term_in_field(
    term: str,
    field_value: str,
    exact_weight: float,
    containment_weight: float,
) -> float:
    """单个查询词在单个字段上的词法评分。

    精确匹配（字段值等于词项）返回 exact_weight；
    包含匹配（词项是字段值的子串，或字段值是词项的子串）返回 containment_weight；
    否则返回 0.0。
    """
    if not term or not field_value:
        return 0.0
    if term == field_value:
        return exact_weight
    if term in field_value or field_value in term:
        return containment_weight
    return 0.0


def _best_score_for_term_in_fields(
    term: str,
    fields: list[tuple[str, float, float]],
) -> float:
    """单个查询词在多个字段上取最高分。

    Args:
        term: 查询词（已小写化）。
        fields: [(字段值, exact_weight, containment_weight), ...]
    """
    return max(
        (_score_term_in_field(term, fv, ew, cw) for fv, ew, cw in fields),
        default=0.0,
    )


# ---------------------------------------------------------------------------
# 实体词法评分
# ---------------------------------------------------------------------------


def score_entity_lexical(
    name: str,
    entity_type: str,
    description: str,
    query_terms: list[str],
    config: GraphCandidateRetrievalConfig,
) -> LexicalScore:
    """字段感知的实体词法评分。

    每个查询词在 name / description / entity_type 三个字段上计算最高分，
    总分取所有词项之和。最后通过 minimum_should_match 门控。

    Args:
        name: 实体名称。
        entity_type: 实体类型。
        description: 实体描述。
        query_terms: 已分词的查询词列表（小写）。
        config: 评分配置，包含 minimum_should_match 门控阈值。

    Returns:
        LexicalScore，包含分数和匹配到的词项。
    """
    # 统一小写化
    name_lower = name.lower()
    type_lower = entity_type.lower()
    desc_lower = description.lower()

    fields = [
        (name_lower, *_ENTITY_FIELD_WEIGHTS["name"]),
        (desc_lower, *_ENTITY_FIELD_WEIGHTS["description"]),
        (type_lower, *_ENTITY_FIELD_WEIGHTS["entity_type"]),
    ]

    total_score = 0.0
    matched: list[str] = []

    for term in query_terms:
        best = _best_score_for_term_in_fields(term, fields)
        if best > 0:
            total_score += best
            matched.append(term)

    # minimum_should_match 门控
    if query_terms:
        ratio = len(matched) / len(query_terms)
        if ratio < config.minimum_should_match:
            return LexicalScore(score=0.0, matched_terms=[])

    return LexicalScore(score=total_score, matched_terms=matched)


# ---------------------------------------------------------------------------
# 关系词法评分
# ---------------------------------------------------------------------------


def score_relationship_lexical(
    source_entity_name: str,
    target_entity_name: str,
    keywords: list[str],
    description: str,
    query_terms: list[str],
    config: GraphCandidateRetrievalConfig,
) -> LexicalScore:
    """字段感知的关系词法评分。

    每个查询词在 source/target entity name、keywords、description 上计算最高分，
    总分取所有词项之和。最后通过 minimum_should_match 门控。

    Args:
        source_entity_name: 源端实体名称。
        target_entity_name: 目标端实体名称。
        keywords: 关系关键词列表。
        description: 关系描述。
        query_terms: 已分词的查询词列表（小写）。
        config: 评分配置，包含 minimum_should_match 门控阈值。

    Returns:
        LexicalScore，包含分数和匹配到的词项。
    """
    src_lower = source_entity_name.lower()
    tgt_lower = target_entity_name.lower()
    desc_lower = description.lower()

    fields = [
        (src_lower, *_RELATIONSHIP_FIELD_WEIGHTS["endpoint"]),
        (tgt_lower, *_RELATIONSHIP_FIELD_WEIGHTS["endpoint"]),
        (desc_lower, *_RELATIONSHIP_FIELD_WEIGHTS["description"]),
    ]
    # 每个 keyword 单独作为一个字段参与评分
    for kw in keywords:
        fields.append((kw.lower(), *_RELATIONSHIP_FIELD_WEIGHTS["keywords"]))

    total_score = 0.0
    matched: list[str] = []

    for term in query_terms:
        best = _best_score_for_term_in_fields(term, fields)
        if best > 0:
            total_score += best
            matched.append(term)

    # minimum_should_match 门控
    if query_terms:
        ratio = len(matched) / len(query_terms)
        if ratio < config.minimum_should_match:
            return LexicalScore(score=0.0, matched_terms=[])

    return LexicalScore(score=total_score, matched_terms=matched)


# ---------------------------------------------------------------------------
# 余弦相似度
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。

    空向量、长度不匹配或零范数向量返回 0.0。

    Args:
        a: 向量 A。
        b: 向量 B。

    Returns:
        余弦相似度，范围 [0.0, 1.0]。
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# 融合评分
# ---------------------------------------------------------------------------


def fuse_candidate_scores(
    lexical_scores: dict[str, float],
    dense_scores: dict[str, float],
    config: GraphCandidateRetrievalConfig,
) -> list[FusedCandidateScore]:
    """将词法和稠密评分融合为最终排序结果。

    步骤：
    1. 取词法和稠密候选 ID 的并集。
    2. 对词法和稠密分数各自归一化（除以最大值，最大值为 0 时视为 1.0）。
    3. 加权融合：lexical_weight * norm_lexical + dense_weight * norm_dense。
    4. 按融合分降序、candidate_id 升序确定性排序。

    Args:
        lexical_scores: {candidate_id: 词法分数}。
        dense_scores: {candidate_id: 稠密分数}。
        config: 融合配置，包含 lexical_weight 和 dense_weight。

    Returns:
        排序后的 FusedCandidateScore 列表。
    """
    # 取并集
    all_ids = set(lexical_scores) | set(dense_scores)

    # 计算各自最大值用于归一化
    max_lexical = max(lexical_scores.values(), default=0.0)
    max_dense = max(dense_scores.values(), default=0.0)

    # 避免除零：最大值为 0 时视为 1.0
    norm_lex_divisor = max_lexical if max_lexical > 0 else 1.0
    norm_dense_divisor = max_dense if max_dense > 0 else 1.0

    results: list[FusedCandidateScore] = []
    for cid in all_ids:
        lex = lexical_scores.get(cid, 0.0)
        dense = dense_scores.get(cid, 0.0)
        norm_lex = lex / norm_lex_divisor
        norm_dense = dense / norm_dense_divisor
        fusion = config.lexical_weight * norm_lex + config.dense_weight * norm_dense

        results.append(
            FusedCandidateScore(
                candidate_id=cid,
                lexical_score=lex,
                dense_score=dense,
                normalized_lexical_score=norm_lex,
                normalized_dense_score=norm_dense,
                fusion_score=fusion,
            )
        )

    # 确定性排序：融合分降序，candidate_id 升序
    results.sort(key=lambda r: (-r.fusion_score, r.candidate_id))
    return results
