from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from deepeval.models import DeepEvalBaseLLM, GPTModel
    from deepeval.test_case import LLMTestCase

_PLACEHOLDER_ENV_VALUES = {
    "test-openai-api-key",
    "test-ark-api-key",
    "ep-test-model",
}
_DEFAULT_DEEPEVAL_MODEL = "gpt-5.4-mini"
_DEFAULT_DEEPEVAL_BASE_URL = "https://code.rayinai.com/v1"
_LEADING_JSON_PREFIX_RE = re.compile(r"^\s*json\s*:\s*", re.IGNORECASE)
_CITATION_BRACKETS_RE = re.compile(r"\[\d+\]")


@dataclass(frozen=True, slots=True)
class RagEvalCase:
    name: str
    document_fixture: str
    question: str
    expected_output: str | None = None
    top_k: int = 4

    @property
    def has_reference(self) -> bool:
        return self.expected_output is not None


_EVAL_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "evals"
_RAG_EVAL_GOLDENS_PATH = _EVAL_FIXTURES_DIR / "synthetic_goldens.json"


def ensure_rag_eval_cases_use_markdown_fixtures(cases: list[RagEvalCase]) -> None:
    non_markdown_fixtures = sorted(
        {
            case.document_fixture
            for case in cases
            if Path(case.document_fixture).suffix.lower() != ".md"
        }
    )
    if non_markdown_fixtures:
        fixture_list = ", ".join(non_markdown_fixtures)
        raise RuntimeError(
            f"deepeval seed dataset currently supports markdown fixtures only: {fixture_list}"
        )


def _load_rag_eval_cases() -> list[RagEvalCase]:
    payload = json.loads(_RAG_EVAL_GOLDENS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("deepeval goldens artifact must be a JSON array.")

    cases = [
        _case_from_golden_payload(item, index=index)
        for index, item in enumerate(payload, start=1)
    ]
    ensure_rag_eval_cases_use_markdown_fixtures(cases)
    return cases


def _case_from_golden_payload(item: Any, *, index: int) -> RagEvalCase:
    if not isinstance(item, Mapping):
        raise RuntimeError(f"deepeval golden payload #{index} must be an object.")

    name = _coerce_optional_string(item.get("name")) or f"golden-{index:03d}"
    question = _coerce_required_string(
        item.get("input"), field_name="input", index=index
    )
    expected_output = _coerce_optional_string(
        item.get("expectedOutput", item.get("expected_output"))
    )
    additional_metadata = item.get(
        "additionalMetadata", item.get("additional_metadata")
    )
    if additional_metadata is None:
        additional_metadata = {}
    if not isinstance(additional_metadata, Mapping):
        raise RuntimeError(
            f"deepeval golden payload #{index} additionalMetadata must be an object."
        )

    document_fixture = _coerce_optional_string(
        additional_metadata.get("document_fixture")
    ) or _coerce_optional_string(item.get("sourceFile", item.get("source_file")))
    if document_fixture is None:
        raise RuntimeError(
            f"deepeval golden payload #{index} must include sourceFile or "
            "additionalMetadata.document_fixture."
        )

    top_k_value = additional_metadata.get("top_k", 4)
    if not isinstance(top_k_value, int) or top_k_value <= 0:
        raise RuntimeError(
            f"deepeval golden payload #{index} additionalMetadata.top_k "
            "must be a positive integer."
        )

    return RagEvalCase(
        name=name,
        document_fixture=Path(document_fixture).name,
        question=question,
        expected_output=expected_output,
        top_k=top_k_value,
    )


def _coerce_required_string(value: Any, *, field_name: str, index: int) -> str:
    text = _coerce_optional_string(value)
    if text is None:
        raise RuntimeError(
            f"deepeval golden payload #{index} field '{field_name}' must be a non-empty string."
        )
    return text


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


RAG_EVAL_CASES = _load_rag_eval_cases()


def is_live_infinity_enabled(
    marker_names: set[str],
    *,
    run_live_infinity: bool,
) -> bool:
    return run_live_infinity or bool({"live_infinity", "deepeval"} & marker_names)


def validate_deepeval_env(env: Mapping[str, str | None]) -> None:
    required = ("OPENAI_API_KEY", "ARK_API_KEY", "ARK_EMBEDDING_MODEL")
    missing_or_placeholder = [
        name
        for name in required
        if (value := env.get(name)) is None or value.strip() in _PLACEHOLDER_ENV_VALUES
    ]
    if missing_or_placeholder:
        missing_list = ", ".join(missing_or_placeholder)
        raise RuntimeError(
            f"deepeval requires real runtime configuration for: {missing_list}."
        )


def build_deepeval_judge_model(env: Mapping[str, str | None]) -> GPTModel:
    from deepeval.models import GPTModel

    api_key = env.get("OPENAI_API_KEY")
    if api_key is None or api_key.strip() in _PLACEHOLDER_ENV_VALUES:
        raise RuntimeError(
            "deepeval judge model requires a real OPENAI_API_KEY-compatible credential."
        )

    model_name = env.get("DEEPEVAL_MODEL") or _DEFAULT_DEEPEVAL_MODEL
    base_url = env.get("DEEPEVAL_BASE_URL") or _DEFAULT_DEEPEVAL_BASE_URL
    return GPTModel(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )


def build_rag_test_case(
    *,
    case: RagEvalCase,
    actual_output: str,
    retrieval_context: list[str],
) -> LLMTestCase:
    from deepeval.test_case import LLMTestCase

    kwargs: dict = dict(
        name=case.name,
        input=case.question,
        actual_output=_normalize_eval_output(actual_output),
        retrieval_context=retrieval_context,
    )
    if case.expected_output is not None:
        kwargs["expected_output"] = case.expected_output
    return LLMTestCase(**kwargs)


def _normalize_eval_output(actual_output: str) -> str:
    text = actual_output.strip()
    text = _LEADING_JSON_PREFIX_RE.sub("", text).strip()

    parsed = _try_parse_wrapped_json_string(text)
    if parsed is not None:
        text = parsed

    text = _CITATION_BRACKETS_RE.sub("", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _try_parse_wrapped_json_string(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        for key in ("answer", "actual_output", "output", "response"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value
    return None


def build_triad_metrics(model: str | DeepEvalBaseLLM) -> list:
    """Default referenceless RAG triad: AnswerRelevancy + Faithfulness + ContextualRelevancy."""
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
    )

    return [
        AnswerRelevancyMetric(model=model),
        FaithfulnessMetric(model=model),
        ContextualRelevancyMetric(model=model),
    ]


def build_reference_based_metrics(model: str | DeepEvalBaseLLM) -> list:
    """Reference-based retrieval metrics: ContextualPrecision + ContextualRecall."""
    from deepeval.metrics import (
        ContextualPrecisionMetric,
        ContextualRecallMetric,
    )

    return [
        ContextualPrecisionMetric(model=model),
        ContextualRecallMetric(model=model),
    ]


def build_metrics_for_case(
    case: RagEvalCase,
    model: str | DeepEvalBaseLLM,
) -> list:
    """Return triad metrics, plus reference-based metrics if case has expected_output."""
    metrics = build_triad_metrics(model)
    if case.has_reference:
        metrics.extend(build_reference_based_metrics(model))
    return metrics
