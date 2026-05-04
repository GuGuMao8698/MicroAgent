from __future__ import annotations

from ragflow_lite.domain.models import (
    EvidenceItem,
    EvidencePackage,
    EvidenceProvenance,
    GraphFirstSource,
    GraphFirstSourceSelection,
    TopologyRetrievalResult,
)


class EvidencePackageBuilder:
    def build(self, result: TopologyRetrievalResult) -> EvidencePackage:
        # 按 chunk_id 建立 source 查找表，用于后续元数据注入
        source_by_chunk = _source_by_chunk(result.source_selection)

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

            # 合并 chunk 原始 metadata 与 source selection 元数据
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
                metadata={
                    **dict(chunk.metadata),
                    **_source_metadata(source_by_chunk.get(cid)),
                },
            )
            seen[cid] = len(items)
            items.append(item)
            order += 1

        metadata = dict(result.metadata)
        metadata["evidence_count"] = len(items)

        # 若存在 source selection 摘要，注入到 package 级 metadata
        selection_summary = _selection_summary(result.source_selection)
        if selection_summary is not None:
            metadata["source_selection"] = selection_summary

        return EvidencePackage(
            query=result.query,
            grounded_query=result.grounded_query,
            items=items,
            metadata=metadata,
        )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _source_by_chunk(
    selection: GraphFirstSourceSelection | None,
) -> dict[str, GraphFirstSource]:
    """将 source selection 列表按 chunk_id 建立查找表。"""
    if selection is None:
        return {}
    return {source.chunk_id: source for source in selection.sources}


def _source_metadata(source: GraphFirstSource | None) -> dict[str, object]:
    """从单个 GraphFirstSource 提取需要注入 EvidenceItem 的元数据字段。"""
    if source is None:
        return {}
    return {
        "source_selection_rank": source.rank,
        "selected_for_answer": source.selected_for_answer,
        "selected_for_discourse": source.selected_for_discourse,
        "selection_reason": source.selection_reason,
        "source_score_components": dict(source.score_components),
        "supporting_entity_ids": list(source.supporting_entity_ids),
        "supporting_relation_ids": list(source.supporting_relation_ids),
        "supporting_path_ids": list(source.supporting_path_ids),
        "auxiliary_chunk_hit": source.auxiliary_chunk_hit,
    }


def _selection_summary(
    selection: GraphFirstSourceSelection | None,
) -> dict[str, object] | None:
    """生成 source selection 的摘要信息，用于注入 EvidencePackage 级 metadata。"""
    if selection is None:
        return None
    return {
        "final_context_k": selection.final_context_k,
        "discourse_selection_k": selection.discourse_selection_k,
        "context_token_budget": selection.context_token_budget,
        "selected_answer_chunk_ids": [
            source.chunk_id
            for source in selection.sources
            if source.selected_for_answer
        ],
        "selected_discourse_chunk_ids": [
            source.chunk_id
            for source in selection.sources
            if source.selected_for_discourse
        ],
        "omitted_source_count": selection.omitted_source_count,
        "fallback_reason": selection.fallback_reason,
    }
