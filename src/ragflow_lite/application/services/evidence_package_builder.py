from __future__ import annotations

from ragflow_lite.domain.models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    TopologyRetrievalResult,
)


class EvidencePackageBuilder:
    def build(self, result: TopologyRetrievalResult) -> EvidencePackage:
        # Path refs to chunks not in result.chunks are silently ignored;
        # TopologyRetrievalResult guarantees all source_chunk_ids are present.
        path_ids_by_chunk: dict[str, list[str]] = {}
        relation_ids_by_chunk: dict[str, list[str]] = {}
        for path in result.paths:
            for chunk_id in path.source_chunk_ids:
                path_ids_by_chunk.setdefault(chunk_id, []).append(path.path_id)
                relation_ids_by_chunk.setdefault(chunk_id, []).extend(path.relation_ids)

        seen: dict[str, int] = {}
        items: list[EvidenceItem] = []
        order = 0
        for chunk in result.chunks:
            cid = chunk.chunk_id
            if cid in seen:
                existing = items[seen[cid]]
                if "baseline_retrieval" not in existing.retained_reasons:
                    existing.retained_reasons.append("baseline_retrieval")
                if cid in path_ids_by_chunk:
                    existing.topology_path_ids = _dedupe(
                        [*existing.topology_path_ids, *path_ids_by_chunk[cid]]
                    )
                    existing.topology_relation_ids = _dedupe(
                        [
                            *existing.topology_relation_ids,
                            *relation_ids_by_chunk.get(cid, []),
                        ]
                    )
                continue

            filename = chunk.metadata.get("filename")
            if not isinstance(filename, str):
                filename = None
            file_type = chunk.metadata.get("file_type")
            if not isinstance(file_type, str):
                file_type = None
            chunk_index = chunk.metadata.get("_chunk_index")
            if not isinstance(chunk_index, int):
                chunk_index = None

            provenance = EvidenceProvenance(
                document_id=chunk.document_id,
                filename=filename,
                file_type=file_type,
                chunk_index=chunk_index,
            )

            reasons: list[str] = []
            path_ids: list[str] = []
            relation_ids: list[str] = []
            if cid in path_ids_by_chunk:
                reasons.append("topology_path")
                path_ids = _dedupe(path_ids_by_chunk[cid])
                relation_ids = _dedupe(relation_ids_by_chunk.get(cid, []))
            else:
                reasons.append("baseline_retrieval")

            item = EvidenceItem(
                canonical_chunk_id=cid,
                text=chunk.text,
                score=chunk.score,
                order=order,
                provenance=provenance,
                retained_reasons=reasons,
                grounded_entities=list(result.grounded_query.entities_from_query),
                answer_type_keywords=list(result.grounded_query.answer_type_keywords),
                topology_path_ids=path_ids,
                topology_relation_ids=relation_ids,
                metadata=dict(chunk.metadata),
            )
            seen[cid] = len(items)
            items.append(item)
            order += 1

        metadata = dict(result.metadata)
        metadata["evidence_count"] = len(items)
        return EvidencePackage(
            query=result.query,
            grounded_query=result.grounded_query,
            items=items,
            metadata=metadata,
        )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
