from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

PRIVATE_BOOTSTRAP_FIXTURE_NAME = "microrag-private-bootstrap.md"
PRIVATE_BOOTSTRAP_SNAPSHOT_DIR = "microrag-private-bootstrap-snapshot"
PRIVATE_BOOTSTRAP_DRAFT_GOLDENS = "private_bootstrap_goldens.draft.json"
AUTHORITY_RULE = "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior."


class CorpusRole(StrEnum):
    AUTHORITATIVE = "authoritative"
    DISTRACTOR = "distractor"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    original_path: str
    snapshot_path: str
    role: str
    topic: str
    status: str
    sha256: str


def normalize_relative_path(path: Path) -> str:
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def classify_corpus_path(path: Path) -> CorpusRole | None:
    relative_path = normalize_relative_path(path)

    excluded_prefixes = (
        "参考项目/",
        "tests/fixtures/documents/",
        "data/uploads/",
        "src/ragflow_lite/microagent/",
    )
    if relative_path.startswith(excluded_prefixes):
        return None

    name = path.name
    if name.startswith("MinerU_markdown_"):
        return None
    if name in {"prompt生成与优化指南.md", "context7.md"}:
        return None

    if name in {"AGENTS.md", "CONTRACTS.md"} and (
        relative_path == name
        or relative_path.startswith(
            ("src/ragflow_lite/", "tests/", "docker/"),
        )
    ):
        return CorpusRole.AUTHORITATIVE

    if (
        relative_path.startswith(
            ("docs/superpowers/specs/", "docs/superpowers/plans/"),
        )
        and path.suffix == ".md"
    ):
        return CorpusRole.DISTRACTOR

    return None


def discover_corpus_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and classify_corpus_path(path.relative_to(root)) is not None
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
