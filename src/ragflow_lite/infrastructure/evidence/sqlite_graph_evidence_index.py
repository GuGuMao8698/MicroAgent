"""基于 SQLite active artifact 的图证据索引实现。"""

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
from ragflow_lite.infrastructure.evidence.sqlite_artifact_registry import (
    SqliteArtifactRegistry,
)
from ragflow_lite.infrastructure.evidence.sqlite_graph_evidence_store import (
    SqliteGraphEvidenceStore,
)


def _normalize(text: str) -> str:
    return text.strip().lower()


def _score_term(term: str, field: str) -> float:
    if term == field:
        return 1.0
    if term in field or field in term:
        return 0.5
    return 0.0


def _best_score_for_term(term: str, fields: list[str]) -> float:
    return max(_score_term(term, f) for f in fields)


class SqliteGraphEvidenceIndex:
    def __init__(
        self,
        db_path: Path,
        *,
        canonicalize_cross_document: bool = False,
    ) -> None:
        self._db_path = db_path
        self._canonicalize_cross_document = canonicalize_cross_document
        self._entities: list[EntityEvidence] | None = None
        self._relations: list[RelationEvidence] | None = None
        self._canonical_graph: CanonicalGraphEvidence | None = None
        self._active_build_snapshot: tuple[tuple[str, str], ...] | None = None

    def _load_active_build_snapshot(self) -> tuple[tuple[str, str], ...]:
        registry = SqliteArtifactRegistry(self._db_path)
        with registry.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.document_id, a.active_build_id
                FROM active_artifacts a
                JOIN artifact_builds b ON b.build_id = a.active_build_id
                WHERE a.artifact_type = ? AND b.status = ?
                ORDER BY a.document_id ASC
                """,
                ("graph_evidence", "active"),
            ).fetchall()
        return tuple(
            (str(row["document_id"]), str(row["active_build_id"])) for row in rows
        )

    def _ensure_loaded(self) -> None:
        active_build_snapshot = self._load_active_build_snapshot()
        if (
            self._entities is not None
            and self._relations is not None
            and self._active_build_snapshot == active_build_snapshot
        ):
            return
        all_entities: list[EntityEvidence] = []
        all_relations: list[RelationEvidence] = []
        registry = SqliteArtifactRegistry(self._db_path)
        store = SqliteGraphEvidenceStore(self._db_path, registry=registry)
        for _, build_id in active_build_snapshot:
            batch = store.get_build_evidence(build_id)
            if batch is None:
                continue
            all_entities.extend(batch.entities)
            all_relations.extend(batch.relations)
        if self._canonicalize_cross_document:
            canonical_graph = canonicalize_graph_evidence(all_entities, all_relations)
            self._entities = canonical_graph.entities
            self._relations = canonical_graph.relationships
            self._canonical_graph = canonical_graph
        else:
            self._entities = all_entities
            self._relations = all_relations
            self._canonical_graph = None
        self._active_build_snapshot = active_build_snapshot

    def _get_entities(self) -> list[EntityEvidence]:
        self._ensure_loaded()
        assert self._entities is not None
        return self._entities

    def _get_relations(self) -> list[RelationEvidence]:
        self._ensure_loaded()
        assert self._relations is not None
        return self._relations

    def _get_canonical_graph(self) -> CanonicalGraphEvidence | None:
        self._ensure_loaded()
        return self._canonical_graph

    def query_entities(
        self,
        entity_texts: list[str],
        top_k: int,
    ) -> list[MiniEntityCandidate]:
        terms = [_normalize(t) for t in entity_texts]
        entities = self._get_entities()

        candidates: list[MiniEntityCandidate] = []
        for entity in entities:
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

        candidates.sort(key=lambda c: (-c.score, c.entity.entity_id))
        return candidates[:top_k]

    def query_relationships(
        self,
        query: str,
        answer_type_keywords: list[str],
        top_k: int,
    ) -> list[MiniRelationshipCandidate]:
        query_terms = [_normalize(w) for w in query.split() if w.strip()]
        keyword_terms = [_normalize(k) for k in answer_type_keywords]
        all_terms = query_terms + keyword_terms

        relations = self._get_relations()
        candidates: list[MiniRelationshipCandidate] = []

        for relation in relations:
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

        candidates.sort(key=lambda c: (-c.score, c.relation.relation_id))
        return candidates[:top_k]

    def expand_paths(
        self,
        seed_entity_ids: list[str],
        seed_relation_ids: list[str],
        max_hops: int,
    ) -> list[TopologyPath]:
        entities = self._get_entities()
        relations = self._get_relations()

        entity_by_id: dict[str, EntityEvidence] = {e.entity_id: e for e in entities}
        relation_by_id: dict[str, RelationEvidence] = {
            r.relation_id: r for r in relations
        }

        adjacency: dict[str, list[RelationEvidence]] = defaultdict(list)
        for rel in relations:
            adjacency[rel.source_entity_id].append(rel)
            adjacency[rel.target_entity_id].append(rel)

        seed_entity_set = set(seed_entity_ids)
        for relation_id in seed_relation_ids:
            relation = relation_by_id.get(relation_id)
            if relation is None:
                continue
            seed_entity_set.add(relation.source_entity_id)
            seed_entity_set.add(relation.target_entity_id)

        visited_entities: set[str] = set()
        visited_relations: set[str] = set()
        paths: list[TopologyPath] = []
        queue: deque[tuple[str, list[str], list[str], int, str]] = deque()
        for entity_id in sorted(seed_entity_set):
            queue.append((entity_id, [entity_id], [], 0, entity_id))

        group_path_counts: dict[str, int] = defaultdict(int)

        while queue:
            (
                current_entity,
                path_entity_ids,
                path_relation_ids,
                hops,
                candidate_group_id,
            ) = queue.popleft()
            if hops >= max_hops:
                continue
            if current_entity in visited_entities:
                continue
            visited_entities.add(current_entity)

            for relation in adjacency.get(current_entity, []):
                if relation.relation_id in visited_relations:
                    continue
                visited_relations.add(relation.relation_id)
                next_entity = (
                    relation.target_entity_id
                    if relation.source_entity_id == current_entity
                    else relation.source_entity_id
                )

                new_entity_ids = path_entity_ids + [next_entity]
                new_relation_ids = path_relation_ids + [relation.relation_id]
                new_hops = hops + 1

                seen_chunks: set[str] = set()
                chunk_ids: list[str] = []
                for entity_id in new_entity_ids:
                    entity = entity_by_id.get(entity_id)
                    if entity is None:
                        continue
                    for chunk_id in entity.source_chunk_ids:
                        if chunk_id not in seen_chunks:
                            seen_chunks.add(chunk_id)
                            chunk_ids.append(chunk_id)
                for relation_id in new_relation_ids:
                    relation_item = relation_by_id.get(relation_id)
                    if relation_item is None:
                        continue
                    for chunk_id in relation_item.source_chunk_ids:
                        if chunk_id not in seen_chunks:
                            seen_chunks.add(chunk_id)
                            chunk_ids.append(chunk_id)

                score = sum(relation_by_id[relation_id].weight for relation_id in new_relation_ids)
                document_id = (
                    relation_by_id[new_relation_ids[0]].document_id
                    if new_relation_ids
                    else ""
                )
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
                        document_id=document_id,
                        entity_ids=new_entity_ids,
                        relation_ids=new_relation_ids,
                        source_chunk_ids=chunk_ids,
                        score=score,
                        candidate_group_id=candidate_group_id,
                        candidate_rank=candidate_rank,
                        metadata={"hop_count": new_hops},
                    )
                )
                queue.append(
                    (
                        next_entity,
                        new_entity_ids,
                        new_relation_ids,
                        new_hops,
                        candidate_group_id,
                    )
                )

        paths.sort(key=lambda p: (-p.score, p.path_id))
        return paths
