from __future__ import annotations

import hashlib
import json
from typing import Any

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ChunkDiscourseStructure,
    DiscourseUnit,
    EvidenceItem,
    EvidencePackage,
    IntraChunkDiscoursePackage,
    IntraChunkDiscourseRelation,
)
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    StructurerAttemptState,
    build_validation_repair_messages,
    is_timeout_error,
)

# --- Functional RST projection constants ---

_RST_RELATION_PROJECTIONS: frozenset[str] = frozenset(
    {
        "supports",
        "elaborates",
        "defines",
        "qualifies",
        "contrasts",
        "causes",
        "conditions",
        "temporal_next",
        "example_of",
    }
)

_NUCLEARITY_VALUES: frozenset[str] = frozenset({"nucleus", "satellite", "joint"})

_PLANNING_ROLE_ALIASES: dict[str, str] = {
    # claim
    "claim": "claim",
    "main": "claim",
    "thesis": "claim",
    # evidence
    "evidence": "evidence",
    "data": "evidence",
    "fact": "evidence",
    # definition
    "definition": "definition",
    "term": "definition",
    # condition
    "condition": "condition",
    "prerequisite": "condition",
    # qualification
    "qualification": "qualification",
    "caveat": "qualification",
    "limitation": "qualification",
    # contrast
    "contrast": "contrast",
    "opposition": "contrast",
    "counter": "contrast",
    # procedure
    "procedure": "procedure",
    "step": "procedure",
    "method": "procedure",
}

_RST_NORMALIZATION_MAP: dict[str, str] = {
    # supports
    "supports": "supports",
    "support": "supports",
    # elaborates
    "elaborates": "elaborates",
    "elaboration": "elaborates",
    "elaborate": "elaborates",
    # defines
    "defines": "defines",
    "definition": "defines",
    "define": "defines",
    # qualifies
    "qualifies": "qualifies",
    "qualification": "qualifies",
    "qualify": "qualifies",
    # contrasts
    "contrasts": "contrasts",
    "contrast": "contrasts",
    "contrast_with": "contrasts",
    # causes
    "causes": "causes",
    "cause": "causes",
    "causation": "causes",
    # conditions
    "conditions": "conditions",
    "condition": "conditions",
    # temporal_next
    "temporal_next": "temporal_next",
    "sequence": "temporal_next",
    "sequences": "temporal_next",
    "next": "temporal_next",
    "sequencing": "temporal_next",
    # example_of
    "example_of": "example_of",
    "example": "example_of",
    "exemplifies": "example_of",
}

DISCOURSE_INSTRUCTIONS = """Extract minimal intra-chunk discourse structure.

Return exactly one JSON object with this shape:
{
  "chunks": [
    {
      "canonical_chunk_id": "chunk_id",
      "units": [
        {
          "text": "grounded unit text",
          "role": "main|support|detail|definition|condition|contrast|background",
          "start_char": 0,
          "end_char": 10
        }
      ],
      "relations": [
        {
          "source_unit_index": 0,
          "target_unit_index": 1,
          "relation_type": "supports|elaborates|qualifies|contrasts|causes|sequences|defines",
          "weight": 1.0
        }
      ],
      "main_unit_indexes": [0],
      "supporting_unit_indexes": [1]
    }
  ]
}

Rules:
- Use only facts visible in the provided chunk text.
- Only return structures for provided canonical_chunk_id values.
- Unit indexes are zero-based within each chunk.
- Do not invent text that is not grounded in the chunk.
- Do not return markdown or prose outside the JSON object.
"""


