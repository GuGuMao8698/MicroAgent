"""Tests for LLM DiscoRAG answer blueprint output parsing and validation.

Covers:
- Task 2: Replacement semantics (promotions are strictly replace, not append)
- Task 5: Full strict validation (all structural fields validated strictly)
"""

from __future__ import annotations

import json

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.evidence.llm_discorag_blueprint_parser import (
    _BLUEPRINT_CHUNK_ROLES,
    _BLUEPRINT_CONSTRAINT_TYPES,
    parse_llm_discorag_blueprint,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

ANSWER_IDS = ["chunk-a", "chunk-b"]
SUPPLEMENTAL_IDS = ["chunk-c", "chunk-d"]
ALL_CHUNK_IDS = ANSWER_IDS + SUPPLEMENTAL_IDS
RELATION_IDS = ["rel-1", "rel-2", "rel-3"]
RST_UNIT_IDS = ["chunk-a:u0", "chunk-a:u1", "chunk-b:u0", "chunk-c:u1"]
TOP_K = 5


def _valid_blueprint(
    *,
    final_ids: list[str] | None = None,
    promotions: list[dict] | None = None,
    chunk_roles: dict[str, str] | None = None,
    constraints: list[dict] | None = None,
    plan_steps: list[dict] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a minimal valid blueprint payload."""
    resolved_final_ids = ANSWER_IDS[:] if final_ids is None else final_ids
    resolved_chunk_roles = chunk_roles
    if resolved_chunk_roles is None:
        resolved_chunk_roles = {
            chunk_id: ("lead" if index == 0 else "support")
            for index, chunk_id in enumerate(resolved_final_ids)
        }
    return {
        "final_answer_chunk_ids": resolved_final_ids,
        "chunk_roles": resolved_chunk_roles,
        "promotions": promotions if promotions is not None else [],
        "answer_constraints": constraints if constraints is not None else [],
        "plan_steps": plan_steps if plan_steps is not None else [],
        "metadata": metadata
        if metadata is not None
        else {"planner": "llm_discorag_answer_blueprint_builder"},
    }


def _parse(
    payload: dict | str,
    *,
    answer_chunk_ids: list[str] | None = None,
    supplemental_chunk_ids: list[str] | None = None,
    known_relation_ids: list[str] | None = None,
    known_rst_unit_ids: list[str] | None = None,
    top_k: int = TOP_K,
    llm_metadata: dict | None = None,
):
    raw = json.dumps(payload) if isinstance(payload, dict) else payload
    return parse_llm_discorag_blueprint(
        raw,
        answer_chunk_ids=ANSWER_IDS if answer_chunk_ids is None else answer_chunk_ids,
        supplemental_chunk_ids=SUPPLEMENTAL_IDS
        if supplemental_chunk_ids is None
        else supplemental_chunk_ids,
        known_relation_ids=RELATION_IDS
        if known_relation_ids is None
        else known_relation_ids,
        known_rst_unit_ids=RST_UNIT_IDS
        if known_rst_unit_ids is None
        else known_rst_unit_ids,
        top_k=top_k,
        llm_metadata=llm_metadata,
    )


# ── Constants ────────────────────────────────────────────────────────────────


class TestConstants:
    def test_chunk_roles_has_8_members(self) -> None:
        assert len(_BLUEPRINT_CHUNK_ROLES) == 8

    def test_constraint_types_has_8_members(self) -> None:
        assert len(_BLUEPRINT_CONSTRAINT_TYPES) == 8

    @pytest.mark.parametrize(
        "role",
        [
            "lead",
            "support",
            "background",
            "caveat",
            "comparison",
            "definition",
            "condition",
            "context",
        ],
    )
    def test_each_chunk_role_present(self, role: str) -> None:
        assert role in _BLUEPRINT_CHUNK_ROLES

    @pytest.mark.parametrize(
        "ctype",
        [
            "caveat",
            "condition",
            "conflict",
            "comparison",
            "support",
            "background",
            "definition",
            "ordering",
        ],
    )
    def test_each_constraint_type_present(self, ctype: str) -> None:
        assert ctype in _BLUEPRINT_CONSTRAINT_TYPES


# ── 1. Valid complete output ─────────────────────────────────────────────────


class TestValidCompleteOutput:
    def test_produces_blueprint_with_correct_fields(self) -> None:
        payload = _valid_blueprint()
        bp = _parse(payload)

        assert bp.ordered_chunk_ids == ["chunk-a", "chunk-b"]
        assert bp.chunk_roles == {"chunk-a": "lead", "chunk-b": "support"}
        assert bp.metadata["builder"] == "llm_discorag_blueprint_parser"
        assert bp.metadata["final_chunk_count"] == 2

    def test_with_promotions_and_supplemental(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "chunk-c contradicts chunk-b",
                    "source_relation_ids": ["rel-2"],
                    "source_rst_unit_ids": ["chunk-c:u1"],
                }
            ],
        )
        bp = _parse(payload)

        assert bp.ordered_chunk_ids == ["chunk-a", "chunk-c"]
        assert bp.metadata["promotion_count"] == 1
        assert len(bp.metadata["promotions"]) == 1
        assert bp.metadata["promotions"][0]["with_chunk_id"] == "chunk-c"
        assert bp.metadata["promoted_chunk_ids"] == ["chunk-c"]

    def test_with_constraints_and_plan_steps(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "chunk-b has a condition",
                    "source_chunk_ids": ["chunk-b"],
                    "source_relation_ids": ["rel-1"],
                    "source_rst_unit_ids": ["chunk-b:u0"],
                }
            ],
            plan_steps=[
                {
                    "text": "Start from lead chunks.",
                    "source_chunk_ids": ["chunk-a"],
                    "source_relation_ids": [],
                    "source_rst_unit_ids": ["chunk-a:u0"],
                }
            ],
        )
        bp = _parse(payload)

        assert len(bp.answer_constraints) == 1
        assert bp.answer_constraints[0] == "chunk-b has a condition"
        assert len(bp.plan_steps) == 1
        assert bp.plan_steps[0] == "Start from lead chunks."


# ── 2. Invalid JSON ──────────────────────────────────────────────────────────


class TestInvalidJson:
    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ProcessingError, match="not valid JSON"):
            _parse("this is not json {{{")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ProcessingError, match="not valid JSON"):
            _parse("")

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse("[]")

    def test_accepts_parsed_dict(self) -> None:
        bp = _parse(_valid_blueprint())
        assert bp.ordered_chunk_ids == ["chunk-a", "chunk-b"]


# ── 3. Empty final_answer_chunk_ids with answer candidates ───────────────────


class TestEmptyChunkIdsWithCandidates:
    def test_empty_with_candidates_raises(self) -> None:
        payload = _valid_blueprint(final_ids=[])
        with pytest.raises(ProcessingError, match="must not be empty"):
            _parse(payload)

    def test_empty_without_candidates_is_ok(self) -> None:
        payload = _valid_blueprint(final_ids=[], chunk_roles={})
        bp = _parse(
            payload,
            answer_chunk_ids=[],
        )
        assert bp.ordered_chunk_ids == []


# ── 4. Duplicate chunk IDs ──────────────────────────────────────────────────


class TestDuplicateChunkIds:
    def test_duplicate_raises(self) -> None:
        payload = _valid_blueprint(final_ids=["chunk-a", "chunk-a"])
        with pytest.raises(ProcessingError) as exc_info:
            _parse(payload)

        message = str(exc_info.value)
        assert "Duplicate chunk ID in 'final_answer_chunk_ids': 'chunk-a'" in message
        assert "duplicate_final_context_ids=['chunk-a']" in message
        assert "expected_final_context_ids=['chunk-a', 'chunk-b']" in message
        assert "actual_final_answer_chunk_ids=['chunk-a', 'chunk-a']" in message


# ── 5. Unknown chunk IDs ────────────────────────────────────────────────────


class TestUnknownChunkIds:
    def test_unknown_chunk_raises(self) -> None:
        payload = _valid_blueprint(final_ids=["chunk-a", "chunk-ghost"])
        with pytest.raises(ProcessingError, match="Unknown chunk ID"):
            _parse(payload)


# ── 6. Budget overflow ──────────────────────────────────────────────────────


class TestBudgetOverflow:
    def test_exceeds_top_k_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-b", "chunk-c", "chunk-d"],
        )
        with pytest.raises(ProcessingError, match="exceeds top_k"):
            _parse(payload, top_k=3)

    def test_exactly_top_k_is_ok(self) -> None:
        payload = _valid_blueprint(final_ids=["chunk-a", "chunk-b"])
        bp = _parse(payload, top_k=2)
        assert len(bp.ordered_chunk_ids) == 2


# ── 7. Supplemental chunk without valid promotion ────────────────────────────


class TestSupplementalWithoutPromotion:
    def test_supplemental_without_promotion_raises(self) -> None:
        payload = _valid_blueprint(final_ids=["chunk-a", "chunk-c"])
        with pytest.raises(ProcessingError, match="without a valid promotion"):
            _parse(payload)


# ── 8. Promotion replaces supplemental instead of answer ─────────────────────


class TestPromotionReplacesSupplemental:
    def test_replace_supplemental_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-d"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-c",
                    "with_chunk_id": "chunk-d",
                    "reason": "test",
                }
            ],
        )
        with pytest.raises(ProcessingError, match="non-answer chunk"):
            _parse(payload)


# ── 9. Promotion inserts answer instead of supplemental ──────────────────────


class TestPromotionInsertsAnswer:
    def test_insert_answer_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-b"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-a",
                    "reason": "test",
                }
            ],
        )
        with pytest.raises(ProcessingError, match="non-supplemental chunk"):
            _parse(payload)


# ── 10. Unknown relation IDs ────────────────────────────────────────────────


class TestUnknownRelationIds:
    def test_unknown_relation_in_constraint_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": ["rel-nonexistent"],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="Unknown relation ID"):
            _parse(payload)

    def test_unknown_relation_in_plan_step_raises(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[
                {
                    "text": "step",
                    "source_relation_ids": ["rel-ghost"],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="Unknown relation ID"):
            _parse(payload)

    def test_unknown_relation_in_promotion_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "test",
                    "source_relation_ids": ["rel-ghost"],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="Unknown relation ID"):
            _parse(payload)


# ── 11. Unknown RST unit IDs ────────────────────────────────────────────────


class TestUnknownRstUnitIds:
    def test_unknown_rst_in_constraint_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": ["chunk-ghost:u0"],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="Unknown RST unit ID"):
            _parse(payload)

    def test_unknown_rst_in_plan_step_raises(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[
                {
                    "text": "step",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": ["nonexistent:u1"],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="Unknown RST unit ID"):
            _parse(payload)


# ── 12. Invalid chunk role (strict: raises ProcessingError) ──────────────────


class TestInvalidChunkRole:
    def test_invalid_role_raises(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-a": "lead", "chunk-b": "not_a_role"},
        )
        with pytest.raises(ProcessingError, match="Invalid chunk role"):
            _parse(payload)

    def test_all_invalid_roles_raises(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-a": "bad", "chunk-b": "worse"},
        )
        with pytest.raises(ProcessingError, match="Invalid chunk role"):
            _parse(payload)

    def test_unknown_chunk_id_in_roles_raises(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-unknown": "lead"},
        )
        with pytest.raises(ProcessingError, match="unknown chunk id"):
            _parse(payload)

    def test_chunk_roles_not_object_raises(self) -> None:
        payload = _valid_blueprint()
        payload["chunk_roles"] = "not_a_dict"
        with pytest.raises(ProcessingError, match="chunk_roles.*must be an object"):
            _parse(payload)

    def test_chunk_roles_list_raises(self) -> None:
        payload = _valid_blueprint()
        payload["chunk_roles"] = [["chunk-a", "lead"]]
        with pytest.raises(ProcessingError, match="chunk_roles.*must be an object"):
            _parse(payload)

    def test_missing_chunk_roles_for_final_chunk_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-b"],
            chunk_roles={"chunk-a": "lead"},
        )
        with pytest.raises(ProcessingError, match="chunk_roles.*missing"):
            _parse(payload)

    def test_no_chunk_roles_is_invalid_when_final_chunks_exist(self) -> None:
        payload = _valid_blueprint()
        del payload["chunk_roles"]
        with pytest.raises(ProcessingError, match="chunk_roles.*missing"):
            _parse(payload)


# ── 13. Invalid constraint type (strict: raises ProcessingError) ─────────────


class TestInvalidConstraintType:
    def test_invalid_type_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {"type": "invalid_type", "text": "x"},
            ],
        )
        with pytest.raises(ProcessingError, match="Invalid constraint type"):
            _parse(payload)

    def test_non_dict_constraint_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=["not_a_dict"],  # type: ignore[list-item]
        )
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse(payload)

    def test_constraint_non_string_text_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {"type": "caveat", "text": 123},
            ],
        )
        with pytest.raises(ProcessingError, match="Constraint 'text' must be a string"):
            _parse(payload)

    def test_constraint_missing_text_uses_empty(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {"type": "caveat"},
            ],
        )
        bp = _parse(payload)
        assert bp.answer_constraints == [""]

    def test_answer_constraints_not_list_raises(self) -> None:
        payload = _valid_blueprint()
        payload["answer_constraints"] = "not_a_list"
        with pytest.raises(ProcessingError, match="answer_constraints.*must be a list"):
            _parse(payload)

    def test_no_answer_constraints_is_ok(self) -> None:
        payload = _valid_blueprint()
        del payload["answer_constraints"]
        bp = _parse(payload)
        assert bp.answer_constraints == []


# ── 14. Missing required fields ──────────────────────────────────────────────


class TestMissingRequiredFields:
    def test_missing_final_answer_chunk_ids(self) -> None:
        payload = {"chunk_roles": {}}
        with pytest.raises(ProcessingError, match="missing 'final_answer_chunk_ids'"):
            _parse(payload)

    def test_final_answer_chunk_ids_not_list(self) -> None:
        payload = {"final_answer_chunk_ids": "oops"}
        with pytest.raises(ProcessingError, match="must be a list"):
            _parse(payload)


# ── 15. Empty relation/RST unit lists are valid ──────────────────────────────


class TestEmptyRefLists:
    def test_empty_relation_ids_valid(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "ok",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        bp = _parse(payload)
        assert len(bp.answer_constraints) == 1

    def test_missing_source_ids_treated_as_empty(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[
                {"text": "step without refs"},
            ],
        )
        bp = _parse(payload)
        assert len(bp.plan_steps) == 1


# ── 16. Metadata is preserved ────────────────────────────────────────────────


class TestMetadataPreserved:
    def test_llm_output_metadata_preserved(self) -> None:
        payload = _valid_blueprint(
            metadata={"planner": "llm_discorag_answer_blueprint_builder", "version": 2}
        )
        bp = _parse(payload)

        assert (
            bp.metadata["llm_output_metadata"]["planner"]
            == "llm_discorag_answer_blueprint_builder"
        )
        assert bp.metadata["llm_output_metadata"]["version"] == 2

    def test_no_llm_output_metadata_when_missing(self) -> None:
        payload = _valid_blueprint()
        del payload["metadata"]
        bp = _parse(payload)

        assert "llm_output_metadata" not in bp.metadata

    def test_llm_metadata_attached(self) -> None:
        payload = _valid_blueprint()
        llm_meta = {"model": "deepseek-v4", "provider": "deepseek"}
        bp = _parse(payload, llm_metadata=llm_meta)

        assert bp.metadata["llm"]["model"] == "deepseek-v4"
        assert bp.metadata["llm"]["provider"] == "deepseek"

    def test_no_llm_key_when_not_provided(self) -> None:
        payload = _valid_blueprint()
        bp = _parse(payload)

        assert "llm" not in bp.metadata


# ── 17. Source IDs collected in metadata ──────────────────────────────────────


class TestSourceIdsInMetadata:
    def test_source_ids_collected_in_metadata(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "c1",
                    "source_relation_ids": ["rel-1"],
                    "source_rst_unit_ids": ["chunk-a:u0"],
                },
            ],
            plan_steps=[
                {
                    "text": "s1",
                    "source_relation_ids": ["rel-2"],
                    "source_rst_unit_ids": ["chunk-b:u0"],
                },
            ],
        )
        bp = _parse(payload)

        assert "rel-1" in bp.metadata["source_relation_ids"]
        assert "rel-2" in bp.metadata["source_relation_ids"]
        assert "chunk-a:u0" in bp.metadata["source_rst_unit_ids"]
        assert "chunk-b:u0" in bp.metadata["source_rst_unit_ids"]


# ============================================================================
# Task 2: Replacement semantics tests
# ============================================================================


class TestPromotionReplacementSemantics:
    """Promotions must be strictly replacement, not append."""

    def test_valid_replacement_passes(self) -> None:
        """Valid: chunk-b (answer) replaced by chunk-c (supplemental)."""
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "chunk-c is better",
                }
            ],
        )
        bp = _parse(payload)
        assert bp.ordered_chunk_ids == ["chunk-a", "chunk-c"]
        assert bp.metadata["promotion_count"] == 1

    def test_append_style_promotion_fails(self) -> None:
        """Append: supplemental chunk appears in final but replaced chunk also
        stays -> replaced chunk in final_answer_chunk_ids is forbidden."""
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-b", "chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "append attempt",
                }
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="must not appear in 'final_answer_chunk_ids'",
        ):
            _parse(payload)

    def test_duplicate_replace_chunk_id_raises(self) -> None:
        """Two promotions replacing the same answer chunk."""
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-c", "chunk-d"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "first",
                },
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-d",
                    "reason": "second",
                },
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="Duplicate promotion for 'replace_chunk_id'",
        ):
            _parse(payload)

    def test_duplicate_with_chunk_id_raises(self) -> None:
        """Two promotions inserting the same supplemental chunk.

        Both replace different answer chunks with the same supplemental chunk.
        The second promotion should be caught by the with_chunk_id dedup.
        Final list excludes both replaced chunks so the earlier
        'replace_chunk_id must not appear in final' check does not fire first.
        """
        payload = _valid_blueprint(
            final_ids=["chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-a",
                    "with_chunk_id": "chunk-c",
                    "reason": "first",
                },
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "second",
                },
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="Duplicate promotion for 'with_chunk_id'",
        ):
            _parse(payload)

    def test_promotion_not_list_raises(self) -> None:
        payload = _valid_blueprint()
        payload["promotions"] = "not_a_list"
        with pytest.raises(ProcessingError, match="promotions.*must be a list"):
            _parse(payload)

    def test_promotion_not_dict_raises(self) -> None:
        payload = _valid_blueprint(
            promotions=["not_a_dict"],  # type: ignore[list-item]
        )
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse(payload)

    def test_promotion_replace_id_not_string_raises(self) -> None:
        payload = _valid_blueprint(
            promotions=[{"replace_chunk_id": 42, "with_chunk_id": "chunk-c"}],  # type: ignore[dict-item]
        )
        with pytest.raises(ProcessingError, match="replace_chunk_id.*must be a string"):
            _parse(payload)

    def test_promotion_with_id_not_string_raises(self) -> None:
        payload = _valid_blueprint(
            promotions=[{"replace_chunk_id": "chunk-b", "with_chunk_id": 99}],  # type: ignore[dict-item]
        )
        with pytest.raises(ProcessingError, match="with_chunk_id.*must be a string"):
            _parse(payload)

    def test_promoted_chunk_ids_in_metadata(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a", "chunk-c"],
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                }
            ],
        )
        bp = _parse(payload)
        assert bp.metadata["promoted_chunk_ids"] == ["chunk-c"]


class TestFinalContextCoverage:
    """final_answer_chunk_ids must exactly cover parser-input final contexts."""

    def test_missing_answer_candidate_raises_with_diagnostics(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a"],
            chunk_roles={"chunk-a": "lead"},
        )

        with pytest.raises(ProcessingError) as exc_info:
            _parse(payload)

        message = str(exc_info.value)
        assert "missing_final_context_ids=['chunk-b']" in message
        assert "unexpected_final_context_ids=[]" in message
        assert "duplicate_final_context_ids=[]" in message
        assert "expected_final_context_ids=['chunk-a', 'chunk-b']" in message
        assert "actual_final_answer_chunk_ids=['chunk-a']" in message

    def test_all_answer_candidates_in_planner_order_passes(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-b", "chunk-a"],
            chunk_roles={"chunk-b": "lead", "chunk-a": "support"},
        )

        blueprint = _parse(payload)

        assert blueprint.ordered_chunk_ids == ["chunk-b", "chunk-a"]

    def test_promotion_coverage_accepts_replacement_set(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-c", "chunk-a"],
            chunk_roles={"chunk-c": "lead", "chunk-a": "support"},
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "chunk-c has stronger discourse support",
                }
            ],
        )

        blueprint = _parse(payload)

        assert blueprint.ordered_chunk_ids == ["chunk-c", "chunk-a"]
        assert blueprint.metadata["promoted_chunk_ids"] == ["chunk-c"]

    def test_promotion_missing_unpromoted_answer_candidate_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-c"],
            chunk_roles={"chunk-c": "lead"},
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "chunk-c replaces chunk-b",
                }
            ],
        )

        with pytest.raises(ProcessingError) as exc_info:
            _parse(payload)

        message = str(exc_info.value)
        assert "missing_final_context_ids=['chunk-a']" in message
        assert "expected_final_context_ids=['chunk-a', 'chunk-c']" in message
        assert "actual_final_answer_chunk_ids=['chunk-c']" in message

    def test_promotion_missing_promoted_supplemental_raises_with_diagnostics(
        self,
    ) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a"],
            chunk_roles={"chunk-a": "lead"},
            promotions=[
                {
                    "replace_chunk_id": "chunk-b",
                    "with_chunk_id": "chunk-c",
                    "reason": "chunk-c replaces chunk-b",
                }
            ],
        )

        with pytest.raises(ProcessingError) as exc_info:
            _parse(payload)

        message = str(exc_info.value)
        assert "missing_final_context_ids=['chunk-c']" in message
        assert "expected_final_context_ids=['chunk-a', 'chunk-c']" in message
        assert "actual_final_answer_chunk_ids=['chunk-a']" in message


# ============================================================================
# Task 5: Full strict validation tests
# ============================================================================


class TestStrictChunkRoles:
    """chunk_roles: must be object, all keys known, all roles valid."""

    def test_chunk_roles_non_dict_raises(self) -> None:
        payload = _valid_blueprint()
        payload["chunk_roles"] = 42
        with pytest.raises(ProcessingError, match="chunk_roles.*must be an object"):
            _parse(payload)

    def test_unknown_chunk_in_roles_raises(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-unknown": "lead"},
        )
        with pytest.raises(ProcessingError, match="unknown chunk id"):
            _parse(payload)

    def test_invalid_role_raises(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-a": "not_a_role"},
        )
        with pytest.raises(ProcessingError, match="Invalid chunk role"):
            _parse(payload)

    def test_valid_roles_pass(self) -> None:
        payload = _valid_blueprint(
            chunk_roles={"chunk-a": "lead", "chunk-b": "support"},
        )
        bp = _parse(payload)
        assert bp.chunk_roles == {"chunk-a": "lead", "chunk-b": "support"}

    def test_role_for_known_non_final_chunk_raises(self) -> None:
        payload = _valid_blueprint(
            final_ids=["chunk-a"],
            chunk_roles={"chunk-a": "lead", "chunk-b": "support"},
        )
        with pytest.raises(ProcessingError, match="chunk_roles.*non-final"):
            _parse(
                payload,
                answer_chunk_ids=["chunk-a"],
                supplemental_chunk_ids=["chunk-b", "chunk-c", "chunk-d"],
            )

    def test_no_chunk_roles_field_raises_when_final_chunks_exist(self) -> None:
        payload = _valid_blueprint()
        del payload["chunk_roles"]
        with pytest.raises(ProcessingError, match="chunk_roles.*missing"):
            _parse(payload)


class TestStrictConstraints:
    """answer_constraints: must be list, each element object, valid type, string text."""

    def test_constraints_not_list_raises(self) -> None:
        payload = _valid_blueprint()
        payload["answer_constraints"] = {"type": "caveat"}
        with pytest.raises(ProcessingError, match="answer_constraints.*must be a list"):
            _parse(payload)

    def test_non_dict_constraint_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=["not_a_dict"],  # type: ignore[list-item]
        )
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse(payload)

    def test_invalid_constraint_type_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[{"type": "invalid", "text": "x"}],
        )
        with pytest.raises(ProcessingError, match="Invalid constraint type"):
            _parse(payload)

    def test_non_string_text_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[{"type": "caveat", "text": 42}],
        )
        with pytest.raises(ProcessingError, match="Constraint 'text' must be a string"):
            _parse(payload)

    def test_missing_text_defaults_to_empty(self) -> None:
        payload = _valid_blueprint(
            constraints=[{"type": "caveat"}],
        )
        bp = _parse(payload)
        assert bp.answer_constraints == [""]

    def test_no_constraints_field_ok(self) -> None:
        payload = _valid_blueprint()
        del payload["answer_constraints"]
        bp = _parse(payload)
        assert bp.answer_constraints == []


class TestStrictPlanSteps:
    """plan_steps: must be list, each element object, string text."""

    def test_plan_steps_not_list_raises(self) -> None:
        payload = _valid_blueprint()
        payload["plan_steps"] = "not_a_list"
        with pytest.raises(ProcessingError, match="plan_steps.*must be a list"):
            _parse(payload)

    def test_non_dict_plan_step_raises(self) -> None:
        payload = _valid_blueprint(
            plan_steps=["not_a_dict"],  # type: ignore[list-item]
        )
        with pytest.raises(ProcessingError, match="must be a JSON object"):
            _parse(payload)

    def test_non_string_text_raises(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[{"text": 42}],
        )
        with pytest.raises(ProcessingError, match="Plan step 'text' must be a string"):
            _parse(payload)

    def test_missing_text_defaults_to_empty(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[{}],
        )
        bp = _parse(payload)
        assert bp.plan_steps == [""]

    def test_no_plan_steps_field_ok(self) -> None:
        payload = _valid_blueprint()
        del payload["plan_steps"]
        bp = _parse(payload)
        assert bp.plan_steps == []


class TestStrictSourceChunkIds:
    """source_chunk_ids in constraints/plan_steps must be known chunk ids."""

    def test_unknown_source_chunk_in_constraint_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_chunk_ids": ["chunk-ghost"],
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="Unknown chunk ID.*constraint source_chunk_ids",
        ):
            _parse(payload)

    def test_unknown_source_chunk_in_plan_step_raises(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[
                {
                    "text": "step",
                    "source_chunk_ids": ["chunk-nonexistent"],
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="Unknown chunk ID.*plan_step source_chunk_ids",
        ):
            _parse(payload)

    def test_valid_source_chunk_ids_pass(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "ok",
                    "source_chunk_ids": ["chunk-a", "chunk-c"],
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        bp = _parse(payload)
        assert len(bp.answer_constraints) == 1

    def test_source_chunk_ids_not_list_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_chunk_ids": "not_a_list",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="must be a list of strings",
        ):
            _parse(payload)

    def test_source_chunk_ids_non_string_element_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_chunk_ids": [42],
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(
            ProcessingError,
            match="must contain only strings",
        ):
            _parse(payload)


class TestStrictSourceIdFieldTypes:
    """source_relation_ids and source_rst_unit_ids must be lists of strings."""

    def test_source_relation_ids_not_list_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": "not_a_list",
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="must be a list of strings"):
            _parse(payload)

    def test_source_relation_ids_non_string_element_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": [42],
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="must contain only strings"):
            _parse(payload)

    def test_source_rst_unit_ids_not_list_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": "not_a_list",
                }
            ],
        )
        with pytest.raises(ProcessingError, match="must be a list of strings"):
            _parse(payload)

    def test_source_rst_unit_ids_non_string_element_raises(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": [],
                    "source_rst_unit_ids": [42],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="must contain only strings"):
            _parse(payload)

    def test_source_relation_ids_tuple_raises(self) -> None:
        """Tuples are arbitrary iterables, not valid lists.

        Must pass raw dict (bypass JSON serialization) since json.dumps
        converts tuples to lists.
        """
        payload = _valid_blueprint(
            constraints=[
                {
                    "type": "caveat",
                    "text": "x",
                    "source_relation_ids": ("rel-1",),  # type: ignore[dict-item]
                    "source_rst_unit_ids": [],
                }
            ],
        )
        with pytest.raises(ProcessingError, match="must be a list of strings"):
            # Pass raw dict to preserve tuple (json.dumps would convert it)
            parse_llm_discorag_blueprint(
                payload,
                answer_chunk_ids=ANSWER_IDS,
                supplemental_chunk_ids=SUPPLEMENTAL_IDS,
                known_relation_ids=RELATION_IDS,
                known_rst_unit_ids=RST_UNIT_IDS,
                top_k=TOP_K,
            )


# ── Valid constraints and plan steps still produce correct strings ─────────


class TestValidOutputProducesStrings:
    def test_constraints_produce_answer_constraints_strings(self) -> None:
        payload = _valid_blueprint(
            constraints=[
                {"type": "caveat", "text": "first"},
                {"type": "condition", "text": "second"},
            ],
        )
        bp = _parse(payload)
        assert bp.answer_constraints == ["first", "second"]

    def test_plan_steps_produce_plan_steps_strings(self) -> None:
        payload = _valid_blueprint(
            plan_steps=[
                {"text": "step one"},
                {"text": "step two"},
            ],
        )
        bp = _parse(payload)
        assert bp.plan_steps == ["step one", "step two"]
