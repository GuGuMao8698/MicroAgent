"""Tests for LLM inter-chunk discourse graph output parsing and validation.

Strict semantics: any structurally invalid entry (non-object, missing fields,
unknown relation label, unknown chunk id, self-reference) raises
ProcessingError immediately. The only silent drop is ``unrelated``.
"""

from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.evidence.llm_inter_chunk_graph_parser import (
    MATERIALIZED_RELATION_TYPES,
    PAPER_INTER_CHUNK_RELATION_TYPES,
    parse_llm_inter_chunk_graph,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

CHUNK_IDS = ["chunk_a", "chunk_b", "chunk_c"]
QUERY = "Does vitamin D prevent flu?"


def _relation(
    source: str = "chunk_a",
    target: str = "chunk_b",
    relation_type: str = "supports",
    rationale: str | None = "A supports B.",
    confidence: float | None = 0.85,
) -> dict:
    r: dict = {
        "source_chunk_id": source,
        "target_chunk_id": target,
        "relation_type": relation_type,
    }
    if rationale is not None:
        r["rationale"] = rationale
    if confidence is not None:
        r["confidence"] = confidence
    return r


def _payload(relations: list[dict]) -> str:
    return json.dumps({"relations": relations})


def _parse(
    raw_json: str,
    *,
    chunk_ids: list[str] | None = None,
    query: str = QUERY,
    llm_metadata: dict | None = None,
):
    return parse_llm_inter_chunk_graph(
        raw_json,
        chunk_ids=chunk_ids or CHUNK_IDS,
        query=query,
        llm_metadata=llm_metadata,
    )


# ── Constants ────────────────────────────────────────────────────────────────


class TestConstants:
    def test_paper_set_has_21_labels(self) -> None:
        assert len(PAPER_INTER_CHUNK_RELATION_TYPES) == 21

    def test_materialized_set_has_20_labels(self) -> None:
        assert len(MATERIALIZED_RELATION_TYPES) == 20

    def test_unrelated_in_paper_but_not_materialized(self) -> None:
        assert "unrelated" in PAPER_INTER_CHUNK_RELATION_TYPES
        assert "unrelated" not in MATERIALIZED_RELATION_TYPES

    def test_materialized_is_paper_minus_unrelated(self) -> None:
        assert MATERIALIZED_RELATION_TYPES == PAPER_INTER_CHUNK_RELATION_TYPES - {
            "unrelated"
        }

    @pytest.mark.parametrize(
        "label",
        [
            "supports",
            "contradicts",
            "elaborates",
            "exemplifies",
            "causes",
            "results_from",
            "enables",
            "prevents",
            "precedes",
            "follows",
            "simultaneous",
            "background_for",
            "generalizes",
            "specifies",
            "compares_with",
            "contrasts_with",
            "supplements",
            "replaces",
            "motivates",
            "justifies",
            "unrelated",
        ],
    )
    def test_each_paper_label_present(self, label: str) -> None:
        assert label in PAPER_INTER_CHUNK_RELATION_TYPES


# ── Happy path ───────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_valid_output_with_multiple_relations(self) -> None:
        raw = _payload(
            [
                _relation(relation_type="supports"),
                _relation(
                    source="chunk_b",
                    target="chunk_c",
                    relation_type="elaborates",
                ),
            ]
        )

        graph = _parse(raw)

        assert graph.query == QUERY
        assert graph.chunk_ids == CHUNK_IDS
        assert len(graph.relations) == 2
        assert graph.relations[0].relation_type == "supports"
        assert graph.relations[1].relation_type == "elaborates"
        assert graph.metadata["valid_relation_count"] == 2

    def test_preserves_rationale_and_confidence(self) -> None:
        raw = _payload(
            [
                _relation(
                    rationale="Chunk A provides evidence for B.",
                    confidence=0.92,
                )
            ]
        )

        graph = _parse(raw)

        assert len(graph.relations) == 1
        assert graph.relations[0].rationale == "Chunk A provides evidence for B."
        assert graph.relations[0].confidence == 0.92

    def test_empty_relations_list_produces_empty_graph(self) -> None:
        raw = _payload([])

        graph = _parse(raw)

        assert graph.relations == []
        assert graph.metadata["valid_relation_count"] == 0
        assert graph.metadata["llm_raw_relation_count"] == 0

    def test_metadata_builder_key(self) -> None:
        raw = _payload([_relation()])

        graph = _parse(raw)

        assert graph.metadata["builder"] == "llm_inter_chunk_graph"

    def test_each_relation_source_is_llm(self) -> None:
        raw = _payload([_relation()])

        graph = _parse(raw)

        assert graph.relations[0].metadata["source"] == "llm_inter_chunk_graph"

    @pytest.mark.parametrize(
        "relation_type",
        sorted(MATERIALIZED_RELATION_TYPES),
    )
    def test_accepts_all_materialized_relation_types(self, relation_type: str) -> None:
        raw = _payload([_relation(relation_type=relation_type)])

        graph = _parse(raw)

        assert len(graph.relations) == 1
        assert graph.relations[0].relation_type == relation_type


# ── UNRELATED filtering ──────────────────────────────────────────────────────


class TestUnrelatedFiltering:
    def test_drops_unrelated_relations(self) -> None:
        raw = _payload(
            [
                _relation(relation_type="supports"),
                _relation(relation_type="unrelated"),
                _relation(
                    source="chunk_b",
                    target="chunk_c",
                    relation_type="elaborates",
                ),
            ]
        )

        graph = _parse(raw)

        assert len(graph.relations) == 2
        types = [r.relation_type for r in graph.relations]
        assert "unrelated" not in types
        assert graph.metadata["dropped_unrelated"] == 1

    def test_all_unrelated_produces_empty_graph(self) -> None:
        """All-unrelated is valid: unrelated entries are silently dropped."""
        raw = _payload(
            [
                _relation(relation_type="unrelated"),
                _relation(
                    source="chunk_b",
                    target="chunk_c",
                    relation_type="unrelated",
                ),
            ]
        )

        graph = _parse(raw)

        assert graph.relations == []
        assert graph.metadata["dropped_unrelated"] == 2

    def test_only_unrelated_entries_is_valid(self) -> None:
        """Empty graph from all-unrelated is explicitly valid per spec."""
        raw = _payload(
            [
                _relation(relation_type="unrelated"),
                _relation(
                    source="chunk_b",
                    target="chunk_c",
                    relation_type="unrelated",
                ),
                _relation(
                    source="chunk_c",
                    target="chunk_a",
                    relation_type="unrelated",
                ),
            ]
        )

        graph = _parse(raw)

        assert len(graph.relations) == 0
        assert graph.metadata["dropped_unrelated"] == 3


# ── Invalid relation type (strict) ──────────────────────────────────────────


class TestInvalidRelationType:
    def test_unknown_relation_type_in_mixed_payload_raises(self) -> None:
        """Mixed valid + unknown relation label must fail."""
        raw = _payload(
            [
                _relation(relation_type="invalid_type"),
                _relation(relation_type="supports"),
            ]
        )

        with pytest.raises(ProcessingError, match="unknown relation type"):
            _parse(raw)

    def test_all_invalid_types_raises(self) -> None:
        raw = _payload(
            [
                _relation(relation_type="not_a_type"),
                _relation(relation_type="also_bad"),
            ]
        )

        with pytest.raises(ProcessingError, match="unknown relation type"):
            _parse(raw)


# ── Unknown chunk IDs (strict) ──────────────────────────────────────────────


class TestUnknownChunkIds:
    def test_unknown_source_in_mixed_payload_raises(self) -> None:
        """Mixed valid + unknown chunk must fail."""
        raw = _payload(
            [
                _relation(source="chunk_missing", relation_type="supports"),
                _relation(relation_type="elaborates"),
            ]
        )

        with pytest.raises(ProcessingError, match="unknown source chunk"):
            _parse(raw)

    def test_unknown_target_in_mixed_payload_raises(self) -> None:
        """Mixed valid + unknown chunk must fail."""
        raw = _payload(
            [
                _relation(target="chunk_ghost", relation_type="supports"),
                _relation(relation_type="elaborates"),
            ]
        )

        with pytest.raises(ProcessingError, match="unknown target chunk"):
            _parse(raw)

    def test_both_unknown_raises(self) -> None:
        raw = _payload([_relation(source="x", target="y", relation_type="supports")])

        with pytest.raises(ProcessingError, match="unknown source chunk"):
            _parse(raw)

    def test_unknown_source_unrelated_still_raises(self) -> None:
        raw = _payload([_relation(source="chunk_missing", relation_type="unrelated")])

        with pytest.raises(ProcessingError, match="unknown source chunk"):
            _parse(raw)

    def test_unknown_target_unrelated_still_raises(self) -> None:
        raw = _payload([_relation(target="chunk_ghost", relation_type="unrelated")])

        with pytest.raises(ProcessingError, match="unknown target chunk"):
            _parse(raw)


# ── Self-references (strict) ────────────────────────────────────────────────


class TestSelfReferences:
    def test_self_ref_in_mixed_payload_raises(self) -> None:
        """Mixed valid + self-reference must fail."""
        raw = _payload(
            [
                _relation(source="chunk_a", target="chunk_a", relation_type="supports"),
                _relation(relation_type="elaborates"),
            ]
        )

        with pytest.raises(ProcessingError, match="self-referential"):
            _parse(raw)

    def test_all_self_refs_raises(self) -> None:
        raw = _payload(
            [
                _relation(source="chunk_a", target="chunk_a", relation_type="supports"),
                _relation(
                    source="chunk_b", target="chunk_b", relation_type="elaborates"
                ),
            ]
        )

        with pytest.raises(ProcessingError, match="self-referential"):
            _parse(raw)

    def test_self_ref_unrelated_still_raises(self) -> None:
        raw = _payload(
            [
                _relation(
                    source="chunk_a",
                    target="chunk_a",
                    relation_type="unrelated",
                )
            ]
        )

        with pytest.raises(ProcessingError, match="self-referential"):
            _parse(raw)


# ── Confidence clamping ─────────────────────────────────────────────────────


class TestConfidenceClamping:
    @pytest.mark.parametrize(
        "raw_conf, expected",
        [
            (-0.5, 0.0),
            (1.5, 1.0),
            (-100.0, 0.0),
            (100.0, 1.0),
        ],
    )
    def test_clamps_out_of_range_confidence(
        self, raw_conf: float, expected: float
    ) -> None:
        raw = _payload([_relation(confidence=raw_conf)])

        graph = _parse(raw)

        assert len(graph.relations) == 1
        assert graph.relations[0].confidence == expected
        assert graph.metadata["clamped_confidence_count"] == 1

    @pytest.mark.parametrize(
        "valid_conf",
        [0.0, 0.5, 1.0],
    )
    def test_keeps_in_range_confidence(self, valid_conf: float) -> None:
        raw = _payload([_relation(confidence=valid_conf)])

        graph = _parse(raw)

        assert graph.relations[0].confidence == valid_conf
        assert graph.metadata["clamped_confidence_count"] == 0

    def test_non_numeric_confidence_treated_as_missing(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "chunk_a",
                        "target_chunk_id": "chunk_b",
                        "relation_type": "supports",
                        "confidence": "high",
                    }
                ]
            }
        )

        graph = _parse(payload)

        assert len(graph.relations) == 1
        assert graph.relations[0].confidence is None


