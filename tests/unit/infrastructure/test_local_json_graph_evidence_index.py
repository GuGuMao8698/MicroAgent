from __future__ import annotations

from pathlib import Path

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_scoring import (
    GraphCandidateRetrievalConfig,
)
from ragflow_lite.infrastructure.evidence.graph_candidate_sidecar import (
    GraphCandidateSidecar,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_evidence_index import (
    LocalJsonGraphEvidenceIndex,
)
from ragflow_lite.infrastructure.evidence.local_json_graph_hybrid_index import (
    LocalJsonGraphEvidenceHybridIndex,
)
from ragflow_lite.infrastructure.evidence.local_json_store import (
    LocalJsonGraphEvidenceStore,
)


def _write_batch(tmp_path) -> None:
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc1",
            entities=[
                EntityEvidence(
                    entity_id="entity_minirag",
                    document_id="doc1",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval mode.",
                    source_chunk_ids=["chunk_a"],
                ),
                EntityEvidence(
                    entity_id="entity_sources",
                    document_id="doc1",
                    name="Sources",
                    entity_type="evidence",
                    description="Recovered chunks.",
                    source_chunk_ids=["chunk_b"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="relation_minirag_sources",
                    document_id="doc1",
                    source_entity_id="entity_minirag",
                    target_entity_id="entity_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Sources",
                    description="MiniRAG recovers source chunks.",
                    keywords=["mechanism"],
                    weight=1.0,
                    source_chunk_ids=["chunk_a", "chunk_b"],
                )
            ],
        )
    )


def test_local_json_graph_index_queries_entities_relationships_and_paths(
    tmp_path,
) -> None:
    _write_batch(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path)

    entity_candidates = index.query_entities(["MiniRAG"], top_k=3)
    relationship_candidates = index.query_relationships(
        "How does MiniRAG recover sources?",
        ["mechanism"],
        top_k=3,
    )
    paths = index.expand_paths(
        seed_entity_ids=[entity_candidates[0].entity.entity_id],
        seed_relation_ids=[relationship_candidates[0].relation.relation_id],
        max_hops=2,
    )

    assert [candidate.entity.entity_id for candidate in entity_candidates] == [
        "entity_minirag"
    ]
    assert [
        candidate.relation.relation_id for candidate in relationship_candidates
    ] == ["relation_minirag_sources"]
    assert paths[0].candidate_group_id == "entity_minirag"
    assert paths[0].candidate_rank == 0
    assert paths[0].source_chunk_ids == ["chunk_a", "chunk_b"]
    assert paths[0].metadata["hop_count"] == 1


# ---------------------------------------------------------------------------
# 混合索引测试辅助
# ---------------------------------------------------------------------------


class _AliasAwareEmbedder:
    """伪嵌入器：为特定文本对返回近似向量，其余文本返回正交向量。

    用于测试稠密别名召回：查询 "ts" 的向量与 "TypeScript" 的向量高度相似。
    """

    _DIMS = 8

    def __init__(
        self,
        aliases: dict[str, list[str]] | None = None,
        similar_value: float = 0.95,
    ) -> None:
        self._aliases = aliases or {}
        self._similar_value = similar_value
        # 基础向量表：为每个文本分配一个唯一正交方向
        self._vectors: dict[str, list[float]] = {}

    def embed_query(self, query: str) -> list[float]:
        if query in self._vectors:
            return list(self._vectors[query])

        # 查看是否有别名映射
        for canonical, alias_list in self._aliases.items():
            if query in alias_list or query == canonical:
                # 分配一个基础向量给 canonical
                if canonical not in self._vectors:
                    self._vectors[canonical] = self._make_unit(len(self._vectors))
                base_vec = self._vectors[canonical]
                # 别名返回高度相似向量
                result = [v * self._similar_value for v in base_vec]
                # 添加少量正交分量保持归一化
                result[0] += (1.0 - self._similar_value**2) ** 0.5
                self._vectors[query] = result
                return list(result)

        # 未命中别名，分配新正交向量
        vec = self._make_unit(len(self._vectors))
        self._vectors[query] = vec
        return list(vec)

    @classmethod
    def _make_unit(cls, idx: int) -> list[float]:
        """生成第 idx 个正交单位向量（one-hot）。"""
        vec = [0.0] * cls._DIMS
        vec[idx % cls._DIMS] = 1.0
        return vec


