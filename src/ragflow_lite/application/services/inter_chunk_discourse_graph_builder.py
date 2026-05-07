from __future__ import annotations

from ragflow_lite.domain.models import (
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
        for supplemental in supplemental_items:
            for answer in answer_items:
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