# ── Missing optional fields ──────────────────────────────────────────────────


class TestMissingOptionalFields:
    def test_missing_rationale_defaults_to_none(self) -> None:
        raw = _payload([_relation(rationale=None)])

        graph = _parse(raw)

        assert graph.relations[0].rationale is None

    def test_missing_confidence_defaults_to_none(self) -> None:
        raw = _payload([_relation(confidence=None)])

        graph = _parse(raw)

        assert graph.relations[0].confidence is None

    def test_missing_both_optional_fields(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "chunk_a",
                        "target_chunk_id": "chunk_b",
                        "relation_type": "supports",
                    }
                ]
            }
        )

        graph = _parse(payload)

        assert len(graph.relations) == 1
        assert graph.relations[0].rationale is None
        assert graph.relations[0].confidence is None


# ── Missing required fields (strict) ────────────────────────────────────────


class TestMissingRequiredFields:
    def test_missing_source_chunk_id_raises(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "target_chunk_id": "chunk_b",
                        "relation_type": "supports",
                    }
                ]
            }
        )

        with pytest.raises(ProcessingError, match="missing or empty.*source_chunk_id"):
            _parse(payload)

    def test_missing_target_chunk_id_raises(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "chunk_a",
                        "relation_type": "supports",
                    }
                ]
            }
        )

        with pytest.raises(ProcessingError, match="missing or empty.*target_chunk_id"):
            _parse(payload)

    def test_missing_relation_type_raises(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "chunk_a",
                        "target_chunk_id": "chunk_b",
                    }
                ]
            }
        )

        with pytest.raises(ProcessingError, match="missing or empty.*relation_type"):
            _parse(payload)

    def test_empty_source_chunk_id_raises(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "  ",
                        "target_chunk_id": "chunk_b",
                        "relation_type": "supports",
                    }
                ]
            }
        )

        with pytest.raises(ProcessingError, match="missing or empty.*source_chunk_id"):
            _parse(payload)

    def test_empty_target_chunk_id_raises(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "chunk_a",
                        "target_chunk_id": "",
                        "relation_type": "supports",
                    }
                ]
            }
        )

        with pytest.raises(ProcessingError, match="missing or empty.*target_chunk_id"):
            _parse(payload)

    def test_non_dict_entry_raises(self) -> None:
        """Non-object relation entry must fail immediately."""
        raw = _payload(
            [
                "not_a_dict",  # type: ignore[list-item]
                _relation(),
            ]
        )

        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse(raw)

    def test_missing_fields_in_mixed_payload_raises(self) -> None:
        """Mixed valid + missing fields must fail."""
        raw = _payload(
            [
                _relation(),
                {
                    "target_chunk_id": "chunk_b",
                    "relation_type": "supports",
                },
            ]
        )

        with pytest.raises(ProcessingError, match="missing or empty.*source_chunk_id"):
            _parse(raw)


