from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Mapping

PRIVATE_BOOTSTRAP_FIXTURE_NAME = "microrag-private-bootstrap.md"
PRIVATE_BOOTSTRAP_SNAPSHOT_DIR = "microrag-private-bootstrap-snapshot"
PRIVATE_BOOTSTRAP_DRAFT_GOLDENS = "private_bootstrap_goldens.draft.json"
AUTHORITY_RULE = "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior."
EXPECTED_CASE_COUNTS: Mapping[str, int] = {
    "current_contract_qa": 8,
    "multi_doc_synthesis": 4,
    "stale_plan_trap": 4,
    "negative_missing_evidence": 2,
    "comparison": 2,
}


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


def _metadata_for_case(
    item: Mapping[str, object], *, index: int
) -> Mapping[str, object]:
    metadata = item.get("additionalMetadata", item.get("additional_metadata"))
    if not isinstance(metadata, Mapping):
        raise RuntimeError(
            f"private bootstrap case #{index} must include additionalMetadata."
        )
    return metadata


def _source_list(
    metadata: Mapping[str, object], field_name: str, *, index: int
) -> list[str]:
    if field_name not in metadata:
        return []
    value = metadata[field_name]
    if not isinstance(value, list):
        raise RuntimeError(
            f"private bootstrap case #{index} {field_name} must be a list of strings."
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise RuntimeError(
            f"private bootstrap case #{index} {field_name} must contain non-empty strings."
        )
    return [item for item in value if isinstance(item, str) and item.strip()]


def _require_text(item: Mapping[str, object], key: str, *, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(
            f"private bootstrap case #{index} must include non-empty {key}."
        )
    return value


def _is_authoritative_source(path: str) -> bool:
    return classify_corpus_path(Path(path)) is CorpusRole.AUTHORITATIVE


def _is_allowed_distractor(path: str) -> bool:
    return classify_corpus_path(Path(path)) is CorpusRole.DISTRACTOR


def _validate_source_file(item: Mapping[str, object], *, index: int) -> None:
    values = [
        value
        for key in ("sourceFile", "source_file")
        if (value := item.get(key)) is not None
    ]
    if not values:
        raise RuntimeError(f"private bootstrap case #{index} must include sourceFile.")
    if any(value != PRIVATE_BOOTSTRAP_FIXTURE_NAME for value in values):
        raise RuntimeError(
            f"private bootstrap case #{index} sourceFile must be {PRIVATE_BOOTSTRAP_FIXTURE_NAME}."
        )


def _validate_corpus_fixture(metadata: Mapping[str, object], *, index: int) -> None:
    if metadata.get("corpus_fixture") != PRIVATE_BOOTSTRAP_SNAPSHOT_DIR:
        raise RuntimeError(
            f"private bootstrap case #{index} corpus_fixture must be "
            f"{PRIVATE_BOOTSTRAP_SNAPSHOT_DIR}."
        )


def _validate_manifest_membership(
    *,
    sources: Iterable[str],
    manifest_paths: set[str] | None,
    index: int,
) -> None:
    if manifest_paths is None:
        return
    for source in sources:
        if source not in manifest_paths:
            raise RuntimeError(
                f"private bootstrap case #{index} source is missing from snapshot manifest: "
                f"{source}"
            )


def validate_goldens_payload(
    payload: object,
    *,
    manifest_entries: Iterable[ManifestEntry] | None = None,
) -> None:
    if not isinstance(payload, list):
        raise RuntimeError("private bootstrap goldens must be a JSON array.")
    if len(payload) != sum(EXPECTED_CASE_COUNTS.values()):
        raise RuntimeError("private bootstrap goldens must contain exactly 20 cases.")

    manifest_paths = (
        {entry.original_path for entry in manifest_entries}
        if manifest_entries is not None
        else None
    )
    counts: dict[str, int] = {case_type: 0 for case_type in EXPECTED_CASE_COUNTS}
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, Mapping):
            raise RuntimeError(f"private bootstrap case #{index} must be an object.")
        _require_text(item, "name", index=index)
        _require_text(item, "input", index=index)
        _require_text(item, "expected_output", index=index)
        _validate_source_file(item, index=index)
        metadata = _metadata_for_case(item, index=index)

        document_fixture = metadata.get("document_fixture")
        if document_fixture != PRIVATE_BOOTSTRAP_FIXTURE_NAME:
            raise RuntimeError(
                f"private bootstrap case #{index} must use {PRIVATE_BOOTSTRAP_FIXTURE_NAME}."
            )
        _validate_corpus_fixture(metadata, index=index)
        if metadata.get("authority_rule") != AUTHORITY_RULE:
            raise RuntimeError(
                f"private bootstrap case #{index} has invalid authority_rule."
            )
        top_k = metadata.get("top_k")
        if type(top_k) is not int or top_k <= 0:
            raise RuntimeError(
                f"private bootstrap case #{index} must include positive top_k."
            )
        case_type = metadata.get("case_type")
        if not isinstance(case_type, str) or case_type not in EXPECTED_CASE_COUNTS:
            raise RuntimeError(
                f"private bootstrap case #{index} has unsupported case_type."
            )
        counts[case_type] += 1

        required_sources = _source_list(
            metadata, "required_authoritative_sources", index=index
        )
        distractor_sources = _source_list(metadata, "distractor_sources", index=index)
        _validate_manifest_membership(
            sources=required_sources + distractor_sources,
            manifest_paths=manifest_paths,
            index=index,
        )
        for source in required_sources:
            if not _is_authoritative_source(source):
                raise RuntimeError(
                    f"private bootstrap case #{index} required source is not an "
                    f"authoritative source: {source}"
                )
        for source in distractor_sources:
            if not _is_allowed_distractor(source):
                raise RuntimeError(
                    f"private bootstrap case #{index} distractor source is not allowed: "
                    f"{source}"
                )

        if case_type != "negative_missing_evidence" and not required_sources:
            raise RuntimeError(
                f"private bootstrap case #{index} needs an authoritative source."
            )
        if case_type == "multi_doc_synthesis" and len(required_sources) < 2:
            raise RuntimeError(
                f"private bootstrap case #{index} needs at least two authoritative sources."
            )
        if case_type == "stale_plan_trap" and not distractor_sources:
            raise RuntimeError(
                f"private bootstrap case #{index} needs a distractor source."
            )
        if case_type == "negative_missing_evidence":
            if metadata.get("answerability") != "unanswerable":
                raise RuntimeError(
                    f"private bootstrap case #{index} must be unanswerable."
                )
            acceptable_refusal = metadata.get("acceptable_refusal")
            if (
                not isinstance(acceptable_refusal, str)
                or not acceptable_refusal.strip()
            ):
                raise RuntimeError(
                    f"private bootstrap case #{index} needs acceptable_refusal."
                )

    if counts != dict(EXPECTED_CASE_COUNTS):
        raise RuntimeError(
            "private bootstrap case distribution must be "
            f"{dict(EXPECTED_CASE_COUNTS)}, got {counts}."
        )


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

        role_dir = (
            "authoritative" if role is CorpusRole.AUTHORITATIVE else "distractors"
        )
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
