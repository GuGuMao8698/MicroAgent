"""LLM-backed DiscoRAG answer blueprint builder.

Uses the structurer model to produce a final answer blueprint that selects,
orders, and roles answer chunks, applies promotions from supplemental chunks,
and generates constraints and plan steps grounded in discourse evidence.

Input:  IntraChunkDiscoursePackage + InterChunkDiscourseGraph.
Output: AnswerBlueprint (validated via parse_llm_discorag_blueprint).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    ChunkDiscourseStructure,
    EvidenceItem,
    InterChunkDiscourseGraph,
    IntraChunkDiscoursePackage,
)
from ragflow_lite.infrastructure.evidence.llm_discorag_blueprint_parser import (
    parse_llm_discorag_blueprint,
)
from ragflow_lite.infrastructure.evidence.structurer_retry import (
    build_validation_repair_messages,
    is_timeout_error,
)

# ── System instructions ─────────────────────────────────────────────────────

_BLUEPRINT_INSTRUCTIONS = """\
You are a discourse-aware answer planner.  Given a query, a set of answer \
candidate chunks, supplemental discourse chunks, intra-chunk RST structures, \
and inter-chunk discourse relations, produce a final answer blueprint.

Output a single JSON object with this shape:
{
  "final_answer_chunk_ids": ["<canonical_chunk_id>", ...],
  "chunk_roles": {"<canonical_chunk_id>": "<role>", ...},
  "promotions": [
    {
      "replace_chunk_id": "<answer_chunk_id>",
      "with_chunk_id": "<supplemental_chunk_id>",
      "reason": "<brief explanation>",
      "source_relation_ids": ["<relation_id>", ...],
      "source_rst_unit_ids": ["<unit_id>", ...]
    }
  ],
  "answer_constraints": [
    {
      "type": "<constraint_type>",
      "text": "<constraint description>",
      "source_chunk_ids": ["<canonical_chunk_id>", ...],
      "source_relation_ids": ["<relation_id>", ...],
      "source_rst_unit_ids": ["<unit_id>", ...]
    }
  ],
  "plan_steps": [
    {
      "text": "<step description>",
      "source_chunk_ids": ["<canonical_chunk_id>", ...],
      "source_relation_ids": ["<relation_id>", ...],
      "source_rst_unit_ids": ["<unit_id>", ...]
    }
  ],
  "metadata": {
    "planner": "llm_discorag_answer_blueprint_builder"
  }
}

Rules:
- final_answer_chunk_ids: ordered list of chunk IDs to include in the final \
answer. Maximum count is the top_k budget provided. All IDs must come from \
the answer candidates or be promoted from supplemental chunks.
- chunk_roles: assign exactly one role per chunk in final_answer_chunk_ids.
  Valid roles: lead, support, background, caveat, comparison, definition, \
condition, context.
- promotions: a supplemental chunk may enter final_answer_chunk_ids ONLY via \
a promotion that replaces an answer candidate. The replace_chunk_id must be an \
answer candidate; the with_chunk_id must be a supplemental chunk. Promotions \
are replacement, not append — the replaced answer chunk is removed.
- answer_constraints: each must have a valid type.
  Valid types: caveat, condition, conflict, comparison, support, background, \
definition, ordering.
  Reference relation IDs and RST unit IDs must exist in the input.