# ── JSON parse failures ─────────────────────────────────────────────────────


class TestJsonParseFailures:
    def test_completely_unparseable_json(self) -> None:
        with pytest.raises(ProcessingError, match="not valid JSON"):
            _parse("this is not json at all {{{")

    def test_empty_string(self) -> None:
        with pytest.raises(ProcessingError, match="not valid JSON"):
            _parse("")

    def test_non_object_json(self) -> None:
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse("[]")

    def test_non_object_json_string(self) -> None:
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse('"hello"')

    def test_missing_relations_key(self) -> None:
        with pytest.raises(ProcessingError, match="missing 'relations' key"):
            _parse('{"data": []}')

    def test_relations_not_a_list(self) -> None:
        with pytest.raises(ProcessingError, match="'relations' must be a list"):
            _parse('{"relations": "oops"}')

    def test_relations_is_number(self) -> None:
        with pytest.raises(ProcessingError, match="'relations' must be a list"):
            _parse('{"relations": 42}')


# ── All-invalid composite (strict) ──────────────────────────────────────────


class TestAllInvalidComposite:
    def test_mixed_invalid_reasons_raises_on_first(self) -> None:
        """Strict: first non-unrelated invalid entry raises immediately."""
        raw = _payload(
            [
                _relation(relation_type="unrelated"),
                _relation(relation_type="not_real"),
                _relation(source="chunk_ghost"),
                _relation(source="chunk_a", target="chunk_a"),
                "not_a_dict",  # type: ignore[list-item]
            ]
        )

        # Should raise on the "not_real" relation type
        with pytest.raises(ProcessingError, match="unknown relation type"):
            _parse(raw)


