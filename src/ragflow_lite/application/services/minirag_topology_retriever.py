from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from ragflow_lite.domain.models import (
    EntityEvidence,
    GraphEvidenceBatch,
    GroundedQuery,
    RelationEvidence,
    RetrievedChunk,
    TopologyPath,
    TopologyRetrievalResult,
)
from ragflow_lite.domain.ports.interfaces import (
    ChunkLookup,
    GraphEvidenceStore,
    QueryGrounder,
    Retriever,
)


class MiniRAGTopologyRetriever:
    def __init__(
        self,
        base_retriever: Retriever,
        query_grounder: QueryGrounder,
        graph_store: GraphEvidenceStore,
        chunk_lookup: ChunkLookup,
        *,
        candidate_multiplier: int = 4,
        max_hops: int = 2,
    ) -> None:
        self.base_retriever = base_retriever
        self.query_grounder = query_grounder
        self.graph_store = graph_store
        self.chunk_lookup = chunk_lookup
        self.candidate_multiplier = candidate_multiplier
        self.max_hops = max_hops

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.retrieve_context(query, top_k).chunks

    def retrieve_context(self, query: str, top_k: int) -> TopologyRetrievalResult:
        candidate_k = max(top_k, top_k * self.candidate_multiplier)
        baseline_chunks = self.base_retriever.retrieve(query, candidate_k)
        grounded_query = self.query_grounder.ground(query)

        if not baseline_chunks or _is_empty_grounding(grounded_query):
            return self._make_result(
                query=query,
                grounded_query=grounded_query,
                chunks=baseline_chunks[:top_k],
                paths=[],
                candidate_count=len(baseline_chunks),
            )

        batches = self._load_candidate_batches(baseline_chunks)
        paths = self._build_paths(batches, grounded_query)
        if not paths:
            return self._make_result(
                query=query,
                grounded_query=grounded_query,
                chunks=baseline_chunks[:top_k],
                paths=[],
                candidate_count=len(baseline_chunks),
            )

        recovered_chunks = self.chunk_lookup.get_chunks(
            _ordered_source_chunk_ids(paths)
        )
        chunks = _merge_chunks(
            recovered_chunks=recovered_chunks,
            baseline_chunks=baseline_chunks,
            paths=paths,
            grounded_query=grounded_query,
            top_k=top_k,
        )
        return self._make_result(
            query=query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=paths,
            candidate_count=len(baseline_chunks),
        )

    def _make_result(
        self,
        *,
        query: str,
        grounded_query: GroundedQuery,
        chunks: list[RetrievedChunk],
        paths: list[TopologyPath],
        candidate_count: int,
    ) -> TopologyRetrievalResult:
        return TopologyRetrievalResult(
            query=query,
            grounded_query=grounded_query,
            chunks=chunks,
            paths=paths,
            metadata={"candidate_count": candidate_count},
        )

    def _load_candidate_batches(
        self,
        baseline_chunks: list[RetrievedChunk],
    ) -> list[GraphEvidenceBatch]:
        document_ids = list(
            dict.fromkeys(chunk.document_id for chunk in baseline_chunks)
        )
        batches: list[GraphEvidenceBatch] = []
        for document_id in document_ids:
            batch = self.graph_store.get_document_evidence(document_id)
            if batch is not None:
                batches.append(batch)
        return batches

    def _build_paths(
        self,
        batches: list[GraphEvidenceBatch],
        grounded_query: GroundedQuery,
    ) -> list[TopologyPath]:
        paths: list[TopologyPath] = []
        terms = _grounding_terms(grounded_query)
        for batch in batches:
            entity_by_id = {entity.entity_id: entity for entity in batch.entities}
            seed_entity_ids = {
                entity.entity_id
                for entity in batch.entities
                if _entity_matches(entity, terms)
            }
            seed_entity_ids.update(_relation_seed_entity_ids(batch.relations, terms))
            if not seed_entity_ids:
                continue
            paths.extend(
                _expand_paths(
                    document_id=batch.document_id,
                    seed_entity_ids=seed_entity_ids,
                    entity_by_id=entity_by_id,
                    relations=batch.relations,
                    max_hops=self.max_hops,
                )
            )
        paths.sort(key=lambda path: path.score, reverse=True)
        return paths


def _is_empty_grounding(grounded_query: GroundedQuery) -> bool:
    return (
        not grounded_query.answer_type_keywords
        and not grounded_query.entities_from_query
    )


def _grounding_terms(grounded_query: GroundedQuery) -> list[str]:
    return [
        _normalize(term)
        for term in [
            *grounded_query.entities_from_query,
            *grounded_query.answer_type_keywords,
        ]
        if term.strip()
    ]


