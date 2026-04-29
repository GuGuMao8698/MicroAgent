from __future__ import annotations

import hashlib
import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    Chunk,
    EntityEvidence,
    GraphEvidenceBatch,
    RelationEvidence,
)

GRAPH_SOURCE_SEPARATOR = "|"

EVIDENCE_INSTRUCTIONS = """Extract minimal graph evidence from the provided chunks.

Return exactly one JSON object with this shape:
{
  "entities": [
    {
      "name": "entity name",
      "entity_type": "concept|person|organization|place|other",
      "description": "short grounded description",
      "source_chunk_ids": ["chunk_id"]
    }
  ],
  "relations": [
    {
      "source_entity_name": "entity name",
      "target_entity_name": "entity name",
      "description": "short grounded relation",
      "keywords": ["keyword"],
      "weight": 1.0,
      "source_chunk_ids": ["chunk_id"]
    }
  ]
}

Rules:
- Use only facts visible in the chunks.
- Every entity and relation must cite at least one provided chunk_id.
- Do not invent chunk IDs.
- Do not return markdown or prose outside the JSON object.
"""


class OpenAIResponsesEvidenceExtractor:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str,
        store: bool,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.store = store
        self.client = client or self._build_client(api_key, base_url)

    def extract(self, chunks: list[Chunk]) -> GraphEvidenceBatch:
        if not chunks:
            raise ProcessingError("Graph evidence extraction requires chunks.")
        document_ids = {chunk.document_id for chunk in chunks}
        if len(document_ids) != 1:
            raise ProcessingError("Graph evidence extraction requires one document.")
        document_id = next(iter(document_ids))
        allowed_chunk_ids = {chunk.chunk_id for chunk in chunks}
        response = self.client.responses.create(
            model=self.model,
            instructions=EVIDENCE_INSTRUCTIONS,
            input=self._build_input(chunks),
            reasoning={"effort": self.reasoning_effort},
            store=self.store,
        )
        payload = self._load_payload(response.output_text)
        entities = self._load_entities(document_id, payload, allowed_chunk_ids)
        relations = self._load_relations(
            document_id, payload, entities, allowed_chunk_ids
        )
        return GraphEvidenceBatch(
            document_id=document_id,
            entities=entities,
            relations=relations,
            metadata={"extractor": "openai_responses", "model": self.model},
        )

    def _build_input(self, chunks: list[Chunk]) -> str:
        sections = []
        for chunk in chunks:
            sections.append(
                "\n".join(
                    [
                        f"chunk_id: {chunk.chunk_id}",
                        f"document_id: {chunk.document_id}",
                        f"text: {chunk.text}",
                    ]
                )
            )
        return "\n\n---\n\n".join(sections)

    def _load_payload(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProcessingError(
                "Graph evidence extractor returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ProcessingError("Graph evidence extractor must return a JSON object.")
        if not isinstance(payload.get("entities"), list):
            raise ProcessingError("Graph evidence extractor output missing entities.")
        if not isinstance(payload.get("relations"), list):
            raise ProcessingError("Graph evidence extractor output missing relations.")
        return payload

    def _load_entities(
        self,
        document_id: str,
        payload: dict[str, Any],
        allowed_chunk_ids: set[str],
    ) -> list[EntityEvidence]:
        entities: list[EntityEvidence] = []
        seen_names: set[str] = set()
        for raw in payload["entities"]:
            if not isinstance(raw, dict):
                raise ProcessingError("Graph entity must be a JSON object.")
            name = _required_text(raw, "name")
            normalized_name = _normalize_name(name)
            if normalized_name in seen_names:
                continue
            entity_type = _required_text(raw, "entity_type")
            description = _required_text(raw, "description")
            source_chunk_ids = _source_chunk_ids(raw, allowed_chunk_ids)
            entity_id = _stable_id("entity", document_id, normalized_name)
            entities.append(
                EntityEvidence(
                    entity_id=entity_id,
                    document_id=document_id,
                    name=name.strip(),
                    entity_type=entity_type.strip(),
                    description=description.strip(),
                    source_chunk_ids=source_chunk_ids,
                    metadata=_source_metadata(source_chunk_ids),
                )
            )
            seen_names.add(normalized_name)
        return entities

    def _load_relations(
        self,
        document_id: str,
        payload: dict[str, Any],
        entities: list[EntityEvidence],
        allowed_chunk_ids: set[str],
    ) -> list[RelationEvidence]:
        entities_by_name = {_normalize_name(entity.name): entity for entity in entities}
        relations: list[RelationEvidence] = []
        for raw in payload["relations"]:
            if not isinstance(raw, dict):
                raise ProcessingError("Graph relation must be a JSON object.")
            source_entity_name = _required_text(raw, "source_entity_name")
            target_entity_name = _required_text(raw, "target_entity_name")
            source_entity = entities_by_name.get(_normalize_name(source_entity_name))
            target_entity = entities_by_name.get(_normalize_name(target_entity_name))
            if source_entity is None or target_entity is None:
                raise ProcessingError("Graph relation references an unknown entity.")
            description = _required_text(raw, "description")
            keywords = _keywords(raw)
            weight = _weight(raw)
            source_chunk_ids = _source_chunk_ids(raw, allowed_chunk_ids)
            relation_id = _stable_id(
                "relation",
                document_id,
                source_entity.entity_id,
                target_entity.entity_id,
                description.strip().lower(),
            )
            relations.append(
                RelationEvidence(
                    relation_id=relation_id,
                    document_id=document_id,
                    source_entity_id=source_entity.entity_id,
                    target_entity_id=target_entity.entity_id,
                    source_entity_name=source_entity.name,
                    target_entity_name=target_entity.name,
                    description=description.strip(),
                    keywords=keywords,
                    weight=weight,
                    source_chunk_ids=source_chunk_ids,
                    metadata=_source_metadata(source_chunk_ids),
                )
            )
        return relations

    @staticmethod
    def _build_client(api_key: str, base_url: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url)


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProcessingError(
            f"Graph evidence field '{key}' must be a non-empty string."
        )
    return value


def _source_chunk_ids(raw: dict[str, Any], allowed_chunk_ids: set[str]) -> list[str]:
    value = raw.get("source_chunk_ids")
    if not isinstance(value, list) or not value:
        raise ProcessingError("Graph evidence must include source_chunk_ids.")
    chunk_ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ProcessingError("Graph evidence source chunk IDs must be strings.")
        chunk_id = item.strip()
        if chunk_id not in allowed_chunk_ids:
            raise ProcessingError(
                f"Graph evidence references unknown source chunk: {chunk_id}"
            )
        if chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _keywords(raw: dict[str, Any]) -> list[str]:
    value = raw.get("keywords", [])
    if not isinstance(value, list):
        raise ProcessingError("Graph relation keywords must be a list.")
    keywords: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            keywords.append(item.strip())
    return keywords


def _weight(raw: dict[str, Any]) -> float:
    value = raw.get("weight", 1.0)
    if not isinstance(value, (int, float)):
        raise ProcessingError("Graph relation weight must be numeric.")
    return float(value)


def _source_metadata(source_chunk_ids: list[str]) -> dict[str, str]:
    return {"source_id": GRAPH_SOURCE_SEPARATOR.join(source_chunk_ids)}


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"