- plan_steps: ordered reasoning steps for the answerer. Reference relation IDs \
and RST unit IDs must exist in the input.
- Do not output markdown, prose, or commentary outside the JSON object.
"""


def _safe_base_url_host(base_url: str | None) -> str | None:
    """Extract hostname from base_url for safe logging (no path, query, or credentials)."""
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
        return parsed.hostname
    except Exception:
        return None


class LLMDiscoRAGAnswerBlueprintBuilder:
    """Build a DiscoRAG answer blueprint using an LLM structurer model."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        provider: str = "deepseek",
        client: Any | None = None,
        timeout_seconds: float = 90.0,
        max_attempts: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def _provenance_metadata(self) -> dict[str, Any]:
        """Build safe provenance metadata — never includes API keys."""
        meta: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "builder": "llm_discorag_answer_blueprint_builder",
        }
        host = _safe_base_url_host(self.base_url)
        if host:
            meta["base_url_host"] = host
        return meta

    def build(
        self,
        package: IntraChunkDiscoursePackage,
        *,
        graph: InterChunkDiscourseGraph | None = None,
    ) -> AnswerBlueprint:
        """Build answer blueprint from discourse package and inter-chunk graph."""
        items = package.evidence_package.items

        # 1. Classify chunks into answer and supplemental sets
        answer_items, supplemental_items = _classify_items(items)
        answer_chunk_ids = [it.canonical_chunk_id for it in answer_items]
        supplemental_chunk_ids = [it.canonical_chunk_id for it in supplemental_items]
        all_items = _dedupe_items(answer_items + supplemental_items)

        # 2. Derive top_k from source_selection metadata
        top_k = _resolve_top_k(package)

        # 3. Collect known relation IDs and RST unit IDs for parser validation
        known_relation_ids = _relation_ids(graph)
        known_rst_unit_ids = _rst_unit_ids(package.structures)

        # 4. Build lookup structures for RST details
        structures_by_id: dict[str, ChunkDiscourseStructure] = {
            s.canonical_chunk_id: s for s in package.structures
        }

        # 5. Build prompt
        input_text = _build_input(
            query=package.query,
            answer_items=answer_items,
            supplemental_items=supplemental_items,
            structures_by_id=structures_by_id,
            graph=graph,
            top_k=top_k,
        )

        # 6. Attempt loop: timeout retry uses fresh original request,
        #    validation repair uses multi-turn messages.
        client = self.client or self._build_client(self.api_key, self.base_url)
        instructions = _BLUEPRINT_INSTRUCTIONS
        last_error: Exception | None = None
        # None = use complete_json (fresh request); list = use complete_messages_json (repair)
        repair_messages: list[dict[str, str]] | None = None

        for attempt_index in range(self.max_attempts):
            try:
                if repair_messages is None:
                    raw_json = client.complete_json(
                        instructions=instructions,
                        input_text=input_text,
                        timeout_seconds=self.timeout_seconds,
                    )
                else:
                    raw_json = client.complete_messages_json(
                        repair_messages,
                        timeout_seconds=self.timeout_seconds,
                    )
            except Exception as exc:
                if is_timeout_error(exc):
                    if attempt_index >= self.max_attempts - 1:
                        raise ProcessingError(
                            f"LLM DiscoRAG blueprint builder failed after "
                            f"{self.max_attempts} attempts: timeout"
                        ) from exc
                    # Timeout retry: fresh original request
                    repair_messages = None
                    last_error = exc
                    continue
                raise ProcessingError(
                    f"LLM DiscoRAG blueprint builder call failed: {exc}"
                ) from exc

            try:
                return parse_llm_discorag_blueprint(
                    raw_json,
                    answer_chunk_ids=answer_chunk_ids,
                    supplemental_chunk_ids=supplemental_chunk_ids,
                    known_relation_ids=known_relation_ids,
                    known_rst_unit_ids=known_rst_unit_ids,
                    top_k=top_k,
                    llm_metadata=self._provenance_metadata(),
                )
            except ProcessingError as exc:
                last_error = exc
                if attempt_index >= self.max_attempts - 1:
                    break
                repair_messages = build_validation_repair_messages(
                    instructions=instructions,
                    input_text=input_text,
                    invalid_output=raw_json,
                    validation_error=str(exc),
                )

        raise ProcessingError(
            f"LLM DiscoRAG blueprint builder failed after "
            f"{self.max_attempts} attempts: {last_error}"
        ) from last_error

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "LLM DiscoRAG blueprint builder requires api_key and base_url "
                "when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


# ── Helper functions ─────────────────────────────────────────────────────────


def _classify_items(
    items: list[EvidenceItem],
) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    """Split items into answer candidates and supplemental discourse chunks.

    Answer candidates: selected_for_answer == True.
    Supplemental: selected_for_discourse == True AND selected_for_answer == False.
    """
    answer: list[EvidenceItem] = []
    supplemental: list[EvidenceItem] = []
    for item in items:
        if item.metadata.get("selected_for_answer") is True:
            answer.append(item)
        elif (
            item.metadata.get("selected_for_discourse") is True
            and item.metadata.get("selected_for_answer") is not True
        ):
            supplemental.append(item)
    return answer, supplemental


