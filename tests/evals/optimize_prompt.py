from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Callable

from deepeval.dataset import Golden
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.models import DeepEvalBaseLLM
from deepeval.optimizer import PromptOptimizer
from deepeval.optimizer.algorithms import GEPA
from deepeval.prompt import Prompt
from eval_models import ArkResponsesDeepEvalModel

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.answerers.openai_responses import (
    OpenAIResponsesAnswerer,
    _load_packaged_template,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDENS_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "synthetic_goldens.json"
)
DEFAULT_OUTPUT_PROMPT_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "optimized_answerer_prompt.txt"
)
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "ep-20260423004926-v99zw"
DEFAULT_JUDGE_REASONING_EFFORT = "medium"
DEFAULT_OPTIMIZER_MODEL = "ep-20260423004926-v99zw"
DEFAULT_OPTIMIZER_REASONING_EFFORT = "medium"
DEFAULT_ITERATIONS = 5
DEFAULT_PARETO_SIZE = 3
DEFAULT_MINIBATCH_SIZE = 5
DEFAULT_RANDOM_SEED = 42


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_goldens(path: Path) -> list[Golden]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("deepeval Goldens artifact must be a JSON array.")
    normalized_payload = [_normalize_golden_payload(item) for item in payload]
    return [Golden.model_validate(item) for item in normalized_payload]


def _normalize_golden_payload(item: object) -> object:
    if not isinstance(item, dict):
        return item

    normalized = dict(item)
    retrieval_context = normalized.get("retrieval_context")
    if retrieval_context is None:
        retrieval_context = normalized.get("retrievalContext")

    if retrieval_context is None and normalized.get("context") is not None:
        normalized["retrieval_context"] = normalized["context"]

    return normalized


def validate_goldens(goldens: list[Golden]) -> None:
    """Validate all goldens have retrieval_context and expected_output."""
    deficient = []
    for index, golden in enumerate(goldens, start=1):
        label = golden.name or (
            golden.input[:40] if golden.input else f"golden-{index}"
        )
        missing = []
        if not golden.retrieval_context and not golden.context:
            missing.append("retrieval_context")
        if not golden.expected_output or not golden.expected_output.strip():
            missing.append("expected_output")
        if missing:
            deficient.append(f"  {label}: missing {', '.join(missing)}")

    if deficient:
        raise RuntimeError(
            "Goldens validation failed — the following goldens are deficient:\n"
            + "\n".join(deficient)
        )


def build_prompt(text_template: str | None = None) -> Prompt:
    if text_template is None:
        text_template = _load_packaged_template("plain")
    return Prompt(text_template=text_template)


def build_eval_model(
    *,
    api_key: str,
    model: str,
    base_url: str,
    reasoning_effort: str,
) -> ArkResponsesDeepEvalModel:
    return ArkResponsesDeepEvalModel(
        model=model,
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort,
    )


def _build_report(
    *,
    optimization_id: str,
    accepted_iterations: int,
    prompt_changed: bool,
    input_prompt_path: str,
    output_prompt_path: str,
    input_prompt_hash: str,
    output_prompt_hash: str,
) -> dict:
    return {
        "optimization_id": optimization_id,
        "best_id": None,
        "accepted_iterations": accepted_iterations,
        "prompt_configurations": [],
        "pareto_scores": [],
        "input_prompt_path": input_prompt_path,
        "output_prompt_path": output_prompt_path,
        "prompt_changed": prompt_changed,
        "input_prompt_hash": input_prompt_hash,
        "output_prompt_hash": output_prompt_hash,
    }


def _write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def build_optimizer(
    *,
    judge_model: str | DeepEvalBaseLLM,
    optimizer_model: str | DeepEvalBaseLLM,
    model_callback: Callable[[Prompt, Golden], str],
) -> PromptOptimizer:
    metrics = [
        AnswerRelevancyMetric(model=judge_model),
        FaithfulnessMetric(model=judge_model),
        ContextualRelevancyMetric(model=judge_model),
        ContextualPrecisionMetric(model=judge_model),
        ContextualRecallMetric(model=judge_model),
    ]
    return PromptOptimizer(
        model_callback=model_callback,
        metrics=metrics,
        optimizer_model=optimizer_model,
        algorithm=GEPA(),
    )


def build_model_callback(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    verbosity: str,
    store: bool,
) -> Callable[[Prompt, Golden], str]:
    def _callback(prompt: Prompt, golden: Golden) -> str:
        contexts = _contexts_from_golden(golden)
        instructions = prompt.interpolate(
            input=golden.input,
            question=golden.input,
            expected_output=golden.expected_output or "",
            source_file=golden.source_file or "",
        )
        answerer = OpenAIResponsesAnswerer(
            api_key=api_key,
            base_url=base_url,
            model=model,
            reasoning_effort=reasoning_effort,
            store=store,
            verbosity=verbosity,
            instructions=instructions,
        )
        return answerer.answer(golden.input, contexts).answer

    return _callback