class DeepSeekChatIntraChunkDiscourseExtractor:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        client: Any | None = None,
        max_chunks: int | None = None,
        enabled: bool = True,
        *,
        timeout_seconds: float = 90.0,
        max_attempts: int = 2,
    ) -> None:
        # Contract reviewed 2026-05-08T12:56:51+08:00.
        # default RST extraction consumes the retriever-selected discourse window;
        # any local cap must be explicit and observable in metadata.
        if max_chunks is not None and max_chunks < 1:
            raise ProcessingError("Intra-chunk discourse max_chunks must be positive.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_chunks = max_chunks
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def extract(self, evidence_package: EvidencePackage) -> IntraChunkDiscoursePackage:
        if not self.enabled:
            return self._empty_package(evidence_package, "disabled")

        selected_items, selection_source = self._select_items(evidence_package.items)
        if not selected_items:
            return self._empty_package(evidence_package, "empty")

        selected_ids = [item.canonical_chunk_id for item in selected_items]
        selected_id_set = set(selected_ids)
        skipped_ids = [
            item.canonical_chunk_id
            for item in evidence_package.items
            if item.canonical_chunk_id not in selected_id_set
        ]

        client = self.client or self._build_client(self.api_key, self.base_url)
        input_text = self._build_input(evidence_package, selected_items)
        instructions = DISCOURSE_INSTRUCTIONS
        attempt_state = StructurerAttemptState(
            stage="rst_extraction",
            max_attempts=self.max_attempts,
        )
        # None = use complete_json (fresh request); list = use complete_messages_json (repair)
        repair_messages: list[dict[str, str]] | None = None

        for attempt_index in range(self.max_attempts):
            try:
                if repair_messages is None:
                    raw_json = client.complete_json(
                        instructions=instructions,
                        input_text=input_text,
                        timeout_seconds=self.timeout_seconds,
                        max_retries=0,
                    )
                else:
                    raw_json = client.complete_messages_json(
                        repair_messages,
                        timeout_seconds=self.timeout_seconds,
                        max_retries=0,
                    )
            except Exception as exc:
                if is_timeout_error(exc):
                    attempt_state.record_failure("timeout", str(exc) or "timeout")
                    if attempt_index >= self.max_attempts - 1:
                        raise attempt_state.exhausted_error() from exc
                    repair_messages = None
                    continue
                raise ProcessingError(
                    f"DeepSeek discourse extractor call failed: {exc}"
                ) from exc

            try:
                payload = self._load_payload(raw_json)
                structures = self._load_structures(payload, selected_items)
            except ProcessingError as exc:
                attempt_state.record_failure("validation_error", str(exc))
                if attempt_index >= self.max_attempts - 1:
                    raise attempt_state.exhausted_error() from exc
                repair_messages = build_validation_repair_messages(
                    instructions=instructions,
                    input_text=input_text,
                    invalid_output=raw_json,
                    validation_error=str(exc),
                )
                continue

            attempt_state.record_success_attempt()
            return IntraChunkDiscoursePackage(
                query=evidence_package.query,
                evidence_package=evidence_package,
                structures=structures,
                metadata={
                    "extractor": "deepseek_chat_intra_chunk_discourse",
                    "model": self.model,
                    "selected_evidence_count": len(selected_items),
                    "structure_count": len(structures),
                    "status": "ok",
                    "selection_source": selection_source,
                    "max_chunks": self.max_chunks,
                    "selected_chunk_ids": selected_ids,
                    "skipped_chunk_ids": skipped_ids,
                },
            )

        raise attempt_state.exhausted_error()

    def _select_items(
        self, items: list[EvidenceItem]
    ) -> tuple[list[EvidenceItem], str]:
        """Select discourse-visible evidence first, with no default local cap."""
        explicit = [
            item
            for item in items
            if item.metadata.get("selected_for_discourse") is True
        ]
        source_items = explicit if explicit else items
        selection_source = "source_selection" if explicit else "prefix"

        selected: list[EvidenceItem] = []
        seen: set[str] = set()
        for item in source_items:
            if item.canonical_chunk_id in seen:
                continue
            selected.append(item)
            seen.add(item.canonical_chunk_id)
            if self.max_chunks is not None and len(selected) >= self.max_chunks:
                break

        return selected, selection_source

    def _empty_package(
        self,
        evidence_package: EvidencePackage,
        status: str,
    ) -> IntraChunkDiscoursePackage:
        return IntraChunkDiscoursePackage(
            query=evidence_package.query,
            evidence_package=evidence_package,
            structures=[],
            metadata={
                "extractor": "deepseek_chat_intra_chunk_discourse",
                "model": self.model,
                "selected_evidence_count": 0,
                "structure_count": 0,
                "status": status,
                "selection_source": "none",
                "max_chunks": self.max_chunks,
                "selected_chunk_ids": [],
                "skipped_chunk_ids": [],
            },
        )

    def _build_input(
        self,
        evidence_package: EvidencePackage,
        items: list[EvidenceItem],
    ) -> str:
        sections = [f"query: {evidence_package.query}"]
        for item in items:
            sections.append(
                "\n".join(
                    [
                        f"canonical_chunk_id: {item.canonical_chunk_id}",
                        f"document_id: {item.provenance.document_id}",
                        f"order: {item.order}",
                        f"text: {item.text}",
                    ]
                )
            )
        return "\n\n---\n\n".join(sections)

    def _load_payload(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProcessingError(
                "Intra-chunk discourse extractor returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise ProcessingError(
                "Intra-chunk discourse extractor must return a JSON object."
            )
        if not isinstance(payload.get("chunks"), list):
            raise ProcessingError(
                "Intra-chunk discourse extractor output missing chunks."
            )
        return payload

    def _load_structures(
        self,
        payload: dict[str, Any],
        items: list[EvidenceItem],
    ) -> list[ChunkDiscourseStructure]:
        items_by_id = {item.canonical_chunk_id: item for item in items}
        expected_ids = set(items_by_id)
        seen_ids: set[str] = set()
        structures_by_id: dict[str, ChunkDiscourseStructure] = {}

        for raw in payload["chunks"]:
            if not isinstance(raw, dict):
                raise ProcessingError("Discourse chunk must be a JSON object.")
            canonical_chunk_id = _required_text(raw, "canonical_chunk_id")
            if canonical_chunk_id not in expected_ids:
                raise ProcessingError(
                    "Discourse extractor returned unknown canonical_chunk_id "
                    f"{canonical_chunk_id!r}."
                )
            if canonical_chunk_id in seen_ids:
                raise ProcessingError(
                    "Discourse extractor returned duplicate canonical_chunk_id "
                    f"{canonical_chunk_id!r}."
                )
            seen_ids.add(canonical_chunk_id)
            item = items_by_id[canonical_chunk_id]
            structures_by_id[canonical_chunk_id] = self._load_structure(raw, item)

        missing_ids = expected_ids - seen_ids
        if missing_ids:
            raise ProcessingError(
                "Discourse extractor missing structures for selected chunks: "
                f"{sorted(missing_ids)!r}."
            )

        return [structures_by_id[item.canonical_chunk_id] for item in items]

    def _load_structure(
        self,
        raw: dict[str, Any],
        item: EvidenceItem,
    ) -> ChunkDiscourseStructure:
        raw_units = raw.get("units")
        raw_relations = raw.get("relations", [])
        if not isinstance(raw_units, list):
            raise ProcessingError("Discourse chunk output missing units.")
        if not isinstance(raw_relations, list):
            raise ProcessingError("Discourse chunk relations must be a list.")

        units = [
            self._load_unit(item, raw_unit, order)
            for order, raw_unit in enumerate(raw_units)
        ]
        relations = [
            self._load_relation(item, units, raw_relation)
            for raw_relation in raw_relations
        ]
        main_unit_ids = _unit_ids_from_indexes(raw, "main_unit_indexes", units)
        supporting_unit_ids = _unit_ids_from_indexes(
            raw, "supporting_unit_indexes", units
        )
        main_id_set = set(main_unit_ids)
        supporting_id_set = set(supporting_unit_ids)

        self._enrich_units(units, relations, main_id_set, supporting_id_set)

        return ChunkDiscourseStructure(
            canonical_chunk_id=item.canonical_chunk_id,
            document_id=item.provenance.document_id,
            units=units,
            relations=relations,
            main_unit_ids=main_unit_ids,
            supporting_unit_ids=supporting_unit_ids,
            metadata={
                "evidence_order": item.order,
                "source_score": item.score,
                "retained_reasons": list(item.retained_reasons),
            },
        )

    @staticmethod
    def _enrich_units(
        units: list[DiscourseUnit],
        relations: list[IntraChunkDiscourseRelation],
        main_id_set: set[str],
        supporting_id_set: set[str],
    ) -> None:
        rst_by_target: dict[str, str] = {}
        for rel in relations:
            if rel.target_unit_id not in rst_by_target:
                normalized = _normalize_rst_relation(rel.relation_type)
                if normalized is not None:
                    rst_by_target[rel.target_unit_id] = normalized

        for unit in units:
            in_main = unit.unit_id in main_id_set
            in_supporting = unit.unit_id in supporting_id_set
            if in_main and in_supporting:
                unit.nuclearity = "joint"
            elif in_main:
                unit.nuclearity = "nucleus"
            elif in_supporting:
                unit.nuclearity = "satellite"

            unit.rst_relation = rst_by_target.get(unit.unit_id)
            unit.planning_role = _map_planning_role(unit.role)

    def _load_unit(
        self,
        item: EvidenceItem,
        raw: Any,
        order: int,
    ) -> DiscourseUnit:
        if not isinstance(raw, dict):
            raise ProcessingError("Discourse unit must be a JSON object.")
        text = _required_text(raw, "text")
        role = _required_text(raw, "role")
        start_char = _optional_int(raw, "start_char")
        end_char = _optional_int(raw, "end_char")
        if (start_char is None) != (end_char is None):
            raise ProcessingError("Discourse unit span must include start and end.")
        if start_char is not None and end_char is not None:
            if not 0 <= start_char < end_char <= len(item.text):
                raise ProcessingError("Discourse unit span is outside chunk text.")
        return DiscourseUnit(
            unit_id=_stable_id(
                "unit",
                item.provenance.document_id,
                item.canonical_chunk_id,
                str(order),
                _normalize_text(text),
            ),
            canonical_chunk_id=item.canonical_chunk_id,
            text=text.strip(),
            order=order,
            role=_normalize_label(role),
            start_char=start_char,
            end_char=end_char,
        )

    def _load_relation(
        self,
        item: EvidenceItem,
        units: list[DiscourseUnit],
        raw: Any,
    ) -> IntraChunkDiscourseRelation:
        if not isinstance(raw, dict):
            raise ProcessingError("Discourse relation must be a JSON object.")
        source_index = _required_int(raw, "source_unit_index")
        target_index = _required_int(raw, "target_unit_index")
        if not 0 <= source_index < len(units):
            raise ProcessingError("Discourse relation source index is invalid.")
        if not 0 <= target_index < len(units):
            raise ProcessingError("Discourse relation target index is invalid.")
        relation_type = _normalize_label(_required_text(raw, "relation_type"))
        weight = _weight(raw)
        source = units[source_index]
        target = units[target_index]
        return IntraChunkDiscourseRelation(
            relation_id=_stable_id(
                "discourse_relation",
                item.provenance.document_id,
                item.canonical_chunk_id,
                source.unit_id,
                target.unit_id,
                relation_type.lower(),
            ),
            canonical_chunk_id=item.canonical_chunk_id,
            source_unit_id=source.unit_id,
            target_unit_id=target.unit_id,
            relation_type=relation_type,
            weight=weight,
        )

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import (
            DEEPSEEK_DISABLED_THINKING_EXTRA_BODY,
            DeepSeekChatCompletionsClient,
        )

        if api_key is None or base_url is None:
            raise ProcessingError(
                "DeepSeek discourse extractor requires api_key and base_url "
                "when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            extra_body=DEEPSEEK_DISABLED_THINKING_EXTRA_BODY,
        )


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProcessingError(f"Discourse field '{key}' must be a non-empty string.")
    return value


def _required_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if type(value) is not int:
        raise ProcessingError(f"Discourse field '{key}' must be an integer.")
    return value


def _optional_int(raw: dict[str, Any], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if type(value) is not int:
        raise ProcessingError(f"Discourse field '{key}' must be an integer.")
    return value


def _unit_ids_from_indexes(
    raw: dict[str, Any],
    key: str,
    units: list[DiscourseUnit],
) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ProcessingError(f"Discourse field '{key}' must be a list.")
    unit_ids: list[str] = []
    for item in value:
        if type(item) is not int or not 0 <= item < len(units):
            raise ProcessingError(f"Discourse field '{key}' contains invalid index.")
        unit_id = units[item].unit_id
        if unit_id not in unit_ids:
            unit_ids.append(unit_id)
    return unit_ids


def _weight(raw: dict[str, Any]) -> float:
    value = raw.get("weight", 1.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProcessingError("Discourse relation weight must be numeric.")
    return float(value)


def _normalize_label(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_rst_relation(relation_type: str) -> str | None:
    key = relation_type.strip().lower()
    return _RST_NORMALIZATION_MAP.get(key)


def _map_planning_role(role: str) -> str:
    key = role.strip().lower()
    return _PLANNING_ROLE_ALIASES.get(key, "context")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
