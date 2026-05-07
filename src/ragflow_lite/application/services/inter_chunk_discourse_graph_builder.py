from __future__ import annotations

from ragflow_lite.domain.models import (
    EvidenceItem,
    InterChunkDiscourseGraph,
    InterChunkDiscourseRelation,
    IntraChunkDiscoursePackage,
)


class DeterministicInterChunkDiscourseGraphBuilder:
    """Build a sparse chunk-level graph from existing MiniRAG metadata."""

    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        items = [
            item
            for item in package.evidence_package.items
            if item.metadata.get("selected_for_discourse") is True
        ]
        chunk_ids = [item.canonical_chunk_id for item in items]
        answer_items = [
            item for item in items if item.metadata.get("selected_for_answer") is True
        ]
        supplemental_items = [
            item
            for item in items
            if item.metadata.get("supplemental_discourse") is True
        ]

        relations: list[InterChunkDiscourseRelation] = []
        chunk_id_set = set(chunk_ids)
        for supplemental in supplemental_items:
            explicit = _explicit_relation(supplemental, chunk_id_set)
            if explicit is not None:
                relations.append(explicit)
                continue
            for answer in answer_items:
                if supplemental.canonical_chunk_id == answer.canonical_chunk_id:
                    continue
                shared_relation_ids = _shared(
                    supplemental.topology_relation_ids,
                    answer.topology_relation_ids,
                )
                if not shared_relation_ids:
                    continue
                relations.append(
                    InterChunkDiscourseRelation(
                        source_chunk_id=supplemental.canonical_chunk_id,
                        target_chunk_id=answer.canonical_chunk_id,
                        relation_type="qualifies",
                        rationale=(
                            "Supplemental discourse evidence shares topology "
                            "relations with an answer chunk."
                        ),
                        confidence=0.6,
                        metadata={
                            "shared_topology_relation_ids": shared_relation_ids,
                            "source": "shared_topology_relation_ids",
                        },
                    )
                )

        return InterChunkDiscourseGraph(
            query=package.query,
            chunk_ids=chunk_ids,
            relations=relations,
            metadata={
                "builder": "deterministic_inter_chunk_discourse",
                "evidence_count": len(items),
                "relation_count": len(relations),
            },
        )


def _shared(left: list[str], right: list[str]) -> list[str]:
    right_set = set(right)
    return [value for value in left if value in right_set]


_RELATION_TYPES = {
    "qualifies",
    "supports",
    "background_for",
    "elaborates",
    "example_of",
    "contradicts",
}


def _explicit_relation(
    supplemental: EvidenceItem,
    chunk_ids: set[str],
) -> InterChunkDiscourseRelation | None:
    relation_type = supplemental.metadata.get("inter_chunk_relation_type")
    target_chunk_id = supplemental.metadata.get("inter_chunk_target_chunk_id")
    if not isinstance(relation_type, str) or relation_type not in _RELATION_TYPES:
        return None
    if not isinstance(target_chunk_id, str) or target_chunk_id not in chunk_ids:
        return None
    if target_chunk_id == supplemental.canonical_chunk_id:
        return None
    rationale = supplemental.metadata.get("inter_chunk_relation_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "Explicit metadata marks an inter-chunk discourse relation."
    confidence = supplemental.metadata.get("inter_chunk_relation_confidence", 0.7)
    if not isinstance(confidence, (int, float)):
        confidence = 0.7
    confidence = max(0.0, min(1.0, float(confidence)))
    return InterChunkDiscourseRelation(
        source_chunk_id=supplemental.canonical_chunk_id,
        target_chunk_id=target_chunk_id,
        relation_type=relation_type,
        rationale=rationale,
        confidence=confidence,
        metadata={"source": "explicit_inter_chunk_relation_metadata"},
    )