def _entity_matches(entity: EntityEvidence, terms: list[str]) -> bool:
    haystack = _normalize(
        " ".join([entity.name, entity.entity_type, entity.description])
    )
    return any(term in haystack for term in terms)


def _relation_seed_entity_ids(
    relations: list[RelationEvidence],
    terms: list[str],
) -> set[str]:
    seeds: set[str] = set()
    for relation in relations:
        haystack = _normalize(
            " ".join(
                [
                    relation.source_entity_name,
                    relation.target_entity_name,
                    relation.description,
                    " ".join(relation.keywords),
                ]
            )
        )
        if any(term in haystack for term in terms):
            seeds.add(relation.source_entity_id)
            seeds.add(relation.target_entity_id)
    return seeds


def _expand_paths(
    *,
    document_id: str,
    seed_entity_ids: set[str],
    entity_by_id: dict[str, EntityEvidence],
    relations: list[RelationEvidence],
    max_hops: int,
) -> list[TopologyPath]:
    adjacency: dict[str, list[RelationEvidence]] = defaultdict(list)
    for relation in relations:
        adjacency[relation.source_entity_id].append(relation)
        adjacency[relation.target_entity_id].append(relation)

    paths: list[TopologyPath] = []
    seen_relation_ids: set[str] = set()
    frontier = set(seed_entity_ids)
    visited = set(seed_entity_ids)
    for hop in range(max_hops):
        next_frontier: set[str] = set()
        for entity_id in frontier:
            for relation in adjacency.get(entity_id, []):
                if relation.relation_id in seen_relation_ids:
                    continue
                seen_relation_ids.add(relation.relation_id)
                connected_ids = [
                    relation.source_entity_id,
                    relation.target_entity_id,
                ]
                source_chunk_ids = _dedupe(
                    [
                        *relation.source_chunk_ids,
                        *(
                            entity_by_id[relation.source_entity_id].source_chunk_ids
                            if relation.source_entity_id in entity_by_id
                            else []
                        ),
                        *(
                            entity_by_id[relation.target_entity_id].source_chunk_ids
                            if relation.target_entity_id in entity_by_id
                            else []
                        ),
                    ]
                )
                paths.append(
                    TopologyPath(
                        path_id=_path_id(document_id, relation.relation_id),
                        document_id=document_id,
                        entity_ids=_dedupe(connected_ids),
                        relation_ids=[relation.relation_id],
                        source_chunk_ids=source_chunk_ids,
                        score=relation.weight + (max_hops - hop) * 0.1,
                        metadata={"hop_count": hop + 1},
                    )
                )
                for connected_id in connected_ids:
                    if connected_id not in visited:
                        next_frontier.add(connected_id)
                        visited.add(connected_id)
        frontier = next_frontier
        if not frontier:
            break
    return paths


def _merge_chunks(
    *,
    recovered_chunks: list[RetrievedChunk],
    baseline_chunks: list[RetrievedChunk],
    paths: list[TopologyPath],
    grounded_query: GroundedQuery,
    top_k: int,
) -> list[RetrievedChunk]:
    path_ids_by_chunk: dict[str, list[str]] = defaultdict(list)
    relation_ids_by_chunk: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        for chunk_id in path.source_chunk_ids:
            path_ids_by_chunk[chunk_id].append(path.path_id)
            relation_ids_by_chunk[chunk_id].extend(path.relation_ids)

    ordered: list[RetrievedChunk] = []
    seen: set[str] = set()
    for chunk in [*recovered_chunks, *baseline_chunks]:
        if chunk.chunk_id in seen:
            continue
        metadata = dict(chunk.metadata)
        if chunk.chunk_id in path_ids_by_chunk:
            metadata.update(
                {
                    "retrieval_mode": "minirag_topology",
                    "grounded_entities": grounded_query.entities_from_query,
                    "answer_type_keywords": grounded_query.answer_type_keywords,
                    "topology_path_ids": _dedupe(path_ids_by_chunk[chunk.chunk_id]),
                    "topology_relation_ids": _dedupe(
                        relation_ids_by_chunk[chunk.chunk_id]
                    ),
                    "topology_source": "graph_evidence",
                }
            )
        ordered.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.text,
                score=chunk.score,
                metadata=metadata,
            )
        )
        seen.add(chunk.chunk_id)
        if len(ordered) == top_k:
            break
    return ordered


def _ordered_source_chunk_ids(paths: list[TopologyPath]) -> list[str]:
    chunk_ids: list[str] = []
    for path in paths:
        chunk_ids.extend(path.source_chunk_ids)
    return _dedupe(chunk_ids)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _path_id(document_id: str, relation_id: str) -> str:
    digest = hashlib.sha256(f"{document_id}:{relation_id}".encode()).hexdigest()
    return f"path_{digest[:16]}"
