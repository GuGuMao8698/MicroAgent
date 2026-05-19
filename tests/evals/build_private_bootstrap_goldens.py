from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

try:
    from private_bootstrap_goldens import (
        PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
        PRIVATE_BOOTSTRAP_FIXTURE_NAME,
        PRIVATE_BOOTSTRAP_SNAPSHOT_DIR,
        build_packed_fixture,
        create_snapshot,
        discover_corpus_paths,
        validate_goldens_payload,
    )
except ModuleNotFoundError:
    from evals.private_bootstrap_goldens import (
        PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
        PRIVATE_BOOTSTRAP_FIXTURE_NAME,
        PRIVATE_BOOTSTRAP_SNAPSHOT_DIR,
        build_packed_fixture,
        create_snapshot,
        discover_corpus_paths,
        validate_goldens_payload,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_private_bootstrap_payload(payload: object) -> object:
    if not isinstance(payload, list):
        return payload
    normalized_payload = []
    for item in payload:
        if not isinstance(item, dict):
            normalized_payload.append(item)
            continue
        normalized = dict(item)
        metadata = normalized.get(
            "additionalMetadata", normalized.get("additional_metadata")
        )
        if isinstance(metadata, dict):
            normalized_metadata = dict(metadata)
            normalized_metadata.setdefault(
                "corpus_fixture", PRIVATE_BOOTSTRAP_SNAPSHOT_DIR
            )
            normalized_metadata.setdefault(
                "document_fixture", PRIVATE_BOOTSTRAP_FIXTURE_NAME
            )
            normalized["additionalMetadata"] = normalized_metadata
            normalized["additional_metadata"] = dict(normalized_metadata)
        normalized.setdefault("sourceFile", PRIVATE_BOOTSTRAP_FIXTURE_NAME)
        normalized.setdefault("source_file", PRIVATE_BOOTSTRAP_FIXTURE_NAME)
        normalized_payload.append(normalized)
    return normalized_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and validate the MicroRAG private bootstrap golden inputs."
    )
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--draft-goldens",
        type=Path,
        default=PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "evals"
        / PRIVATE_BOOTSTRAP_DRAFT_GOLDENS,
    )
    parser.add_argument(
        "--output-goldens",
        type=Path,
        default=None,
        help="Optional output path. If omitted, only validates the draft artifact.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    snapshot_root = (
        repo_root / "tests" / "fixtures" / "documents" / PRIVATE_BOOTSTRAP_SNAPSHOT_DIR
    )
    fixture_path = (
        repo_root / "tests" / "fixtures" / "documents" / PRIVATE_BOOTSTRAP_FIXTURE_NAME
    )

    source_paths = discover_corpus_paths(repo_root)
    entries = create_snapshot(
        repo_root=repo_root,
        source_paths=source_paths,
        snapshot_root=snapshot_root,
    )
    build_packed_fixture(snapshot_root=snapshot_root, fixture_path=fixture_path)

    draft_payload = normalize_private_bootstrap_payload(
        json.loads(args.draft_goldens.read_text(encoding="utf-8"))
    )
    validate_goldens_payload(draft_payload, manifest_entries=entries)
    if args.output_goldens is not None:
        args.output_goldens.parent.mkdir(parents=True, exist_ok=True)
        args.output_goldens.write_text(
            json.dumps(draft_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "snapshot": str(snapshot_root),
                "fixture": str(fixture_path),
                "sources": len(entries),
                "draft_goldens": str(args.draft_goldens),
                "output_goldens": str(args.output_goldens)
                if args.output_goldens is not None
                else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