_REL_EMBED_TEXT = (
    "TypeScript\nNode.js\nruntime execution\nTypeScript code runs on Node.js runtime."
)


def _write_hybrid_batch(evidence_dir: Path, sidecar_dir: Path) -> None:
    """写入包含 TypeScript / Node.js 实体和关系的测试数据。"""
    embedder = _AliasAwareEmbedder(
        aliases={"TypeScript": ["ts"], _REL_EMBED_TEXT: ["uses runtime"]},
    )
    sidecar = GraphCandidateSidecar(sidecar_dir, embedding_signature={"model": "test"})

    batch = GraphEvidenceBatch(
        document_id="doc_ts",
        entities=[
            EntityEvidence(
                entity_id="entity_typescript",
                document_id="doc_ts",
                name="TypeScript",
                entity_type="language",
                description="A typed superset of JavaScript.",
                source_chunk_ids=["chunk_ts"],
            ),
            EntityEvidence(
                entity_id="entity_nodejs",
                document_id="doc_ts",
                name="Node.js",
                entity_type="runtime",
                description="JavaScript runtime built on V8 engine.",
                source_chunk_ids=["chunk_node"],
            ),
            EntityEvidence(
                entity_id="entity_web_framework",
                document_id="doc_ts",
                name="Web Framework",
                entity_type="concept",
                description="Typescript is commonly used in web frameworks.",
                source_chunk_ids=["chunk_fw"],
            ),
        ],
        relations=[
            RelationEvidence(
                relation_id="rel_uses_runtime",
                document_id="doc_ts",
                source_entity_id="entity_typescript",
                target_entity_id="entity_nodejs",
                source_entity_name="TypeScript",
                target_entity_name="Node.js",
                description="TypeScript code runs on Node.js runtime.",
                keywords=["runtime", "execution"],
                weight=1.0,
                source_chunk_ids=["chunk_ts", "chunk_node"],
            )
        ],
    )

    store = LocalJsonGraphEvidenceStore(evidence_dir)
    store.upsert_document_evidence(batch)
    sidecar.rebuild_document(batch, embedder)


def _make_hybrid_index(
    evidence_dir: Path,
    sidecar_dir: Path,
    config: GraphCandidateRetrievalConfig | None = None,
) -> LocalJsonGraphEvidenceHybridIndex:
    """构造混合索引实例，使用别名感知嵌入器。"""
    embedder = _AliasAwareEmbedder(
        aliases={"TypeScript": ["ts"], _REL_EMBED_TEXT: ["uses runtime"]},
    )
    sidecar = GraphCandidateSidecar(sidecar_dir, embedding_signature={"model": "test"})
    return LocalJsonGraphEvidenceHybridIndex(
        evidence_dir=evidence_dir,
        sidecar=sidecar,
        embedder=embedder,
        config=config,
    )


# ---------------------------------------------------------------------------
# 混合索引测试
# ---------------------------------------------------------------------------


def test_hybrid_entity_query_recalls_dense_alias_and_exposes_metadata(
    tmp_path,
) -> None:
    """查询 "ts" 通过稠密分支召回 "TypeScript" 实体，metadata 包含 retrieval_sources=["dense"]。"""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    sidecar_dir = tmp_path / "sidecar"
    sidecar_dir.mkdir()

    _write_hybrid_batch(evidence_dir, sidecar_dir)
    index = _make_hybrid_index(evidence_dir, sidecar_dir)

    results = index.query_entities(["ts"], top_k=3)

    # 应能召回 TypeScript 实体
    ids = [c.entity.entity_id for c in results]
    assert "entity_typescript" in ids

    # 找到 TypeScript 候选并检查 metadata
    ts_candidate = next(c for c in results if c.entity.entity_id == "entity_typescript")
    meta = ts_candidate.metadata
    assert meta["retrieval_mode"] == "graph_evidence_hybrid"
    assert "dense" in meta["retrieval_sources"]
    assert meta["dense_score"] > 0.0
    assert meta["fusion_score"] > 0.0
    assert meta["fusion_weights"]["lexical"] == 0.3
    assert meta["fusion_weights"]["dense"] == 0.7
    assert meta["minimum_should_match"] == 0.3
    assert meta["dense_similarity_threshold"] == 0.2


