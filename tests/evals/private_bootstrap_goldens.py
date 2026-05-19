from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

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


def snapshot_filename(relative_path: str) -> str:
    return relative_path.replace("/", "__")


def infer_status(text: str, *, role: CorpusRole) -> str:
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.lower().startswith("status:"):
            return stripped.split(":", 1)[1].strip() or "unknown"
    if role is CorpusRole.AUTHORITATIVE:
        return "active"
    return "historical"


def infer_topic(relative_path: str) -> str:
    path = Path(relative_path)
    if path.name in {"AGENTS.md", "CONTRACTS.md"}:
        parent = path.parent.as_posix()
        return "root" if parent == "." else parent
    return path.stem


def write_manifest(snapshot_root: Path, entries: list[ManifestEntry]) -> None:
    payload = {
        "dataset": "microrag-private-bootstrap",
        "entries": [asdict(entry) for entry in entries],
    }
    (snapshot_root / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_manifest(snapshot_root: Path) -> list[ManifestEntry]:
    payload = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise RuntimeError("private bootstrap manifest must contain entries.")
    return [ManifestEntry(**entry) for entry in raw_entries]


def validate_snapshot_root(*, repo_root: Path, snapshot_root: Path) -> Path:
    repo_root_resolved = repo_root.resolve()
    snapshot_root_resolved = snapshot_root.resolve()
    documents_root = repo_root_resolved / "tests" / "fixtures" / "documents"
    if (
        snapshot_root_resolved == repo_root_resolved
        or snapshot_root_resolved.name != PRIVATE_BOOTSTRAP_SNAPSHOT_DIR
        or not snapshot_root_resolved.is_relative_to(documents_root)
    ):
        raise RuntimeError(
            "Unsafe private bootstrap snapshot root: "
            f"{snapshot_root_resolved.as_posix()}"
        )
    return snapshot_root_resolved


def create_snapshot(
    *,
    repo_root: Path,
    source_paths: Iterable[Path],
    snapshot_root: Path,
) -> list[ManifestEntry]:
    repo_root_resolved = repo_root.resolve()
    snapshot_root_resolved = validate_snapshot_root(
        repo_root=repo_root_resolved,
        snapshot_root=snapshot_root,
    )

    snapshots: list[tuple[Path, str, CorpusRole, str]] = []
    seen_targets: dict[str, str] = {}
    for source_path in sorted(
        source_paths,
        key=lambda path: path.resolve().relative_to(repo_root_resolved).as_posix(),
    ):
        relative_path = normalize_relative_path(
            source_path.resolve().relative_to(repo_root_resolved)
        )
        role = classify_corpus_path(Path(relative_path))
        if role is None:
            continue

        role_dir = "authoritative" if role is CorpusRole.AUTHORITATIVE else "distractors"
        target_relative = f"{role_dir}/{snapshot_filename(relative_path)}"
        previous_path = seen_targets.get(target_relative)
        if previous_path is not None:
            raise RuntimeError(
                "Snapshot filename collision: "
                f"{previous_path} and {relative_path} both map to {target_relative}"
            )
        seen_targets[target_relative] = relative_path
        snapshots.append((source_path, relative_path, role, target_relative))

    if snapshot_root_resolved.exists():
        shutil.rmtree(snapshot_root_resolved)
    (snapshot_root_resolved / "authoritative").mkdir(parents=True, exist_ok=True)
    (snapshot_root_resolved / "distractors").mkdir(parents=True, exist_ok=True)

    entries: list[ManifestEntry] = []
    for source_path, relative_path, role, target_relative in snapshots:
        target_path = snapshot_root_resolved / target_relative
        shutil.copy2(source_path, target_path)
        text = source_path.read_text(encoding="utf-8")
        entries.append(
            ManifestEntry(
                original_path=relative_path,
                snapshot_path=target_relative,
                role=role.value,
                topic=infer_topic(relative_path),
                status=infer_status(text, role=role),
                sha256=sha256_file(target_path),
            )
        )

    write_manifest(snapshot_root_resolved, entries)
    return entries


def build_packed_fixture(*, snapshot_root: Path, fixture_path: Path) -> None:
    entries = load_manifest(snapshot_root)
    parts = [
        "# MicroRAG Private Bootstrap Corpus",
        "",
        "This fixture is generated from a frozen corpus snapshot.",
        "Use source headers and manifest metadata to preserve authority boundaries.",
        "",
    ]
    for entry in entries:
        source_text = (snapshot_root / entry.snapshot_path).read_text(encoding="utf-8")
        parts.extend(
            [
                f"# Source: {entry.original_path}",
                "",
                f"Role: {entry.role}",
                f"Status: {entry.status}",
                f"Topic: {entry.topic}",
                f"SHA256: {entry.sha256}",
                "",
                source_text.rstrip(),
                "",
            ]
        )

    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
