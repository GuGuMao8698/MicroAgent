from __future__ import annotations

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.infrastructure.retrievers.cot_grounding import (
    COT_GROUNDING_INSTRUCTIONS,
    parse_cot_grounding_result,
    render_enriched_grounding_input,
)


def test_parse_cot_grounding_result_accepts_solution_steps_only() -> None:
    result = parse_cot_grounding_result(
        '{"original_query":"What improves MiniRAG recall?",'
        '"solution_steps":["Identify recall failure.", "Map entities and relations."]}',
        expected_query="What improves MiniRAG recall?",
        attempts=1,
    )

    assert result.status == "succeeded"
    assert result.solution_steps == [
        "Identify recall failure.",
        "Map entities and relations.",
    ]
    assert result.original_query == "What improves MiniRAG recall?"


def test_parse_cot_grounding_result_rejects_direct_retrieval_parameters() -> None:
    with pytest.raises(ProcessingError, match="must not include retrieval fields"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["step"],"entities":["MiniRAG"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_mismatched_query() -> None:
    with pytest.raises(ProcessingError, match="original_query does not match"):
        parse_cot_grounding_result(
            '{"original_query":"Different","solution_steps":["step"]}',
            expected_query="Q",
            attempts=1,
        )


def test_parse_cot_grounding_result_rejects_empty_steps() -> None:
    with pytest.raises(ProcessingError, match="solution_steps"):
        parse_cot_grounding_result(
            '{"original_query":"Q","solution_steps":["   "]}',
            expected_query="Q",
            attempts=1,
        )


def test_render_enriched_grounding_input_contains_query_and_steps() -> None:
    rendered = render_enriched_grounding_input(
        original_query="What improves MiniRAG recall?",
        solution_steps=["Identify recall failure.", "Map entities and relations."],
    )

    assert "Original query:" in rendered
    assert "What improves MiniRAG recall?" in rendered
    assert "Solution steps:" in rendered
    assert "1. Identify recall failure." in rendered
    assert "2. Map entities and relations." in rendered


def test_cot_grounding_instructions_do_not_request_entities_or_relations() -> None:
    assert "solution_steps" in COT_GROUNDING_INSTRUCTIONS
    assert '"entities"' not in COT_GROUNDING_INSTRUCTIONS
    assert '"relations"' not in COT_GROUNDING_INSTRUCTIONS
    assert "answer_type_keywords" not in COT_GROUNDING_INSTRUCTIONS
