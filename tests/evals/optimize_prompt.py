from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable

from deepeval.dataset import Golden
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.optimizer import PromptOptimizer
from deepeval.optimizer.algorithms import GEPA
from deepeval.prompt import Prompt

from ragflow_lite.domain.models import RetrievedChunk
from ragflow_lite.infrastructure.answerers.openai_responses import (
    ANSWERER_INSTRUCTIONS,
    OpenAIResponsesAnswerer,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDENS_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "synthetic_goldens.json"
)
DEFAULT_OUTPUT_PROMPT_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "optimized_answerer_prompt.txt"
)
DEFAULT_BASE_URL = "https://code.rayinai.com/v1"
DEFAULT_MODEL = "gpt-5.4-mini"


def load_goldens(path: Path) -> list[Golden]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("deepeval Goldens artifact must be a JSON array.")
    return [Golden.model_validate(item) for item in payload]


def build_prompt(text_template: str = ANSWERER_INSTRUCTIONS) -> Prompt:
    return Prompt(text_template=text_template)


def build_optimizer(
    *,
    judge_model: str,
    model_callback: Callable[[Prompt, Golden], str],
) -> PromptOptimizer:
    metrics = [
        AnswerRelevancyMetric(model=judge_model),
        FaithfulnessMetric(model=judge_model),
        ContextualRelevancyMetric(model=judge_model),
    ]
    return PromptOptimizer(
        model_callback=model_callback,
        metrics=metrics,
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
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--verbosity", default="medium")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key is None or not api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required for prompt optimization.")

    goldens = load_goldens(args.goldens)
    optimizer = build_optimizer(
        judge_model=args.judge_model,
        model_callback=build_model_callback(
            api_key=api_key,
            base_url=args.base_url,
            model=args.answer_model,
            reasoning_effort=args.reasoning_effort,
            verbosity=args.verbosity,
            store=False,
        ),
    )
    optimized_prompt = optimizer.optimize(
        prompt=build_prompt(),
        goldens=goldens,
    )

    prompt_text = optimized_prompt.text_template
    if prompt_text is None:
        raise RuntimeError("Optimized prompt does not contain a text_template.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(prompt_text, encoding="utf-8")
    print(
        json.dumps(
            {
                "goldens": len(goldens),
                "output": str(args.output),
                "optimization_id": getattr(
                    getattr(optimizer, "optimization_report", None),
                    "optimization_id",
                    None,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
