from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Iterable

from deepeval.dataset import Golden
from deepeval.synthesizer import Synthesizer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DOCS_DIR = PROJECT_ROOT / "网页" / "deepeval" / "eval集"
DEFAULT_TARGET_DOCS_DIR = PROJECT_ROOT / "tests" / "fixtures" / "documents"
DEFAULT_GOLDENS_PATH = (
    PROJECT_ROOT / "tests" / "fixtures" / "evals" / "synthetic_goldens.json"
)
DEFAULT_GOLDENS_PER_DOCUMENT = 10


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


def generate_goldens_artifact(
    *,
    document_paths: Iterable[Path],
    output_path: Path,
    model: str | None = None,
    top_k: int = 4,
    goldens_per_document: int = DEFAULT_GOLDENS_PER_DOCUMENT,
) -> list[dict[str, object]]:
    synthesizer = Synthesizer(model=model)
    payloads: list[dict[str, object]] = []

    for document_path in document_paths:
        goldens = synthesizer.generate_goldens_from_docs(
            [str(document_path)],
            include_expected_output=True,
            max_goldens_per_context=goldens_per_document,
        )
        if len(goldens) != goldens_per_document:
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
    parser.add_argument("--model", default=None)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--goldens-per-document",
        type=int,
        default=DEFAULT_GOLDENS_PER_DOCUMENT,
    )
    args = parser.parse_args()

    copied_paths = sync_eval_source_documents(args.source_dir, args.target_dir)
    payloads = generate_goldens_artifact(
        document_paths=copied_paths,
        output_path=args.output,
        model=args.model,
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