def test_hybrid_entity_query_keeps_name_match_above_description_match(
    tmp_path,
) -> None:
    """纯词法场景（高稠密阈值），名称精确匹配得分高于描述包含匹配。"""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    sidecar_dir = tmp_path / "sidecar"
    sidecar_dir.mkdir()

    _write_hybrid_batch(evidence_dir, sidecar_dir)

    # 使用高稠密阈值，排除稠密分支，仅依赖词法
    config = GraphCandidateRetrievalConfig(
        dense_similarity_threshold=1.0,  # 不可能达到，排除稠密
        minimum_should_match=0.0,  # 不过滤低匹配率
    )
    index = _make_hybrid_index(evidence_dir, sidecar_dir, config=config)

    # "typescript" 应匹配 entity_typescript（名称精确）和 entity_web_framework（描述包含）
    results = index.query_entities(["typescript"], top_k=3)

    ids = [c.entity.entity_id for c in results]
    # 名称精确匹配的 TypeScript 应排在描述包含匹配的 Web Framework 之前
    assert len(ids) >= 2
    assert ids.index("entity_typescript") < ids.index("entity_web_framework")


def test_hybrid_relationship_query_recalls_dense_paraphrase(tmp_path) -> None:
    """查询 "uses runtime" 通过稠密分支召回关系（旁路向量包含类似文本）。"""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    sidecar_dir = tmp_path / "sidecar"
    sidecar_dir.mkdir()

    _write_hybrid_batch(evidence_dir, sidecar_dir)
    index = _make_hybrid_index(evidence_dir, sidecar_dir)

    results = index.query_relationships("uses runtime", [], top_k=3)

    ids = [c.relation.relation_id for c in results]
    assert "rel_uses_runtime" in ids

    # 检查 metadata
    rel_candidate = next(
        c for c in results if c.relation.relation_id == "rel_uses_runtime"
    )
    meta = rel_candidate.metadata
    assert meta["retrieval_mode"] == "graph_evidence_hybrid"
    assert "dense" in meta["retrieval_sources"]


def test_hybrid_index_reload_sees_new_graph_evidence(tmp_path) -> None:
    """写入新证据后，混合索引（reload_on_query=True）无需重建即可看到新数据。"""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    sidecar_dir = tmp_path / "sidecar"
    sidecar_dir.mkdir()

    _write_hybrid_batch(evidence_dir, sidecar_dir)
    index = _make_hybrid_index(evidence_dir, sidecar_dir)

    # 初始查询确认只有 doc_ts 的数据
    initial = index.query_entities(["TypeScript"], top_k=10)
    initial_ids = {c.entity.entity_id for c in initial}
    assert "entity_typescript" in initial_ids
    assert "entity_python" not in initial_ids

    # 写入新文档证据
    store = LocalJsonGraphEvidenceStore(evidence_dir)
    new_batch = GraphEvidenceBatch(
        document_id="doc_py",
        entities=[
            EntityEvidence(
                entity_id="entity_python",
                document_id="doc_py",
                name="Python",
                entity_type="language",
                description="A popular programming language.",
                source_chunk_ids=["chunk_py"],
            ),
        ],
        relations=[],
    )
    store.upsert_document_evidence(new_batch)

    # 重建旁路向量
    embedder = _AliasAwareEmbedder()
    sidecar = GraphCandidateSidecar(sidecar_dir, embedding_signature={"model": "test"})
    sidecar.rebuild_document(new_batch, embedder)

    # 同一个索引实例应能看到新数据
    after = index.query_entities(["Python"], top_k=10)
    after_ids = {c.entity.entity_id for c in after}
    assert "entity_python" in after_ids


# ---------------------------------------------------------------------------
# 跨文档 canonical 合并测试
# ---------------------------------------------------------------------------


