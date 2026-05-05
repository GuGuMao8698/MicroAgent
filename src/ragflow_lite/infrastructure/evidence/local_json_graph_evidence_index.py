"""基于本地 JSON 文件的图证据索引实现。

实现 EntityNameIndex、RelationshipIndex、ReasoningPathExpander 三个端口。
读取 LocalJsonGraphEvidenceStore 写入的 JSON 文件，提供词法匹配和 BFS 路径扩展。"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from ragflow_lite.domain.models import (
    EntityEvidence,
    MiniEntityCandidate,
    MiniRelationshipCandidate,
    RelationEvidence,
    TopologyPath,
)
from ragflow_lite.infrastructure.evidence.graph_evidence_canonicalizer import (
    CanonicalGraphEvidence,
    canonicalize_graph_evidence,
)
from ragflow_lite.infrastructure.evidence.local_json_store import (
    LocalJsonGraphEvidenceStore,
)


def _normalize(text: str) -> str:
    """统一转小写用于词法匹配。"""
    return text.strip().lower()


def _score_term(term: str, field: str) -> float:
    """对单个查询词与单个字段做精确/包含度评分。

    精确匹配得 1.0，前缀/后缀/子串包含得 0.5，否则 0.0。
    """
    # 精确匹配：最高分
    if term == field:
        return 1.0
    # 包含匹配：部分命中
    if term in field or field in term:
        return 0.5
    return 0.0


def _best_score_for_term(term: str, fields: list[str]) -> float:
    """单个查询词在多个字段中取最高分。"""
    return max(_score_term(term, f) for f in fields)


class LocalJsonGraphEvidenceIndex:
    """基于本地 JSON 文件的图证据索引。

    从 evidence_dir 中扫描所有 *.json 文件，加载全部实体和关系，
    提供 query_entities / query_relationships / expand_paths 三种查询能力。
    """

    def __init__(
        self,
        evidence_dir: Path,
        *,
        reload_on_query: bool = False,
        canonicalize_cross_document: bool = False,
    ) -> None:
        self._evidence_dir = evidence_dir
        self._reload_on_query = reload_on_query
        # 跨文档同名实体合并开关：启用后在加载阶段将 raw 图证据 canonicalize
        self._canonicalize_cross_document = canonicalize_cross_document
        # 惰性加载标记
        self._entities: list[EntityEvidence] | None = None
        self._relations: list[RelationEvidence] | None = None
        self._canonical_graph: CanonicalGraphEvidence | None = None

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """惰性加载所有文档的实体和关系。"""
        if (
            not self._reload_on_query
            and self._entities is not None
            and self._relations is not None
        ):
            return
        all_entities: list[EntityEvidence] = []
        all_relations: list[RelationEvidence] = []
        store = LocalJsonGraphEvidenceStore(self._evidence_dir)
        # 扫描目录下所有 JSON 文件，提取 document_id 并加载
        for json_path in sorted(self._evidence_dir.glob("*.json")):
            doc_id = json_path.stem
            batch = store.get_document_evidence(doc_id)
            if batch is not None:
                all_entities.extend(batch.entities)
                all_relations.extend(batch.relations)
        # 启用 canonical 模式时，将 raw 图证据合并为去重 canonical 图
        if self._canonicalize_cross_document:
            canonical_graph = canonicalize_graph_evidence(all_entities, all_relations)
            self._entities = canonical_graph.entities
            self._relations = canonical_graph.relationships
            self._canonical_graph = canonical_graph
        else:
            self._entities = all_entities
            self._relations = all_relations
            self._canonical_graph = None

    def _get_entities(self) -> list[EntityEvidence]:
        self._ensure_loaded()
        assert self._entities is not None
        return self._entities

    def _get_relations(self) -> list[RelationEvidence]:
        self._ensure_loaded()
        assert self._relations is not None
        return self._relations

    def _get_canonical_graph(self) -> CanonicalGraphEvidence | None:
        """返回 canonical graph（含 raw->canonical 映射），供 hybrid index 使用。"""
        self._ensure_loaded()
        return self._canonical_graph

    # ------------------------------------------------------------------
    # EntityNameIndex 实现
    # ------------------------------------------------------------------

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        """根据实体文本列表查询匹配的实体候选。

        对每个实体，计算所有查询词在其 name / entity_type / description 字段上的
        最高分之和作为总分，然后按分数降序、ID 升序排序取 top_k。
        """
        # 预处理查询词：统一小写
        terms = [_normalize(t) for t in entity_texts]
        entities = self._get_entities()

        candidates: list[MiniEntityCandidate] = []
        for entity in entities:
            # 收集该实体可用于匹配的字段（统一小写）
            fields = [
                _normalize(entity.name),
                _normalize(entity.entity_type),
                _normalize(entity.description),
            ]
            total_score = 0.0
            matched: list[str] = []
            for term in terms:
                best = _best_score_for_term(term, fields)
                if best > 0:
                    total_score += best
                    matched.append(term)

            if total_score > 0:
                candidates.append(
                    MiniEntityCandidate(
                        entity=entity,
                        score=total_score,
                        matched_terms=matched,
                    )
                )

        # 确定性排序：分数降序，ID 升序
        candidates.sort(key=lambda c: (-c.score, c.entity.entity_id))
        return candidates[:top_k]

    # ------------------------------------------------------------------
    # RelationshipIndex 实现
    # ------------------------------------------------------------------

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        """根据查询和回答类型关键词查询匹配的关系候选。

        对每个关系，计算查询词在 keywords / description / source_entity_name /
        target_entity_name 上的匹配分，加上 answer_type_keywords 在同样字段上的匹配分，
        总和作为最终分数。按分数降序、ID 升序排序取 top_k。
        """
        # 将 query 拆分为单词作为查询词
        query_terms = [_normalize(w) for w in query.split() if w.strip()]
        # 将 answer_type_keywords 额外加入匹配词列表
        keyword_terms = [_normalize(k) for k in answer_type_keywords]
        all_terms = query_terms + keyword_terms

        relations = self._get_relations()
        candidates: list[MiniRelationshipCandidate] = []

        for relation in relations:
            # 收集该关系可用于匹配的字段
            fields = [
                _normalize(relation.description),
                _normalize(relation.source_entity_name),
                _normalize(relation.target_entity_name),
            ] + [_normalize(kw) for kw in relation.keywords]

            total_score = 0.0
            matched: list[str] = []
            for term in all_terms:
                best = _best_score_for_term(term, fields)
                if best > 0:
                    total_score += best
                    matched.append(term)

            if total_score > 0:
                candidates.append(
                    MiniRelationshipCandidate(
                        relation=relation,
                        score=total_score,
                        matched_terms=matched,
                    )
                )

        # 确定性排序：分数降序，ID 升序
        candidates.sort(key=lambda c: (-c.score, c.relation.relation_id))
        return candidates[:top_k]

    # ------------------------------------------------------------------
    # ReasoningPathExpander 实现
    # ------------------------------------------------------------------

    def expand_paths(
        self,
        seed_entity_ids: list[str],
        seed_relation_ids: list[str],
        max_hops: int,
    ) -> list[TopologyPath]:
        """从种子实体和关系出发，BFS 扩展拓扑路径。

        构建邻接表（无向图），从种子实体集合开始广度优先遍历，
        每跳收集经过的 relation 和到达的 entity，记录路径和 hop 数。
        每条路径的 source_chunk_ids 为路径上所有 relation 和 entity 的
        source_chunk_ids 去重并集。score = relation.weight 之和。
        """
        entities = self._get_entities()
        relations = self._get_relations()

        # 构建实体 ID -> EntityEvidence 的映射
        entity_by_id: dict[str, EntityEvidence] = {e.entity_id: e for e in entities}
        # 构建关系 ID -> RelationEvidence 的映射
        relation_by_id: dict[str, RelationEvidence] = {
            r.relation_id: r for r in relations
        }

        # 构建无向邻接表：entity_id -> list[RelationEvidence]
        # 每条关系连接 source_entity_id 和 target_entity_id
        adjacency: dict[str, list[RelationEvidence]] = defaultdict(list)
        for rel in relations:
            adjacency[rel.source_entity_id].append(rel)
            adjacency[rel.target_entity_id].append(rel)

        # 将种子关系涉及的实体也加入种子实体集合
        # 确保种子关系的端点也作为 BFS 起点
        seed_entity_set = set(seed_entity_ids)
        for rid in seed_relation_ids:
            rel = relation_by_id.get(rid)
            if rel is not None:
                seed_entity_set.add(rel.source_entity_id)
                seed_entity_set.add(rel.target_entity_id)

        # BFS 遍历，从种子实体集合出发
        # visited_entities 记录已访问实体，visited_relations 记录已访问关系
        visited_entities: set[str] = set()
        visited_relations: set[str] = set()

        # 收集所有路径结果
        paths: list[TopologyPath] = []

        # BFS 队列元素：
        # (当前实体ID, 已经过的实体ID列表, 已经过的关系ID列表, 跳数, 候选组ID)
        # 初始将种子实体入队，每条初始路径只包含该种子实体自身
        queue: deque[tuple[str, list[str], list[str], int, str]] = deque()
        for eid in sorted(seed_entity_set):  # 排序保证确定性
            queue.append((eid, [eid], [], 0, eid))

        group_path_counts: dict[str, int] = defaultdict(int)

        while queue:
            (
                current_entity,
                path_entity_ids,
                path_relation_ids,
                hops,
                candidate_group_id,
            ) = queue.popleft()

            # 如果已达到最大跳数，不再继续扩展
            if hops >= max_hops:
                continue

            # 标记当前实体已访问
            if current_entity in visited_entities:
                continue
            visited_entities.add(current_entity)

            # 遍历当前实体的所有邻接关系
            for rel in adjacency.get(current_entity, []):
                if rel.relation_id in visited_relations:
                    continue
                visited_relations.add(rel.relation_id)

                # 确定下一跳的实体（取关系的另一端）
                next_entity = (
                    rel.target_entity_id
                    if rel.source_entity_id == current_entity
                    else rel.source_entity_id
                )

                # 构建新路径
                new_entity_ids = path_entity_ids + [next_entity]
                new_relation_ids = path_relation_ids + [rel.relation_id]
                new_hops = hops + 1

                # 汇总路径上所有 chunk IDs（从实体和关系中收集，去重保序）
                seen_chunks: set[str] = set()
                chunk_ids: list[str] = []
                # 收集路径上实体关联的 chunks
                for eid_in_path in new_entity_ids:
                    ent = entity_by_id.get(eid_in_path)
                    if ent is not None:
                        for cid in ent.source_chunk_ids:
                            if cid not in seen_chunks:
                                seen_chunks.add(cid)
                                chunk_ids.append(cid)
                # 收集路径上关系关联的 chunks
                for rid_in_path in new_relation_ids:
                    r = relation_by_id.get(rid_in_path)
                    if r is not None:
                        for cid in r.source_chunk_ids:
                            if cid not in seen_chunks:
                                seen_chunks.add(cid)
                                chunk_ids.append(cid)

                # 路径分数：路径上所有关系的 weight 之和
                score = sum(relation_by_id[rid].weight for rid in new_relation_ids)

                # 推断路径所属文档（取第一个有 document_id 的关系）
                doc_id = (
                    relation_by_id[new_relation_ids[0]].document_id
                    if new_relation_ids
                    else ""
                )

                # 生成确定性的 path_id：基于实体和关系 ID 拼接
                path_id = (
                    "path_"
                    + "_".join(new_entity_ids)
                    + "_r_"
                    + "_".join(new_relation_ids)
                )
                candidate_rank = group_path_counts[candidate_group_id]
                group_path_counts[candidate_group_id] += 1

                paths.append(
                    TopologyPath(
                        path_id=path_id,
                        document_id=doc_id,
                        entity_ids=new_entity_ids,
                        relation_ids=new_relation_ids,
                        source_chunk_ids=chunk_ids,
                        score=score,
                        candidate_group_id=candidate_group_id,
                        candidate_rank=candidate_rank,
                        metadata={"hop_count": new_hops},
                    )
                )

                # 将下一跳实体入队继续 BFS
                queue.append(
                    (
                        next_entity,
                        new_entity_ids,
                        new_relation_ids,
                        new_hops,
                        candidate_group_id,
                    )
                )

        # 确定性排序：分数降序，path_id 升序
        paths.sort(key=lambda p: (-p.score, p.path_id))
        return paths
