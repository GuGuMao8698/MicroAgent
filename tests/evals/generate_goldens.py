from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from deepeval.dataset import Golden
from deepeval.models import DeepEvalBaseEmbeddingModel
from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import ContextConstructionConfig
from eval_models import DeepSeekChatDeepEvalModel  # noqa: F401
from volcenginesdkarkruntime import Ark

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DOCS_DIR = PROJECT_ROOT / "网页" / "deepeval" / "eval集"
DEFAULT_TARGET_DOCS_DIR = PROJECT_ROOT / "tests" / "fixtures" / "documents"
DEFAULT_GOLDENS_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "synthetic_goldens.json"
)
DEFAULT_GOLDENS_PER_DOCUMENT = 10
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_REASONING_EFFORT = "high"
DEBUG_CONTEXT_ENV_VAR = "RAGFLOW_LITE_DEEPEVAL_CONTEXT_DEBUG"
DEFAULT_SYNTHESIZER_MAX_CONCURRENT = 30

LOGGER = logging.getLogger(__name__)


class ArkContextConstructionEmbeddingModel(DeepEvalBaseEmbeddingModel):
    """Use the repo's Ark embedding provider for deepeval context construction."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._dimensions = dimensions
        super().__init__(model=model)

    def load_model(self) -> Ark:
        return Ark(api_key=self._api_key)

    def embed_text(self, text: str) -> list[float]:
        return self._embed_text(text)

    async def a_embed_text(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_text, text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    async def a_embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_texts, texts)

    def get_model_name(self) -> str:
        return f"{self.name} (Ark)"

    def _embed_text(self, text: str) -> list[float]:
        request: dict[str, object] = {
            "input": [{"type": "text", "text": text}],
            "model": self.name,
        }
        if self._dimensions is not None:
            request["dimensions"] = self._dimensions

        response = self.model.multimodal_embeddings.create(**request)
        return self._normalize_vector(response.data.embedding)

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        normalized_source = [float(value) for value in vector]
        norm = sum(value * value for value in normalized_source) ** 0.5
        if norm == 0:
            return normalized_source
        return [value / norm for value in normalized_source]


def is_context_debug_enabled() -> bool:
    value = os.getenv(DEBUG_CONTEXT_ENV_VAR, "")
    return value.lower() in {"1", "true", "yes", "on"}


def describe_model(value: object | None) -> str:
    if value is None:
        return "None"

    get_model_name = getattr(value, "get_model_name", None)
    if callable(get_model_name):
        model_name = get_model_name()
        if isinstance(model_name, str) and model_name:
            return model_name

    name = getattr(value, "model_name", None)
    if isinstance(name, str) and name:
        return name

    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name

    return value.__class__.__name__


def emit_context_construction_debug_summary(
    *,
    document_path: Path,
    synthesis_path: Path,
    synthesizer_model: object | None,
    context_construction_config: ContextConstructionConfig | None,
) -> None:
    critic_model = None
    embedder = None
    if context_construction_config is not None:
        critic_model = context_construction_config.critic_model
        embedder = context_construction_config.embedder

    LOGGER.warning(
        "RAGFLOW_LITE_DEEPEVAL_DEBUG context_summary "
        "document=%s staged=%s synthesizer_model=%s "
        "context_critic_model=%s context_embedder=%s",
        document_path,
        synthesis_path,
        describe_model(synthesizer_model),
        describe_model(critic_model),
        describe_model(embedder),
    )


def install_context_construction_debug_hooks(
    context_generator_cls: type | None = None,
) -> None:
    if context_generator_cls is None:
        from deepeval.synthesizer.chunking.context_generator import ContextGenerator

        context_generator_cls = ContextGenerator

    original = getattr(
        context_generator_cls,
        "_a_get_n_random_contexts_per_source_file",
    )
    if getattr(original, "_ragflow_lite_context_debug_hook", False):
        return

    async def wrapped(
        self,
        path: str,
        n_contexts_per_source_file: int,
        context_size: int,
        similarity_threshold: float,
        source_files_to_collections_map: dict,
        progress=None,
        pbar_generate_contexts_id=None,
    ):
        contexts, scores = await original(
            self,
            path=path,
            n_contexts_per_source_file=n_contexts_per_source_file,
            context_size=context_size,
            similarity_threshold=similarity_threshold,
            source_files_to_collections_map=source_files_to_collections_map,
            progress=progress,
            pbar_generate_contexts_id=pbar_generate_contexts_id,
        )
        if context_size > 1 and n_contexts_per_source_file > 0 and not contexts:
            LOGGER.warning(
                "RAGFLOW_LITE_DEEPEVAL_DEBUG zero_contexts_after_expansion "
                "path=%s requested_contexts=%d context_size=%d "
                "scored_chunks=%d critic_model=%s embedder=%s",
                path,
                n_contexts_per_source_file,
                context_size,
                len(scores),
                describe_model(getattr(self, "model", None)),
                describe_model(getattr(self, "embedder", None)),
            )
        return contexts, scores

    setattr(wrapped, "_ragflow_lite_context_debug_hook", True)
    setattr(
        context_generator_cls,
        "_a_get_n_random_contexts_per_source_file",
        wrapped,
    )

    process_document_original = getattr(
        context_generator_cls,
        "_a_process_document_async",
    )
    if getattr(process_document_original, "_ragflow_lite_context_debug_hook", False):
        return

    async def wrapped_process_document(
        self,
        *,
        path: str,
        num_context_per_source_file: int,
        max_context_size: int,
        source_files_to_collections_map: dict,
        progress=None,
        pbar_generate_contexts_id=None,
    ):
        LOGGER.warning(
            "RAGFLOW_LITE_DEEPEVAL_DEBUG process_document_start "
            "path=%s requested_contexts=%d max_context_size=%d",
            path,
            num_context_per_source_file,
            max_context_size,
        )
        try:
            source_files, contexts, scores = await process_document_original(
                self,
                path=path,
                num_context_per_source_file=num_context_per_source_file,
                max_context_size=max_context_size,
                source_files_to_collections_map=source_files_to_collections_map,
                progress=progress,
                pbar_generate_contexts_id=pbar_generate_contexts_id,
            )
        except Exception:
            LOGGER.warning(
                "RAGFLOW_LITE_DEEPEVAL_DEBUG process_document_failed "
                "path=%s requested_contexts=%d max_context_size=%d",
                path,
                num_context_per_source_file,
                max_context_size,
                exc_info=True,
            )
            raise

        LOGGER.warning(
            "RAGFLOW_LITE_DEEPEVAL_DEBUG process_document_complete "
            "path=%s requested_contexts=%d max_context_size=%d "
            "returned_contexts=%d returned_scores=%d returned_source_files=%d",
            path,
            num_context_per_source_file,
            max_context_size,
            len(contexts),
            len(scores),
            len(source_files),
        )
        return source_files, contexts, scores

    setattr(wrapped_process_document, "_ragflow_lite_context_debug_hook", True)
    setattr(
        context_generator_cls,
        "_a_process_document_async",
        wrapped_process_document,
    )


def sync_eval_source_documents(
    source_dir: Path,
    target_dir: Path,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    source_docs = sorted(source_dir.glob("*.md"))

    copied_paths: list[Path] = []
    for source_path in source_docs:
        target_path = target_dir / source_path.name
        shutil.copy2(source_path, target_path)
        copied_paths.append(target_path)
    return copied_paths


def golden_to_payload(
    golden: Golden,
    *,
    document_fixture: str,
    top_k: int,
) -> dict[str, object]:
    payload = golden.model_dump(mode="json", by_alias=True, exclude_none=True)
    additional_metadata = payload.get("additionalMetadata")
    if not isinstance(additional_metadata, dict):
        additional_metadata = {}
    additional_metadata.update(
        {
            "document_fixture": document_fixture,
            "top_k": top_k,
        }
    )
    payload["additionalMetadata"] = additional_metadata
    payload["additional_metadata"] = dict(additional_metadata)
    payload["sourceFile"] = document_fixture
    payload["source_file"] = document_fixture
    expected_output = payload.get("expectedOutput")
    if isinstance(expected_output, str):
        payload["expected_output"] = expected_output
    return payload


def stage_document_for_synthesizer(
    document_path: Path,
    *,
    staging_dir: Path,
    sequence: int,
) -> Path:
    # deepeval reuses the input filename as part of a Chroma collection name.
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", document_path.stem).strip(".-_")
    if not safe_stem:
        safe_stem = "document"
    digest = hashlib.sha1(document_path.name.encode("utf-8")).hexdigest()[:8]
    staged_path = (
        staging_dir / f"{sequence:02d}-{safe_stem}-{digest}{document_path.suffix}"
    )
    shutil.copy2(document_path, staged_path)
    return staged_path


def generate_goldens_artifact(
    *,
    document_paths: Iterable[Path],
    output_path: Path,
    model: str | object | None = None,
    context_construction_config: ContextConstructionConfig | None = None,
    top_k: int = 4,
    goldens_per_document: int = DEFAULT_GOLDENS_PER_DOCUMENT,
) -> list[dict[str, object]]:
    context_debug_enabled = is_context_debug_enabled()
    if context_debug_enabled:
        install_context_construction_debug_hooks()

    synthesizer = Synthesizer(
        model=model,
        max_concurrent=DEFAULT_SYNTHESIZER_MAX_CONCURRENT,
    )
    payloads: list[dict[str, object]] = []
    staging_context = (
        TemporaryDirectory(prefix="deepeval-goldens-")
        if context_construction_config is not None
        else nullcontext(None)
    )

    with staging_context as staging_dir_name:
        staging_dir = Path(staging_dir_name) if staging_dir_name is not None else None
        for sequence, document_path in enumerate(document_paths, start=1):
            synthesis_path = document_path
            if staging_dir is not None:
                synthesis_path = stage_document_for_synthesizer(
                    document_path,
                    staging_dir=staging_dir,
                    sequence=sequence,
                )
            if context_debug_enabled:
                emit_context_construction_debug_summary(
                    document_path=document_path,
                    synthesis_path=synthesis_path,
                    synthesizer_model=model,
                    context_construction_config=context_construction_config,
                )

            goldens = synthesizer.generate_goldens_from_docs(
                [str(synthesis_path)],
                include_expected_output=True,
                max_goldens_per_context=goldens_per_document,
                context_construction_config=context_construction_config,
            )
            if len(goldens) > goldens_per_document:
                if context_debug_enabled:
                    LOGGER.warning(
                        "RAGFLOW_LITE_DEEPEVAL_DEBUG goldens_count_trimmed "
                        "document=%s staged=%s requested=%d actual=%d",
                        document_path,
                        synthesis_path,
                        goldens_per_document,
                        len(goldens),
                    )
                goldens = goldens[:goldens_per_document]
            if len(goldens) != goldens_per_document:
                if context_debug_enabled:
                    LOGGER.warning(
                        "RAGFLOW_LITE_DEEPEVAL_DEBUG goldens_count_mismatch "
                        "document=%s staged=%s expected=%d actual=%d",
                        document_path,
                        synthesis_path,
                        goldens_per_document,
                        len(goldens),
                    )
                raise RuntimeError(
                    f"{document_path.name} must produce exactly "
                    f"{goldens_per_document} goldens, got {len(goldens)}."
                )
            for index, golden in enumerate(goldens, start=1):
                payload = golden_to_payload(
                    golden,
                    document_fixture=document_path.name,
                    top_k=top_k,
                )
                payload.setdefault("name", f"{document_path.stem}-{index:03d}")
                payloads.append(payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payloads, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payloads


def build_synthesizer_model(
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> DeepSeekChatDeepEvalModel:
    return DeepSeekChatDeepEvalModel(
        model=model,
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort,
    )


def build_context_construction_config(
    *,
    api_key: str,
    model: str,
    critic_model: object,
    dimensions: int | None = None,
) -> ContextConstructionConfig:
    return ContextConstructionConfig(
        critic_model=critic_model,
        embedder=ArkContextConstructionEmbeddingModel(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync eval docs and generate deepeval Goldens artifact."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DOCS_DIR,
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=DEFAULT_TARGET_DOCS_DIR,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_GOLDENS_PATH,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--reasoning-effort",
        default=DEFAULT_REASONING_EFFORT,
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Defaults to ARK_EMBEDDING_MODEL.",
    )
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--goldens-per-document",
        type=int,
        default=DEFAULT_GOLDENS_PER_DOCUMENT,
    )
    args = parser.parse_args()

    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_api_key is None or not deepseek_api_key.strip():
        raise RuntimeError("DEEPSEEK_API_KEY is required for goldens generation.")
    ark_api_key = os.getenv("ARK_API_KEY")
    if ark_api_key is None or not ark_api_key.strip():
        raise RuntimeError("ARK_API_KEY is required for goldens generation.")
    ark_embedding_model = args.embedding_model or os.getenv("ARK_EMBEDDING_MODEL")
    if ark_embedding_model is None or not ark_embedding_model.strip():
        raise RuntimeError(
            "ARK_EMBEDDING_MODEL or --embedding-model is required for goldens generation."
        )

    synthesizer_model = build_synthesizer_model(
        api_key=deepseek_api_key,
        model=args.model,
        base_url=args.base_url,
        reasoning_effort=args.reasoning_effort,
    )

    copied_paths = sync_eval_source_documents(args.source_dir, args.target_dir)
    payloads = generate_goldens_artifact(
        document_paths=copied_paths,
        output_path=args.output,
        model=synthesizer_model,
        context_construction_config=build_context_construction_config(
            api_key=ark_api_key,
            model=ark_embedding_model,
            critic_model=synthesizer_model,
        ),
        top_k=args.top_k,
        goldens_per_document=args.goldens_per_document,
    )
    print(
        json.dumps(
            {
                "documents": [path.name for path in copied_paths],
                "goldens": len(payloads),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