def _write_cross_document_batches(tmp_path: Path) -> None:
    """写入两份文档的图证据，包含共享实体 'MiniRAG'。"""
    store = LocalJsonGraphEvidenceStore(tmp_path)
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc_a",
            entities=[
                EntityEvidence(
                    entity_id="doc_a_alpha",
                    document_id="doc_a",
                    name="Alpha",
                    entity_type="concept",
                    description="Entry concept.",
                    source_chunk_ids=["chunk_alpha"],
                ),
                EntityEvidence(
                    entity_id="doc_a_minirag",
                    document_id="doc_a",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph-first retrieval.",
                    source_chunk_ids=["chunk_minirag_a"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc_a_alpha_minirag",
                    document_id="doc_a",
                    source_entity_id="doc_a_alpha",
                    target_entity_id="doc_a_minirag",
                    source_entity_name="Alpha",
                    target_entity_name="MiniRAG",
                    description="Alpha introduces MiniRAG.",
                    keywords=["entry"],
                    weight=1.0,
                    source_chunk_ids=["chunk_rel_a"],
                )
            ],
        )
    )
    store.upsert_document_evidence(
        GraphEvidenceBatch(
            document_id="doc_b",
            entities=[
                EntityEvidence(
                    entity_id="doc_b_minirag",
                    document_id="doc_b",
                    name="MiniRAG",
                    entity_type="concept",
                    description="Graph retrieval mode.",
                    source_chunk_ids=["chunk_minirag_b"],
                ),
                EntityEvidence(
                    entity_id="doc_b_sources",
                    document_id="doc_b",
                    name="Source Chunks",
                    entity_type="evidence",
                    description="Recovered source chunks.",
                    source_chunk_ids=["chunk_sources"],
                ),
            ],
            relations=[
                RelationEvidence(
                    relation_id="doc_b_minirag_sources",
                    document_id="doc_b",
                    source_entity_id="doc_b_minirag",
                    target_entity_id="doc_b_sources",
                    source_entity_name="MiniRAG",
                    target_entity_name="Source Chunks",
                    description="MiniRAG recovers source chunks.",
                    keywords=["recovery"],
                    weight=1.0,
                    source_chunk_ids=["chunk_rel_b"],
                )
            ],
        )
    )


def test_canonical_index_merges_same_name_entities_across_documents(tmp_path) -> None:
    """canonical 模式下同名实体跨文档合并。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(
        tmp_path,
        reload_on_query=True,
        canonicalize_cross_document=True,
    )

    candidates = index.query_entities(["MiniRAG"], top_k=5)

    # 应合并为一个 canonical entity
    assert [candidate.entity.name for candidate in candidates] == ["MiniRAG"]
    entity = candidates[0].entity
    assert entity.document_id == "__canonical__"
    assert entity.source_chunk_ids == ["chunk_minirag_a", "chunk_minirag_b"]
    assert entity.metadata["member_entity_ids"] == [
        "doc_a_minirag",
        "doc_b_minirag",
    ]
    assert entity.metadata["source_document_ids"] == ["doc_a", "doc_b"]


def test_canonical_index_expands_paths_across_documents(tmp_path) -> None:
    """canonical 模式下路径可跨文档桥接。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(
        tmp_path,
        reload_on_query=True,
        canonicalize_cross_document=True,
    )

    alpha = index.query_entities(["Alpha"], top_k=1)[0]
    paths = index.expand_paths(
        seed_entity_ids=[alpha.entity.entity_id],
        seed_relation_ids=[],
        max_hops=2,
    )

    # 应存在跨文档桥接路径
    source_chunks_by_path = [path.source_chunk_ids for path in paths]
    # 跨文档路径应包含来自 doc_a 和 doc_b 的 chunks
    assert [
        "chunk_alpha",
        "chunk_minirag_a",
        "chunk_minirag_b",
        "chunk_sources",
        "chunk_rel_a",
        "chunk_rel_b",
    ] in source_chunks_by_path
    assert any(path.document_id == "__canonical__" for path in paths)


def test_legacy_index_still_keeps_document_scoped_duplicate_entities(tmp_path) -> None:
    """不启用 canonical 时，同名实体保持文档隔离。"""
    _write_cross_document_batches(tmp_path)
    index = LocalJsonGraphEvidenceIndex(tmp_path, reload_on_query=True)

    candidates = index.query_entities(["MiniRAG"], top_k=5)

    # 未启用 canonical，应返回两个独立实体
    assert [candidate.entity.entity_id for candidate in candidates] == [
        "doc_a_minirag",
        "doc_b_minirag",
    ]