def _dedupe_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Deduplicate items by canonical_chunk_id, keeping first occurrence."""
    seen: set[str] = set()
    result: list[EvidenceItem] = []
    for item in items:
        if item.canonical_chunk_id in seen:
            continue
        seen.add(item.canonical_chunk_id)
        result.append(item)
    return result


def _resolve_top_k(package: IntraChunkDiscoursePackage) -> int:
    """Derive top_k from source_selection metadata or fall back to item count."""
    source_selection = package.evidence_package.metadata.get("source_selection")
    if isinstance(source_selection, dict):
        fck = source_selection.get("final_context_k")
        if isinstance(fck, int) and fck > 0:
            return fck
    # 默认使用 answer 候选数量作为预算下限
    answer_count = sum(
        1
        for item in package.evidence_package.items
        if item.metadata.get("selected_for_answer") is True
    )
    return max(answer_count, 1)


def _relation_ids(graph: InterChunkDiscourseGraph | None) -> list[str]:
    """Collect inter-chunk relation IDs from the graph metadata."""
    if graph is None:
        return []
    # InterChunkDiscourseRelation has no relation_id field; use index-based IDs
    # from metadata if available, otherwise synthesize.
    # The inter-chunk graph builder stores relations without explicit IDs.
    # The parser expects known_relation_ids for validation; derive from metadata
    # or synthesize stable IDs.
    return [
        rel.metadata.get("relation_id", f"ic_rel_{i}")
        for i, rel in enumerate(graph.relations)
    ]


def _rst_unit_ids(structures: list[ChunkDiscourseStructure]) -> list[str]:
    """Collect all RST unit IDs from chunk discourse structures."""
    return [unit.unit_id for struct in structures for unit in struct.units]


def _build_input(
    *,
    query: str,
    answer_items: list[EvidenceItem],
    supplemental_items: list[EvidenceItem],
    structures_by_id: dict[str, ChunkDiscourseStructure],
    graph: InterChunkDiscourseGraph | None,
    top_k: int,
) -> str:
    """Build the user message with all discourse context."""
    sections: list[str] = [f"query: {query}"]
    sections.append(f"top_k budget: {top_k}")

    # Answer candidate chunks
    if answer_items:
        parts: list[str] = ["## answer_candidates"]
        for idx, item in enumerate(answer_items, start=1):
            chunk_block = _format_chunk(idx, item, structures_by_id)
            parts.append(chunk_block)
        sections.append("\n\n".join(parts))

    # Supplemental discourse chunks
    if supplemental_items:
        parts = ["## supplemental_discourse_chunks"]
        # 继续编号以保持 CHUNK[N] 标识符全局唯一
        offset = len(answer_items)
        for idx, item in enumerate(supplemental_items, start=offset + 1):
            chunk_block = _format_chunk(idx, item, structures_by_id)
            parts.append(chunk_block)
        sections.append("\n\n".join(parts))

    # RST structures detail
    rst_detail = _rst_detail_section(structures_by_id)
    if rst_detail:
        sections.append(rst_detail)

    # Inter-chunk relations
    if graph is not None and graph.relations:
        sections.append(_inter_chunk_relations_section(graph))

    return "\n\n---\n\n".join(sections)


def _format_chunk(
    index: int,
    item: EvidenceItem,
    structures_by_id: dict[str, ChunkDiscourseStructure],
) -> str:
    """Format a single chunk with stable local identifier."""
    lines = [f"CHUNK[{index}] id={item.canonical_chunk_id}"]
    lines.append(f"text: {item.text}")

    structure = structures_by_id.get(item.canonical_chunk_id)
    if structure is not None:
        unit_summary = _chunk_unit_summary(structure)
        if unit_summary:
            lines.append(f"rst_units: {unit_summary}")

    return "\n".join(lines)


def _chunk_unit_summary(structure: ChunkDiscourseStructure) -> str:
    """Compact summary of units within a chunk for the prompt."""
    parts: list[str] = []
    for unit in structure.units:
        role = unit.planning_role or unit.role
        nuclearity = unit.nuclearity or "unknown"
        rst = unit.rst_relation or ""
        label = f"{unit.unit_id}(role={role}, nuclearity={nuclearity}"
        if rst:
            label += f", rst={rst}"
        label += ")"
        parts.append(label)
    return "; ".join(parts)


def _rst_detail_section(
    structures_by_id: dict[str, ChunkDiscourseStructure],
) -> str:
    """Build detailed RST section showing intra-chunk relations."""
    parts: list[str] = ["## rst_intra_chunk_relations"]
    has_content = False
    for cid, struct in structures_by_id.items():
        if not struct.relations:
            continue
        has_content = True
        rel_lines: list[str] = [f"chunk_id={cid}"]
        for rel in struct.relations:
            rel_lines.append(
                f"  {rel.source_unit_id} -> {rel.target_unit_id}: "
                f"{rel.relation_type} (weight={rel.weight})"
            )
        parts.append("\n".join(rel_lines))
    if not has_content:
        return ""
    return "\n\n".join(parts)


def _inter_chunk_relations_section(graph: InterChunkDiscourseGraph) -> str:
    """Build inter-chunk relations section."""
    lines: list[str] = ["## inter_chunk_relations"]
    for i, rel in enumerate(graph.relations):
        rid = rel.metadata.get("relation_id", f"ic_rel_{i}")
        conf = f", confidence={rel.confidence}" if rel.confidence is not None else ""
        rat = f", rationale={rel.rationale}" if rel.rationale else ""
        lines.append(
            f"id={rid}: {rel.source_chunk_id} -> {rel.target_chunk_id}: "
            f"{rel.relation_type}{conf}{rat}"
        )
    return "\n".join(lines)