# ── LLM metadata ────────────────────────────────────────────────────────────


class TestLlmMetadata:
    def test_llm_metadata_observable_in_output(self) -> None:
        raw = _payload([_relation()])
        llm_meta = {"model": "gpt-4o", "provider": "openai", "usage": {"tokens": 150}}

        graph = _parse(raw, llm_metadata=llm_meta)

        assert graph.metadata["llm"] == llm_meta
        assert graph.metadata["llm"]["model"] == "gpt-4o"
        assert graph.metadata["llm"]["provider"] == "openai"

    def test_no_llm_metadata_key_when_not_provided(self) -> None:
        raw = _payload([_relation()])

        graph = _parse(raw)

        assert "llm" not in graph.metadata

    def test_empty_llm_metadata_not_attached(self) -> None:
        raw = _payload([_relation()])

        graph = _parse(raw, llm_metadata={})

        # Empty dict is falsy — should not attach
        assert "llm" not in graph.metadata


# ── Whitespace handling ─────────────────────────────────────────────────────


class TestWhitespaceHandling:
    def test_whitespace_trimmed_from_chunk_ids(self) -> None:
        payload = json.dumps(
            {
                "relations": [
                    {
                        "source_chunk_id": "  chunk_a  ",
                        "target_chunk_id": "  chunk_b  ",
                        "relation_type": "  supports  ",
                    }
                ]
            }
        )

        graph = _parse(payload)

        assert len(graph.relations) == 1
        assert graph.relations[0].source_chunk_id == "chunk_a"
        assert graph.relations[0].target_chunk_id == "chunk_b"
        assert graph.relations[0].relation_type == "supports"


# ── Metadata counts (strict) ────────────────────────────────────────────────


class TestMetadataCounts:
    def test_counts_with_unrelated_drop(self) -> None:
        """Only unrelated count and confidence clamp remain in metadata."""
        raw = _payload(
            [
                # valid
                _relation(relation_type="supports"),
                # unrelated (silently dropped)
                _relation(
                    source="chunk_b",
                    target="chunk_c",
                    relation_type="unrelated",
                ),
            ]
        )

        graph = _parse(raw)

        assert graph.metadata["dropped_unrelated"] == 1
        assert graph.metadata["valid_relation_count"] == 1
        assert graph.metadata["llm_raw_relation_count"] == 2

    def test_no_legacy_drop_keys_in_metadata(self) -> None:
        """Strict mode removed per-category drop counts; only unrelated remains."""
        raw = _payload([_relation()])

        graph = _parse(raw)

        # These legacy keys must not appear in strict metadata
        assert "dropped_invalid_type" not in graph.metadata
        assert "dropped_unknown_chunk" not in graph.metadata
        assert "dropped_self_ref" not in graph.metadata
        assert "dropped_missing_fields" not in graph.metadata
        assert "total_dropped" not in graph.metadata