def _contexts_from_golden(golden: Golden) -> list[RetrievedChunk]:
    texts = golden.retrieval_context or golden.context or []
    if not texts:
        raise RuntimeError(
            f"Golden '{golden.name or golden.input[:20]}' does not include context."
        )

    filename = Path(golden.source_file or "synthetic.md").name
    return [
        RetrievedChunk(
            chunk_id=f"golden-{index}",
            document_id=filename,
            text=text,
            score=float(len(texts) - index),
            metadata={"filename": filename, "file_type": "md"},
        )
        for index, text in enumerate(texts, start=1)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimize the answerer prompt with deepeval GEPA."
    )
    parser.add_argument("--goldens", type=Path, default=DEFAULT_GOLDENS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PROMPT_PATH)
    parser.add_argument("--judge-model", default=DEFAULT_MODEL)
    parser.add_argument("--answer-model", default=DEFAULT_MODEL)
    parser.add_argument("--optimizer-model", default=DEFAULT_OPTIMIZER_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--judge-reasoning-effort",
        default=DEFAULT_JUDGE_REASONING_EFFORT,
    )
    parser.add_argument(
        "--answer-reasoning-effort",
        "--reasoning-effort",
        dest="answer_reasoning_effort",
        default="medium",
    )
    parser.add_argument(
        "--optimizer-reasoning-effort",
        default=DEFAULT_OPTIMIZER_REASONING_EFFORT,
    )
    parser.add_argument("--verbosity", default="medium")

    # New CLI arguments
    parser.add_argument(
        "--input-prompt-path",
        type=Path,
        default=None,
        help="Path to a prompt file to optimize (defaults to packaged plain template).",
    )
    parser.add_argument(
        "--prompt-variant",
        choices=["citations", "plain"],
        default="plain",
        help="Packaged template to use as default input (default: plain).",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=None,
        required=False,
        help="Path to write a detailed JSON report.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help="Number of GEPA optimization iterations (default: 5).",
    )
    parser.add_argument(
        "--pareto-size",
        type=int,
        default=DEFAULT_PARETO_SIZE,
        help="GEPA pareto front size (default: 3).",
    )
    parser.add_argument(
        "--minibatch-size",
        type=int,
        default=DEFAULT_MINIBATCH_SIZE,
        help="GEPA minibatch size (default: 5).",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help="Random seed for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--allow-noop",
        action="store_true",
        default=False,
        help="Allow no-change results to be written as artifacts.",
    )

    args = parser.parse_args()

    api_key = os.getenv("ARK_API_KEY")
    if api_key is None or not api_key.strip():
        raise RuntimeError("ARK_API_KEY is required for prompt optimization.")

    # Determine input prompt text
    if args.input_prompt_path is not None:
        input_prompt_text = args.input_prompt_path.read_text(encoding="utf-8").strip()
    else:
        input_prompt_text = _load_packaged_template(args.prompt_variant)

    input_prompt_path_label = (
        str(args.input_prompt_path)
        if args.input_prompt_path
        else f"packaged:{args.prompt_variant}"
    )
    input_prompt_hash = _sha256_text(input_prompt_text)
    judge_model = build_eval_model(
        api_key=api_key,
        model=args.judge_model,
        base_url=args.base_url,
        reasoning_effort=args.judge_reasoning_effort,
    )
    optimizer_model = build_eval_model(
        api_key=api_key,
        model=args.optimizer_model,
        base_url=args.base_url,
        reasoning_effort=args.optimizer_reasoning_effort,
    )
    goldens = load_goldens(args.goldens)

    # Validate goldens before optimization
    validate_goldens(goldens)

    optimizer = build_optimizer(
        judge_model=judge_model,
        optimizer_model=optimizer_model,
        model_callback=build_model_callback(
            api_key=api_key,
            base_url=args.base_url,
            model=args.answer_model,
            reasoning_effort=args.answer_reasoning_effort,
            verbosity=args.verbosity,
            store=False,
        ),
    )
    optimized_prompt = optimizer.optimize(
        prompt=build_prompt(text_template=input_prompt_text),
        goldens=goldens,
    )

    prompt_text = optimized_prompt.text_template
    if prompt_text is None:
        raise RuntimeError("Optimized prompt does not contain a text_template.")

    output_prompt_hash = _sha256_text(prompt_text)
    prompt_changed = input_prompt_hash != output_prompt_hash

    # No-op handling
    if not prompt_changed:
        print("本次优化没有产生有效 prompt 改写")
        if args.report_output is not None:
            _write_report(
                _build_report(
                    optimization_id=str(uuid.uuid4()),
                    accepted_iterations=0,
                    prompt_changed=False,
                    input_prompt_path=input_prompt_path_label,
                    output_prompt_path=str(args.output),
                    input_prompt_hash=input_prompt_hash,
                    output_prompt_hash=output_prompt_hash,
                ),
                args.report_output,
            )
        if not args.allow_noop:
            sys.exit(1)
        return

    # Write optimized prompt
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(prompt_text, encoding="utf-8")

    # Build and write report JSON
    optimization_id = str(
        getattr(
            getattr(optimizer, "optimization_report", None),
            "optimization_id",
            None,
        )
        or uuid.uuid4()
    )

    if args.report_output is not None:
        _write_report(
            _build_report(
                optimization_id=optimization_id,
                accepted_iterations=args.iterations,
                prompt_changed=True,
                input_prompt_path=input_prompt_path_label,
                output_prompt_path=str(args.output),
                input_prompt_hash=input_prompt_hash,
                output_prompt_hash=output_prompt_hash,
            ),
            args.report_output,
        )

    print(
        json.dumps(
            {
                "goldens": len(goldens),
                "output": str(args.output),
                "optimization_id": optimization_id,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
