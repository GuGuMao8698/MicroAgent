"""LLM-backed inter-chunk discourse graph builder.

Uses the structurer model to infer directed rhetorical relations among
discourse-visible chunks, replacing the deterministic metadata-rule builder
with listwise graph inference.

Input:  IntraChunkDiscoursePackage (from the intra-chunk RST extractor).
Output: InterChunkDiscourseGraph  (validated via parse_llm_inter_chunk_graph).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    ChunkDiscourseStructure,
    EvidenceItem,
    InterChunkDiscourseGraph,
    IntraChunkDiscoursePackage,
)
from ragflow_lite.infrastructure.evidence.llm_inter_chunk_graph_parser import (
    parse_llm_inter_chunk_graph,
)

# ── System instructions ─────────────────────────────────────────────────────

_INTER_CHUNK_INSTRUCTIONS = """\
Identify directed rhetorical relations among the provided chunks.

You are given a set of text chunks (each identified by CHUNK[N] and a canonical_chunk_id). \
Your task is to analyze cross-chunk discourse and output a JSON object listing the \
inter-chunk rhetorical relations you find.

Valid relation types (use exactly these labels):
  supports, contradicts, elaborates, exemplifies, causes, results_from,
  enables, prevents, precedes, follows, simultaneous, background_for,
  generalizes, specifies, compares_with, contrasts_with, supplements,
  replaces, motivates, justifies

Do NOT output "unrelated" relations — only include relations where a real \
rhetorical connection exists.

Output a single JSON object with this shape:
{
  "relations": [
    {
      "source_chunk_id": "<canonical_chunk_id>",
      "target_chunk_id": "<canonical_chunk_id>",
      "relation_type": "<one of the 20 valid labels>",
      "rationale": "<brief explanation>",
      "confidence": 0.8
    }
  ]
}

Rules:
- source_chunk_id and target_chunk_id must be exact canonical_chunk_id values from the input.
- source and target must be different chunks.
- confidence must be a number between 0.0 and 1.0.
- rationale is optional but recommended.
- Return an empty relations array if no meaningful cross-chunk relations exist.
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


class LLMInterChunkDiscourseGraphBuilder:
    """Build an inter-chunk discourse graph using an LLM structurer model."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-v4-flash",
        reasoning_effort: str = "high",
        provider: str = "deepseek",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.client = client

    def _provenance_metadata(self) -> dict[str, Any]:
        """Build safe provenance metadata — never includes API keys."""
        meta: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "builder": "llm_inter_chunk_discourse_graph",
        }
        host = _safe_base_url_host(self.base_url)
        if host:
            meta["base_url_host"] = host
        return meta

    def build(self, package: IntraChunkDiscoursePackage) -> InterChunkDiscourseGraph:
        """Build inter-chunk discourse graph from an intra-chunk discourse package."""
        # 1. Select discourse-visible chunks
        items = _select_discourse_visible_items(
            package.evidence_package.items,
        )
        if not items:
            return _empty_graph(package, self._provenance_metadata())

        # 2. Build lookup structures for RST summaries
        structures_by_id: dict[str, ChunkDiscourseStructure] = {
            s.canonical_chunk_id: s for s in package.structures
        }

        # 3. Build prompt
        input_text = _build_input(package.query, items, structures_by_id)

        # 4. Call LLM
        client = self.client or self._build_client(self.api_key, self.base_url)
        try:
            raw_json = client.complete_json(
                instructions=_INTER_CHUNK_INSTRUCTIONS,
                input_text=input_text,
            )
        except Exception as exc:
            raise ProcessingError(
                f"LLM inter-chunk graph builder call failed: {exc}"
            ) from exc

        # 5. Parse and validate
        chunk_ids = [item.canonical_chunk_id for item in items]
        try:
            graph = parse_llm_inter_chunk_graph(
                raw_json,
                chunk_ids=chunk_ids,
                query=package.query,
                llm_metadata=self._provenance_metadata(),
            )
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError(
                f"LLM inter-chunk graph builder parsing failed: {exc}"
            ) from exc

        return graph

    def _build_client(self, api_key: str | None, base_url: str | None) -> Any:
        from ragflow_lite.infrastructure.llms import DeepSeekChatCompletionsClient

        if api_key is None or base_url is None:
            raise ProcessingError(
                "LLM inter-chunk graph builder requires api_key and base_url "
                "when no client is provided."
            )
        return DeepSeekChatCompletionsClient(
            api_key=api_key,
            base_url=base_url,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


# ── Helper functions ─────────────────────────────────────────────────────────


def _select_discourse_visible_items(
    items: list[EvidenceItem],
) -> list[EvidenceItem]:
    """Select discourse-visible items, deduplicating by canonical_chunk_id."""
    explicit = [
        item for item in items if item.metadata.get("selected_for_discourse") is True
    ]
    source = explicit if explicit else items

    selected: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in source:
        if item.canonical_chunk_id in seen:
            continue
        selected.append(item)
        seen.add(item.canonical_chunk_id)
    return selected


def _build_input(
    query: str,
    items: list[EvidenceItem],
    structures_by_id: dict[str, ChunkDiscourseStructure],
) -> str:
    """Build the user message listing chunks with optional RST summaries."""
    sections: list[str] = [f"query: {query}"]

    for index, item in enumerate(items, start=1):
        chunk_header = f"CHUNK[{index}] id={item.canonical_chunk_id}"
        chunk_text = f"text: {item.text}"

        structure = structures_by_id.get(item.canonical_chunk_id)
        if structure is not None:
            summary = _rst_summary(structure)
            if summary:
                sections.append(f"{chunk_header}\n{chunk_text}\nrst_summary: {summary}")
                continue

        sections.append(f"{chunk_header}\n{chunk_text}")

    return "\n\n---\n\n".join(sections)


def _rst_summary(structure: ChunkDiscourseStructure) -> str:
    """Build a compact RST summary from a chunk's discourse structure.

    Shows the main unit texts and a condensed view of intra-chunk relations
    without emitting the full raw tree.
    """
    parts: list[str] = []

    # Main units
    main_texts = [
        unit.text for unit in structure.units if unit.unit_id in structure.main_unit_ids
    ]
    if main_texts:
        parts.append(f"main: {'; '.join(main_texts)}")

    # Intra-chunk relation summary: "type count" for each
    if structure.relations:
        type_counts: dict[str, int] = {}
        for rel in structure.relations:
            type_counts[rel.relation_type] = type_counts.get(rel.relation_type, 0) + 1
        rel_summary = ", ".join(
            f"{rtype}({count})" for rtype, count in sorted(type_counts.items())
        )
        parts.append(f"intra_relations: {rel_summary}")

    return " | ".join(parts)


def _empty_graph(
    package: IntraChunkDiscoursePackage,
    provenance: dict[str, Any],
) -> InterChunkDiscourseGraph:
    """Return an empty inter-chunk discourse graph when no chunks are visible."""
    return InterChunkDiscourseGraph(
        query=package.query,
        chunk_ids=[],
        relations=[],
        metadata={
            "builder": "llm_inter_chunk_discourse_graph",
            "model": None,
            "status": "empty",
            "valid_relation_count": 0,
            "llm": provenance,
        },
    )
