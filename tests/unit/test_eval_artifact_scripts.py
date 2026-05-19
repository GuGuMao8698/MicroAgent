from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from pydantic import BaseModel

pytest.importorskip("deepeval")

from deepeval.dataset import Golden  # noqa: E402
from deepeval.metrics.utils import initialize_model  # noqa: E402
from evals.cleanup_infinity import select_eval_cleanup_tables  # noqa: E402
from evals.eval_models import DeepSeekChatDeepEvalModel  # noqa: E402
from evals.generate_goldens import (
    DEFAULT_GOLDENS_PATH,
    ArkContextConstructionEmbeddingModel,
    build_context_construction_config,
    build_synthesizer_model,
    emit_context_construction_debug_summary,
    generate_goldens_artifact,
    golden_to_payload,
    install_context_construction_debug_hooks,
    sync_eval_source_documents,
)
from evals.optimize_prompt import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    _sha256_text,
    build_eval_model,
    build_optimizer,
    load_goldens,
    main,
    validate_goldens,
)
from evals.private_bootstrap_goldens import (  # noqa: E402
    AUTHORITY_RULE,
    CorpusRole,
    ManifestEntry,
    classify_corpus_path,
    discover_corpus_paths,
)

_EXPECTED_EVAL_SOURCE_FILES = {
    "Best Practices for Claude Code.md": 10,
    "CodexBestpractices.md": 10,
    "Faithfulness.md": 10,
    "MinerU_markdown_603260_20260417_2LSZ.md": 10,
    "MinerU_markdown_中华人民共和国劳动法.md": 10,
    "MinerU_markdown_附件1：《期货公司监督管理办法（征求意见稿）》.md": 10,
}


def test_private_bootstrap_classifies_allowed_and_excluded_paths() -> None:
    assert classify_corpus_path(Path("AGENTS.md")) == CorpusRole.AUTHORITATIVE
    assert (
        classify_corpus_path(Path("src/ragflow_lite/CONTRACTS.md"))
        == CorpusRole.AUTHORITATIVE
    )
    assert (
        classify_corpus_path(Path("tests/evals/AGENTS.md")) == CorpusRole.AUTHORITATIVE
    )
    assert (
        classify_corpus_path(Path("docs/superpowers/specs/2026-05-18-example.md"))
        == CorpusRole.DISTRACTOR
    )
    assert (
        classify_corpus_path(Path("docs/superpowers/plans/2026-05-19-example.md"))
        == CorpusRole.DISTRACTOR
    )

    assert classify_corpus_path(Path("参考项目/网页/deepeval/Faithfulness.md")) is None
    assert classify_corpus_path(Path("tests/fixtures/documents/sample.md")) is None
    assert classify_corpus_path(Path("data/uploads/doc.md")) is None
    assert classify_corpus_path(Path("src/ragflow_lite/microagent/README.md")) is None


def test_private_bootstrap_discovers_only_allowed_corpus_paths(
    tmp_path: Path,
) -> None:
    files = {
        "AGENTS.md": "# root agents\n",
        "src/ragflow_lite/CONTRACTS.md": "# contract\n",
        "tests/evals/AGENTS.md": "# eval agents\n",
        "docs/superpowers/specs/2026-05-18-a.md": "# spec\n",
        "docs/superpowers/plans/2026-05-19-b.md": "# plan\n",
        "参考项目/网页/deepeval/Faithfulness.md": "# public docs\n",
        "tests/fixtures/documents/sample.md": "# old fixture\n",
        "src/ragflow_lite/microagent/README.md": "# mixed authority\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    discovered = [
        path.relative_to(tmp_path).as_posix()
        for path in discover_corpus_paths(tmp_path)
    ]

    assert discovered == [
        "AGENTS.md",
        "docs/superpowers/plans/2026-05-19-b.md",
        "docs/superpowers/specs/2026-05-18-a.md",
        "src/ragflow_lite/CONTRACTS.md",
        "tests/evals/AGENTS.md",
    ]


def test_private_bootstrap_creates_frozen_snapshot_manifest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    root_agents = root / "AGENTS.md"
    authoritative = root / "tests" / "evals" / "CONTRACTS.md"
    distractor = root / "docs" / "superpowers" / "plans" / "2026-05-19-plan.md"
    authoritative.parent.mkdir(parents=True)
    distractor.parent.mkdir(parents=True)
    root_agents.write_text("# Working Agreements\n", encoding="utf-8")
    authoritative.write_text(
        "# Eval Contracts\n\nActive eval rules.\n", encoding="utf-8"
    )
    distractor.write_text(
        "# Historical Plan\n\nStatus: Ready for implementation after confirmation\n",
        encoding="utf-8",
    )

    snapshot_root = (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
    )

    from evals.private_bootstrap_goldens import create_snapshot

    entries = create_snapshot(
        repo_root=root,
        source_paths=[authoritative, distractor, root_agents],
        snapshot_root=snapshot_root,
    )

    assert [entry.role for entry in entries] == [
        "authoritative",
        "distractor",
        "authoritative",
    ]
    assert (snapshot_root / "manifest.json").exists()
    manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["original_path"] for entry in manifest["entries"]] == [
        "AGENTS.md",
        "docs/superpowers/plans/2026-05-19-plan.md",
        "tests/evals/CONTRACTS.md",
    ]
    assert manifest["entries"][0]["topic"] == "root"
    assert (snapshot_root / "authoritative" / "tests__evals__CONTRACTS.md").read_text(
        encoding="utf-8"
    ) == "# Eval Contracts\n\nActive eval rules.\n"
    assert (
        snapshot_root / "distractors" / "docs__superpowers__plans__2026-05-19-plan.md"
    ).exists()


def test_private_bootstrap_builds_packed_fixture_from_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    authoritative = root / "AGENTS.md"
    distractor = root / "docs" / "superpowers" / "specs" / "2026-05-18-spec.md"
    distractor.parent.mkdir(parents=True)
    authoritative.write_text(
        "# Working Agreements\n\nUse root cause fixes.\n",
        encoding="utf-8",
    )
    distractor.write_text(
        "# Draft Spec\n\nStatus: Draft design spec\n",
        encoding="utf-8",
    )
    snapshot_root = (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
    )

    from evals.private_bootstrap_goldens import build_packed_fixture, create_snapshot

    create_snapshot(
        repo_root=root,
        source_paths=[authoritative, distractor],
        snapshot_root=snapshot_root,
    )
    fixture_path = (
        root / "tests" / "fixtures" / "documents" / "microrag-private-bootstrap.md"
    )

    build_packed_fixture(snapshot_root=snapshot_root, fixture_path=fixture_path)

    text = fixture_path.read_text(encoding="utf-8")
    assert "# MicroRAG Private Bootstrap Corpus" in text
    assert "# Source: AGENTS.md" in text
    assert "Role: authoritative" in text
    assert "# Source: docs/superpowers/specs/2026-05-18-spec.md" in text
    assert "Role: distractor" in text
    assert "Use root cause fixes." in text
    assert "Status: Draft design spec" in text


def test_private_bootstrap_rejects_unsafe_snapshot_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "AGENTS.md"
    source.write_text("# Working Agreements\n", encoding="utf-8")
    unsafe_snapshot_root = tmp_path / "outside" / "microrag-private-bootstrap-snapshot"
    unsafe_snapshot_root.mkdir(parents=True)
    sentinel = unsafe_snapshot_root / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    from evals.private_bootstrap_goldens import create_snapshot

    with pytest.raises(RuntimeError, match="Unsafe private bootstrap snapshot root"):
        create_snapshot(
            repo_root=root,
            source_paths=[source],
            snapshot_root=unsafe_snapshot_root,
        )

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_private_bootstrap_rejects_snapshot_filename_collisions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source_a = root / "docs" / "superpowers" / "plans" / "a__b.md"
    source_b = root / "docs" / "superpowers" / "plans" / "a" / "b.md"
    source_a.parent.mkdir(parents=True)
    source_b.parent.mkdir(parents=True)
    source_a.write_text("# Plan A\n", encoding="utf-8")
    source_b.write_text("# Plan B\n", encoding="utf-8")
    snapshot_root = (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
    )

    from evals.private_bootstrap_goldens import create_snapshot

    with pytest.raises(RuntimeError, match="Snapshot filename collision"):
        create_snapshot(
            repo_root=root,
            source_paths=[source_a, source_b],
            snapshot_root=snapshot_root,
        )


def _private_bootstrap_case(
    *,
    name: str,
    case_type: str,
    answerability: str = "answerable",
    required_sources: list[str] | None = None,
    distractor_sources: list[str] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "document_fixture": "microrag-private-bootstrap.md",
        "top_k": 6,
        "case_type": case_type,
        "authority_rule": "Only CONTRACTS.md and AGENTS.md may justify current runtime behavior.",
        "required_authoritative_sources": required_sources or ["AGENTS.md"],
        "distractor_sources": distractor_sources or [],
        "answerability": answerability,
    }
    if case_type == "multi_doc_synthesis":
        metadata["required_authoritative_sources"] = required_sources or [
            "AGENTS.md",
            "tests/evals/CONTRACTS.md",
        ]
        metadata["why_multi_doc"] = "Requires root workflow and eval contract."
    if case_type == "stale_plan_trap":
        metadata["distractor_sources"] = distractor_sources or [
            "docs/superpowers/specs/2026-05-18-example.md"
        ]
        metadata["why_not_answer_from_distractor"] = (
            "The distractor is planning material, not an active contract."
        )
    if case_type == "negative_missing_evidence":
        metadata["answerability"] = "unanswerable"
        metadata["required_authoritative_sources"] = []
        metadata["acceptable_refusal"] = (
            "The authoritative MicroRAG documents in this eval corpus do not establish that."
        )
    return {
        "name": name,
        "input": f"Question for {name}?",
        "expected_output": "Answer grounded in authoritative sources.",
        "context": ["Source context."],
        "sourceFile": "microrag-private-bootstrap.md",
        "additionalMetadata": metadata,
    }


def _private_bootstrap_payload() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    payload.extend(
        _private_bootstrap_case(
            name=f"current-{index}", case_type="current_contract_qa"
        )
        for index in range(8)
    )
    payload.extend(
        _private_bootstrap_case(name=f"multi-{index}", case_type="multi_doc_synthesis")
        for index in range(4)
    )
    payload.extend(
        _private_bootstrap_case(name=f"stale-{index}", case_type="stale_plan_trap")
        for index in range(4)
    )
    payload.extend(
        _private_bootstrap_case(
            name=f"negative-{index}", case_type="negative_missing_evidence"
        )
        for index in range(2)
    )
    payload.extend(
        _private_bootstrap_case(
            name=f"comparison-{index}",
            case_type="comparison",
            required_sources=["AGENTS.md"],
            distractor_sources=["docs/superpowers/plans/2026-05-19-plan.md"],
        )
        for index in range(2)
    )
    return payload


def _private_bootstrap_manifest_entries() -> list[ManifestEntry]:
    return [
        ManifestEntry(
            original_path=original_path,
            snapshot_path=f"snapshot/{index}.md",
            role="authoritative",
            topic="test",
            status="active",
            sha256=f"sha256-{index}",
        )
        for index, original_path in enumerate(
            [
                "AGENTS.md",
                "tests/evals/CONTRACTS.md",
                "docs/superpowers/specs/2026-05-18-example.md",
                "docs/superpowers/plans/2026-05-19-plan.md",
            ],
            start=1,
        )
    ]


def test_private_bootstrap_cli_builds_snapshot_fixture_and_validates_draft(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("# Root\n\nRoot rule.\n", encoding="utf-8")
    contracts = root / "tests" / "evals" / "CONTRACTS.md"
    spec = root / "docs" / "superpowers" / "specs" / "2026-05-18-example.md"
    plan = root / "docs" / "superpowers" / "plans" / "2026-05-19-plan.md"
    contracts.parent.mkdir(parents=True)
    spec.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    contracts.write_text("# Eval Contract\n\nActive eval rule.\n", encoding="utf-8")
    spec.write_text(
        "# Spec\n\nStatus: Draft design spec\n",
        encoding="utf-8",
    )
    plan.write_text(
        "# Plan\n\nStatus: Ready for implementation after confirmation\n",
        encoding="utf-8",
    )
    draft = root / "tests" / "fixtures" / "evals" / "private_bootstrap_goldens.draft.json"
    draft.parent.mkdir(parents=True)
    cases = []
    cases.extend(
        _private_bootstrap_case(name=f"current-{index}", case_type="current_contract_qa")
        for index in range(8)
    )
    cases.extend(
        _private_bootstrap_case(name=f"multi-{index}", case_type="multi_doc_synthesis")
        for index in range(4)
    )
    cases.extend(
        _private_bootstrap_case(name=f"stale-{index}", case_type="stale_plan_trap")
        for index in range(4)
    )
    cases.extend(
        _private_bootstrap_case(
            name=f"negative-{index}", case_type="negative_missing_evidence"
        )
        for index in range(2)
    )
    cases.extend(
        _private_bootstrap_case(
            name=f"comparison-{index}",
            case_type="comparison",
            distractor_sources=["docs/superpowers/plans/2026-05-19-plan.md"],
        )
        for index in range(2)
    )
    draft.write_text(json.dumps(cases), encoding="utf-8")

    from evals.build_private_bootstrap_goldens import main

    main(["--repo-root", str(root), "--draft-goldens", str(draft)])

    assert (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap.md"
    ).exists()
    assert (
        root
        / "tests"
        / "fixtures"
        / "documents"
        / "microrag-private-bootstrap-snapshot"
        / "manifest.json"
    ).exists()


def test_private_bootstrap_validation_accepts_expected_case_distribution() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    validate_goldens_payload(_private_bootstrap_payload())


def test_private_bootstrap_validation_accepts_manifest_sources() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    validate_goldens_payload(
        _private_bootstrap_payload(),
        manifest_entries=_private_bootstrap_manifest_entries(),
    )


def test_private_bootstrap_validation_rejects_source_missing_from_manifest() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    entries = [
        entry
        for entry in _private_bootstrap_manifest_entries()
        if entry.original_path != "tests/evals/CONTRACTS.md"
    ]

    with pytest.raises(RuntimeError, match="snapshot manifest"):
        validate_goldens_payload(
            _private_bootstrap_payload(),
            manifest_entries=entries,
        )


def test_private_bootstrap_validation_rejects_wrong_or_missing_source_file() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    wrong_source_payload = _private_bootstrap_payload()
    wrong_source_payload[0]["sourceFile"] = "other.md"

    with pytest.raises(RuntimeError, match="sourceFile"):
        validate_goldens_payload(wrong_source_payload)

    missing_source_payload = _private_bootstrap_payload()
    missing_source_payload[0].pop("sourceFile")

    with pytest.raises(RuntimeError, match="sourceFile"):
        validate_goldens_payload(missing_source_payload)


def test_private_bootstrap_validation_rejects_malformed_required_sources() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = _private_bootstrap_payload()
    payload[0]["additionalMetadata"]["required_authoritative_sources"] = [
        "AGENTS.md",
        123,
    ]

    with pytest.raises(RuntimeError, match="required_authoritative_sources"):
        validate_goldens_payload(payload)


def test_private_bootstrap_validation_rejects_wrong_authority_rule() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = _private_bootstrap_payload()
    payload[0]["additionalMetadata"]["authority_rule"] = f"{AUTHORITY_RULE} Extra."

    with pytest.raises(RuntimeError, match="authority_rule"):
        validate_goldens_payload(payload)


def test_private_bootstrap_validation_rejects_stale_plan_only_answer_source() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = [
        _private_bootstrap_case(
            name=f"current-{index}",
            case_type="current_contract_qa",
        )
        for index in range(20)
    ]
    payload[0]["additionalMetadata"]["required_authoritative_sources"] = [
        "docs/superpowers/specs/2026-05-18-example.md"
    ]

    with pytest.raises(RuntimeError, match="authoritative source"):
        validate_goldens_payload(payload)


def test_private_bootstrap_validation_rejects_boolean_top_k() -> None:
    from evals.private_bootstrap_goldens import validate_goldens_payload

    payload = _private_bootstrap_payload()
    payload[0]["additionalMetadata"]["top_k"] = True

    with pytest.raises(RuntimeError, match="positive top_k"):
        validate_goldens_payload(payload)


def test_sync_eval_source_documents_copies_markdown_files_only(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    (source_dir / "keep.md").write_text("# keep\n", encoding="utf-8")
    (source_dir / "skip.txt").write_text("skip\n", encoding="utf-8")

    copied = sync_eval_source_documents(source_dir, target_dir)

    assert [path.name for path in copied] == ["keep.md"]
    assert (target_dir / "keep.md").read_text(encoding="utf-8") == "# keep\n"
    assert not (target_dir / "skip.txt").exists()


def test_sync_eval_source_documents_preserves_unmanaged_markdown_files(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / "managed.md").write_text("# managed from source\n", encoding="utf-8")
    (target_dir / "managed.md").write_text("# stale managed copy\n", encoding="utf-8")
    (target_dir / "shared-fixture.md").write_text(
        "# unrelated shared fixture\n",
        encoding="utf-8",
    )

    copied = sync_eval_source_documents(source_dir, target_dir)

    assert [path.name for path in copied] == ["managed.md"]
    assert (target_dir / "managed.md").read_text(encoding="utf-8") == (
        "# managed from source\n"
    )
    assert (target_dir / "shared-fixture.md").read_text(encoding="utf-8") == (
        "# unrelated shared fixture\n"
    )


def test_golden_to_payload_preserves_eval_fixture_metadata() -> None:
    golden = Golden(
        input="what is the policy",
        expected_output="Use the checked-in fixture copy.",
        source_file="/tmp/Best Practices for Claude Code.md",
        name="case-1",
        context=["ctx-1"],
    )

    payload = golden_to_payload(
        golden,
        document_fixture="Best Practices for Claude Code.md",
        top_k=6,
    )

    assert payload["input"] == "what is the policy"
    assert payload["expectedOutput"] == "Use the checked-in fixture copy."
    assert payload["expected_output"] == "Use the checked-in fixture copy."
    assert payload["context"] == ["ctx-1"]
    assert payload["sourceFile"] == "Best Practices for Claude Code.md"
    assert payload["source_file"] == "Best Practices for Claude Code.md"
    assert payload["additionalMetadata"] == {
        "document_fixture": "Best Practices for Claude Code.md",
        "top_k": 6,
    }
    assert payload["additional_metadata"] == {
        "document_fixture": "Best Practices for Claude Code.md",
        "top_k": 6,
    }


def test_checked_in_goldens_artifact_loads_via_prompt_consumer() -> None:
    goldens = load_goldens(DEFAULT_GOLDENS_PATH)

    assert len(goldens) == 60
    assert all(golden.input.strip() for golden in goldens)
    assert all(
        golden.expected_output and golden.expected_output.strip() for golden in goldens
    )
    assert all(
        golden.source_file and golden.source_file.endswith(".md") for golden in goldens
    )
    assert all(golden.context for golden in goldens)


def test_checked_in_goldens_artifact_mirrors_context_into_retrieval_context() -> None:
    goldens = load_goldens(DEFAULT_GOLDENS_PATH)

    assert all(golden.retrieval_context for golden in goldens)
    assert all(golden.retrieval_context == golden.context for golden in goldens)


def test_checked_in_goldens_artifact_has_exactly_ten_per_source_document() -> None:
    goldens = load_goldens(DEFAULT_GOLDENS_PATH)
    counts = Counter(golden.source_file for golden in goldens if golden.source_file)

    assert counts == _EXPECTED_EVAL_SOURCE_FILES


def test_generate_goldens_artifact_requires_exactly_ten_per_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "doc.md"
    document_path.write_text("# doc\n", encoding="utf-8")

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            self.model = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            assert doc_paths == [str(document_path)]
            assert include_expected_output is True
            assert max_goldens_per_context == 10
            assert context_construction_config is None
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=document_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 10)
            ]

    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    with pytest.raises(RuntimeError, match="exactly 10 goldens"):
        generate_goldens_artifact(
            document_paths=[document_path],
            output_path=tmp_path / "goldens.json",
        )


def test_generate_goldens_artifact_trims_extra_goldens_to_requested_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "doc.md"
    document_path.write_text("# doc\n", encoding="utf-8")

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            self.model = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            assert doc_paths == [str(document_path)]
            assert include_expected_output is True
            assert max_goldens_per_context == 10
            assert context_construction_config is None
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=document_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 31)
            ]

    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    payloads = generate_goldens_artifact(
        document_paths=[document_path],
        output_path=tmp_path / "goldens.json",
    )

    assert len(payloads) == 10
    assert [payload["input"] for payload in payloads] == [
        f"question {index}" for index in range(1, 11)
    ]


def test_generate_goldens_artifact_limits_synthesizer_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "doc.md"
    document_path.write_text("# doc\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            captured["model"] = model
            captured["max_concurrent"] = max_concurrent

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=document_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 11)
            ]

    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    generate_goldens_artifact(
        document_paths=[document_path],
        output_path=tmp_path / "goldens.json",
    )

    assert captured["max_concurrent"] == 30


def test_generate_goldens_artifact_forwards_context_construction_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "doc.md"
    document_path.write_text("# doc\n", encoding="utf-8")
    captured: dict[str, object] = {}
    context_config = object()

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            captured["model"] = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            captured["context_construction_config"] = context_construction_config
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=document_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 11)
            ]

    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    generate_goldens_artifact(
        document_paths=[document_path],
        output_path=tmp_path / "goldens.json",
        context_construction_config=context_config,
    )

    assert captured["context_construction_config"] is context_config


def test_generate_goldens_artifact_sanitizes_staged_doc_name_for_context_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "Best Practices for Claude Code.md"
    document_path.write_text("# doc\n", encoding="utf-8")
    context_config = object()
    captured: dict[str, object] = {}

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            captured["model"] = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            staged_path = Path(doc_paths[0])
            captured["staged_path"] = staged_path
            assert include_expected_output is True
            assert max_goldens_per_context == 10
            assert context_construction_config is context_config
            assert staged_path.suffix == ".md"
            assert " " not in staged_path.name
            assert staged_path.read_text(encoding="utf-8") == document_path.read_text(
                encoding="utf-8"
            )
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=staged_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 11)
            ]

    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    payloads = generate_goldens_artifact(
        document_paths=[document_path],
        output_path=tmp_path / "goldens.json",
        context_construction_config=context_config,
    )

    staged_path = captured["staged_path"]
    assert isinstance(staged_path, Path)
    assert staged_path.name != document_path.name
    assert payloads[0]["sourceFile"] == document_path.name
    assert payloads[0]["additionalMetadata"]["document_fixture"] == document_path.name


def test_build_context_construction_config_wraps_ark_embedder() -> None:
    critic_model = build_synthesizer_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )
    config = build_context_construction_config(
        api_key="ark-key",
        model="ep-embedding",
        dimensions=1024,
        critic_model=critic_model,
    )

    assert isinstance(config.embedder, ArkContextConstructionEmbeddingModel)
    assert config.embedder.name == "ep-embedding"
    assert config.embedder.get_model_name() == "ep-embedding (Ark)"
    assert config.critic_model is critic_model
    assert config.critic_model.get_model_name() == "deepseek-v4-flash"


def test_build_context_construction_config_keeps_custom_critic_model_for_deepeval() -> (
    None
):
    critic_model = build_synthesizer_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    config = build_context_construction_config(
        api_key="ark-key",
        model="ep-embedding",
        critic_model=critic_model,
    )

    initialized_model, using_native_model = initialize_model(config.critic_model)

    assert initialized_model is config.critic_model
    assert using_native_model is False


def test_build_synthesizer_model_passes_reasoning_effort_generation_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeDeepSeekChatDeepEvalModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "evals.generate_goldens.DeepSeekChatDeepEvalModel",
        FakeDeepSeekChatDeepEvalModel,
    )

    synthesizer_model = build_synthesizer_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    assert synthesizer_model.__class__ is FakeDeepSeekChatDeepEvalModel
    assert captured == {
        "model": "deepseek-v4-flash",
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com",
        "reasoning_effort": "high",
    }


def test_generate_goldens_artifact_passes_native_synthesizer_model_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_path = tmp_path / "doc.md"
    document_path.write_text("# doc\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeDeepSeekChatDeepEvalModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def get_model_name(self) -> str:
            return self.kwargs["model"]

    class FakeSynthesizer:
        def __init__(self, model=None, max_concurrent=None):
            captured["model"] = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
            context_construction_config,
        ):
            return [
                Golden(
                    name=f"doc-{index:03d}",
                    input=f"question {index}",
                    expected_output=f"answer {index}",
                    source_file=document_path.name,
                    context=[f"context {index}"],
                )
                for index in range(1, 11)
            ]

    monkeypatch.setattr(
        "evals.generate_goldens.DeepSeekChatDeepEvalModel",
        FakeDeepSeekChatDeepEvalModel,
    )
    monkeypatch.setattr("evals.generate_goldens.Synthesizer", FakeSynthesizer)

    synthesizer_model = build_synthesizer_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    generate_goldens_artifact(
        document_paths=[document_path],
        output_path=tmp_path / "goldens.json",
        model=synthesizer_model,
    )

    assert captured["model"] is synthesizer_model


def test_deepseek_deepeval_model_sends_chat_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = "plain response"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["openai_kwargs"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    result = model.generate("hello")

    assert result == "plain response"
    assert captured["openai_kwargs"] == {
        "api_key": "deepseek-key",
        "base_url": "https://api.deepseek.com",
        "timeout": 300.0,
    }
    assert captured["create_kwargs"] == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def test_deepseek_deepeval_model_validates_schema_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result(BaseModel):
        answer: str

    class FakeMessage:
        content = '{"answer": "ok"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    result = model.generate("Score the answer.", schema=Result)

    assert result == Result(answer="ok")
    request = captured["create_kwargs"]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 262144
    prompt = request["messages"][0]["content"]
    assert "Score the answer." in prompt
    assert "Return only one JSON object" in prompt
    assert "json" in prompt.lower()
    assert '"answer"' in prompt


def test_deepseek_deepeval_plain_generation_does_not_request_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessage:
        content = "plain response"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    assert model.generate("hello") == "plain response"
    assert "response_format" not in captured["create_kwargs"]
    assert "max_tokens" not in captured["create_kwargs"]


def test_deepseek_deepeval_model_validates_async_schema_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Result(BaseModel):
        answer: str

    class FakeMessage:
        content = '{"answer": "async ok"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeChatCompletions:
        async def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletion()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr("evals.eval_models.OpenAI", FakeOpenAI)
    monkeypatch.setattr("evals.eval_models.AsyncOpenAI", FakeOpenAI)

    model = DeepSeekChatDeepEvalModel(
        api_key="deepseek-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    result = asyncio.run(model.a_generate("Score async.", schema=Result))

    assert result == Result(answer="async ok")
    request = captured["create_kwargs"]
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 262144
    prompt = request["messages"][0]["content"]
    assert "Score async." in prompt
    assert "Return only one JSON object" in prompt
    assert '"answer"' in prompt


def test_emit_context_construction_debug_summary_logs_effective_models(
    caplog: pytest.LogCaptureFixture,
) -> None:
    synthesizer_model = build_synthesizer_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )
    context_config = build_context_construction_config(
        api_key="ark-key",
        model="ep-embedding",
        critic_model=synthesizer_model,
    )

    with caplog.at_level("WARNING"):
        emit_context_construction_debug_summary(
            document_path=Path(
                "tests/fixtures/documents/Best Practices for Claude Code.md"
            ),
            synthesis_path=Path("/tmp/01-Best-Practices.md"),
            synthesizer_model=synthesizer_model,
            context_construction_config=context_config,
        )

    assert "synthesizer_model=deepseek-v4-flash" in caplog.text
    assert "context_critic_model=deepseek-v4-flash" in caplog.text
    assert "context_embedder=ep-embedding (Ark)" in caplog.text


def test_install_context_construction_debug_hooks_logs_zero_contexts_after_expansion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeModel:
        name = "gpt-4.1"

    class FakeEmbedder:
        def get_model_name(self) -> str:
            return "ep-embedding (Ark)"

    class FakeContextGenerator:
        def __init__(self) -> None:
            self.model = FakeModel()
            self.embedder = FakeEmbedder()

        async def _a_get_n_random_contexts_per_source_file(
            self,
            path: str,
            n_contexts_per_source_file: int,
            context_size: int,
            similarity_threshold: float,
            source_files_to_collections_map: dict,
            progress=None,
            pbar_generate_contexts_id=None,
        ):
            return [], [0.91, 0.73]

        async def _a_process_document_async(
            self,
            *,
            path: str,
            num_context_per_source_file: int,
            max_context_size: int,
            source_files_to_collections_map: dict,
            progress=None,
            pbar_generate_contexts_id=None,
        ):
            return [path], [], [0.91, 0.73]

    install_context_construction_debug_hooks(FakeContextGenerator)

    with caplog.at_level("WARNING"):
        asyncio.run(
            FakeContextGenerator()._a_get_n_random_contexts_per_source_file(
                path="tests/fixtures/documents/Best Practices for Claude Code.md",
                n_contexts_per_source_file=3,
                context_size=3,
                similarity_threshold=0.5,
                source_files_to_collections_map={},
            )
        )

    assert "zero_contexts_after_expansion" in caplog.text
    assert "critic_model=gpt-4.1" in caplog.text
    assert "embedder=ep-embedding (Ark)" in caplog.text


def test_install_context_construction_debug_hooks_logs_process_document_completion(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeContextGenerator:
        async def _a_get_n_random_contexts_per_source_file(self, **kwargs):
            return [["ctx-1"], ["ctx-2"]], [0.91, 0.73]

        async def _a_process_document_async(
            self,
            *,
            path: str,
            num_context_per_source_file: int,
            max_context_size: int,
            source_files_to_collections_map: dict,
            progress=None,
            pbar_generate_contexts_id=None,
        ):
            return [path], [["ctx-1"], ["ctx-2"]], [0.91, 0.73]

    install_context_construction_debug_hooks(FakeContextGenerator)

    with caplog.at_level("WARNING"):
        asyncio.run(
            FakeContextGenerator()._a_process_document_async(
                path="tests/fixtures/documents/Best Practices for Claude Code.md",
                num_context_per_source_file=3,
                max_context_size=3,
                source_files_to_collections_map={},
            )
        )

    assert "process_document_start" in caplog.text
    assert "process_document_complete" in caplog.text
    assert "returned_contexts=2" in caplog.text
    assert "returned_scores=2" in caplog.text


def test_install_context_construction_debug_hooks_logs_process_document_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeContextGenerator:
        async def _a_get_n_random_contexts_per_source_file(self, **kwargs):
            return [["ctx-1"]], [0.91]

        async def _a_process_document_async(
            self,
            *,
            path: str,
            num_context_per_source_file: int,
            max_context_size: int,
            source_files_to_collections_map: dict,
            progress=None,
            pbar_generate_contexts_id=None,
        ):
            raise RuntimeError("boom")

    install_context_construction_debug_hooks(FakeContextGenerator)

    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(
                FakeContextGenerator()._a_process_document_async(
                    path="tests/fixtures/documents/Best Practices for Claude Code.md",
                    num_context_per_source_file=3,
                    max_context_size=3,
                    source_files_to_collections_map={},
                )
            )

    assert "process_document_start" in caplog.text
    assert "process_document_failed" in caplog.text


def test_build_optimizer_uses_gepa_and_five_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    judge_model = object()
    optimizer_model = object()

    class FakeGEPA:
        pass

    class FakePromptOptimizer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("evals.optimize_prompt.GEPA", FakeGEPA)
    monkeypatch.setattr("evals.optimize_prompt.PromptOptimizer", FakePromptOptimizer)
    monkeypatch.setattr(
        "evals.optimize_prompt.AnswerRelevancyMetric",
        lambda model: ("AnswerRelevancyMetric", model),
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.FaithfulnessMetric",
        lambda model: ("FaithfulnessMetric", model),
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.ContextualRelevancyMetric",
        lambda model: ("ContextualRelevancyMetric", model),
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.ContextualPrecisionMetric",
        lambda model: ("ContextualPrecisionMetric", model),
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.ContextualRecallMetric",
        lambda model: ("ContextualRecallMetric", model),
    )

    build_optimizer(
        judge_model=judge_model,
        optimizer_model=optimizer_model,
        model_callback=lambda prompt, golden: "",
    )

    assert captured["algorithm"].__class__ is FakeGEPA
    assert captured["optimizer_model"] is optimizer_model
    assert captured["metrics"] == [
        ("AnswerRelevancyMetric", judge_model),
        ("FaithfulnessMetric", judge_model),
        ("ContextualRelevancyMetric", judge_model),
        ("ContextualPrecisionMetric", judge_model),
        ("ContextualRecallMetric", judge_model),
    ]


def test_build_eval_model_uses_explicit_openai_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeDeepSeekChatDeepEvalModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "evals.optimize_prompt.DeepSeekChatDeepEvalModel",
        FakeDeepSeekChatDeepEvalModel,
    )

    model = build_eval_model(
        api_key="test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        reasoning_effort="high",
    )

    assert model.__class__ is FakeDeepSeekChatDeepEvalModel
    assert captured == {
        "model": "deepseek-v4-flash",
        "api_key": "test-key",
        "base_url": "https://api.deepseek.com",
        "reasoning_effort": "high",
    }


def test_main_defaults_optimizer_to_deepseek_high(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    captured: dict[str, object] = {}
    calls: dict[str, object] = {}
    judge_model = object()
    optimizer_model = object()
    model_callback = object()
    prompt = object()
    goldens = ["golden"]

    class FakeOptimizer:
        optimization_report = type(
            "OptimizationReport",
            (),
            {"optimization_id": "opt-123"},
        )()

        def optimize(self, *, prompt, goldens):
            captured["prompt"] = prompt
            captured["goldens"] = goldens
            return type("OptimizedPrompt", (), {"text_template": "optimized"})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["optimize_prompt.py", "--output", str(output_path)],
    )
    eval_model_call_count = 0

    def _fake_build_eval_model(**kwargs):
        nonlocal eval_model_call_count
        eval_model_call_count += 1
        if eval_model_call_count == 1:
            calls["judge_model_kwargs"] = kwargs
            return judge_model
        calls["optimizer_model_kwargs"] = kwargs
        return optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _fake_build_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: calls.update({"goldens_path": path}) or goldens,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: "packaged-plain-template",
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_prompt",
        lambda **kwargs: calls.update({"build_prompt_kwargs": kwargs}) or prompt,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: (
            calls.update({"model_callback_kwargs": kwargs}) or model_callback
        ),
    )

    def fake_build_optimizer(**kwargs):
        calls["build_optimizer_kwargs"] = kwargs
        return FakeOptimizer()

    monkeypatch.setattr("evals.optimize_prompt.build_optimizer", fake_build_optimizer)

    main()

    assert calls["judge_model_kwargs"] == {
        "api_key": "test-key",
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "reasoning_effort": "high",
    }
    assert calls["optimizer_model_kwargs"] == {
        "api_key": "test-key",
        "model": "deepseek-v4-flash",
        "base_url": DEFAULT_BASE_URL,
        "reasoning_effort": "high",
    }
    assert calls["build_optimizer_kwargs"] == {
        "judge_model": judge_model,
        "optimizer_model": optimizer_model,
        "model_callback": model_callback,
    }
    assert calls["model_callback_kwargs"] == {
        "api_key": "test-key",
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "reasoning_effort": "high",
    }
    assert calls["build_prompt_kwargs"] == {
        "text_template": "packaged-plain-template",
    }
    assert captured == {"prompt": prompt, "goldens": goldens}
    assert output_path.read_text(encoding="utf-8") == "optimized"


def test_generate_goldens_main_uses_deepseek_llm_and_ark_embedding_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    output_path = tmp_path / "goldens.json"
    source_dir.mkdir()
    target_dir.mkdir()
    calls: dict[str, object] = {}

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-embedding")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_goldens.py",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--output",
            str(output_path),
        ],
    )
    monkeypatch.setattr(
        "evals.generate_goldens.sync_eval_source_documents",
        lambda source_dir, target_dir: (
            calls.update(
                {
                    "sync_source_dir": source_dir,
                    "sync_target_dir": target_dir,
                }
            )
            or [target_dir / "doc.md"]
        ),
    )
    monkeypatch.setattr(
        "evals.generate_goldens.build_synthesizer_model",
        lambda **kwargs: calls.update({"synth_kwargs": kwargs}) or "synth-model",
    )
    monkeypatch.setattr(
        "evals.generate_goldens.build_context_construction_config",
        lambda **kwargs: calls.update({"context_kwargs": kwargs}) or "context-config",
    )
    monkeypatch.setattr(
        "evals.generate_goldens.generate_goldens_artifact",
        lambda **kwargs: calls.update({"generate_kwargs": kwargs}) or [],
    )

    from evals.generate_goldens import main as gg_main

    gg_main()

    assert calls["synth_kwargs"] == {
        "api_key": "deepseek-key",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "reasoning_effort": "high",
    }
    assert calls["context_kwargs"] == {
        "api_key": "ark-key",
        "model": "ep-embedding",
        "critic_model": "synth-model",
    }
    assert calls["generate_kwargs"] == {
        "document_paths": [target_dir / "doc.md"],
        "output_path": output_path,
        "model": "synth-model",
        "context_construction_config": "context-config",
        "top_k": 4,
        "goldens_per_document": 10,
    }


def test_select_eval_cleanup_tables_targets_eval_residue() -> None:
    assert select_eval_cleanup_tables(
        [
            "documents",
            "chunks",
            "documents_datasets",
            "documents_dataset_bindings",
            "documents_liveeval",
            "chunks_liveeval",
            "graph_entities_liveeval",
            "graph_relationships_liveeval",
            "test_legacy_doc_abcd_datasets",
            "test_legacy_chunk_abcd",
            "other_table",
        ]
    ) == [
        "chunks",
        "chunks_liveeval",
        "documents",
        "documents_dataset_bindings",
        "documents_datasets",
        "documents_liveeval",
        "graph_entities_liveeval",
        "graph_relationships_liveeval",
        "test_legacy_chunk_abcd",
        "test_legacy_doc_abcd_datasets",
    ]


# --- optimize_prompt: golden validation tests ---


def test_validate_goldens_passes_when_all_fields_present() -> None:
    goldens = [
        Golden(
            input="q1",
            expected_output="a1",
            context=["ctx-1"],
            name="case-1",
        ),
        Golden(
            input="q2",
            expected_output="a2",
            context=["ctx-2"],
            name="case-2",
        ),
    ]
    # Should not raise
    validate_goldens(goldens)


def test_validate_goldens_fails_on_missing_retrieval_context() -> None:
    goldens = [
        Golden(
            input="q1",
            expected_output="a1",
            context=[],
            name="case-no-context",
        ),
    ]
    with pytest.raises(RuntimeError, match="Goldens validation failed"):
        validate_goldens(goldens)


def test_validate_goldens_fails_on_missing_expected_output() -> None:
    goldens = [
        Golden(
            input="q1",
            expected_output="",
            context=["ctx-1"],
            name="case-no-output",
        ),
    ]
    with pytest.raises(RuntimeError, match="Goldens validation failed"):
        validate_goldens(goldens)


def test_validate_goldens_lists_all_deficient_goldens() -> None:
    goldens = [
        Golden(
            input="q1",
            expected_output="",
            context=[],
            name="bad-1",
        ),
        Golden(
            input="q2",
            expected_output="a2",
            context=["ctx"],
            name="good-1",
        ),
        Golden(
            input="q3",
            expected_output="a3",
            context=[],
            name="bad-2",
        ),
    ]
    with pytest.raises(RuntimeError, match=r"bad-1[\s\S]*bad-2") as exc_info:
        validate_goldens(goldens)
    msg = str(exc_info.value)
    assert "bad-1" in msg
    assert "bad-2" in msg
    assert "good-1" not in msg


# --- optimize_prompt: no-op detection tests ---


def test_main_noop_exits_nonzero_without_allow_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    input_prompt_text = "original-prompt"
    judge_model = object()
    optimizer_model = object()
    model_callback = object()
    goldens = ["golden"]

    class FakeOptimizer:
        def optimize(self, *, prompt, goldens):
            # Return same text as input -> no-op
            return type("OptimizedPrompt", (), {"text_template": input_prompt_text})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["optimize_prompt.py", "--output", str(output_path)],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: input_prompt_text,
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: goldens,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    # Output file should NOT have been written
    assert not output_path.exists()


def test_main_noop_with_allow_noop_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    input_prompt_text = "original-prompt"
    judge_model = object()
    optimizer_model = object()
    model_callback = object()
    goldens = ["golden"]

    class FakeOptimizer:
        def optimize(self, *, prompt, goldens):
            return type("OptimizedPrompt", (), {"text_template": input_prompt_text})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_prompt.py",
            "--output",
            str(output_path),
            "--allow-noop",
        ],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: input_prompt_text,
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: goldens,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    main()  # Should NOT raise SystemExit

    # Output file should still NOT be written (no-op never overwrites)
    assert not output_path.exists()


def test_main_noop_writes_report_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    report_path = tmp_path / "report.json"
    input_prompt_text = "original-prompt"
    judge_model = object()
    optimizer_model = object()
    model_callback = object()
    goldens = ["golden"]

    class FakeOptimizer:
        def optimize(self, *, prompt, goldens):
            return type("OptimizedPrompt", (), {"text_template": input_prompt_text})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_prompt.py",
            "--output",
            str(output_path),
            "--report-output",
            str(report_path),
            "--allow-noop",
        ],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: input_prompt_text,
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: goldens,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    main()

    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["prompt_changed"] is False
    assert "optimization_id" in report
    assert "input_prompt_hash" in report
    assert "output_prompt_hash" in report
    assert report["input_prompt_hash"] == report["output_prompt_hash"]
    assert report["output_prompt_path"] == str(output_path)

    captured = capsys.readouterr()
    assert "本次优化没有产生有效 prompt 改写" in captured.out


# --- optimize_prompt: report JSON tests ---


def test_main_writes_report_json_on_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    report_path = tmp_path / "report.json"
    judge_model = object()
    optimizer_model = object()
    model_callback = object()
    goldens = ["golden"]

    class FakeOptimizer:
        optimization_report = type(
            "OptimizationReport",
            (),
            {"optimization_id": "opt-456"},
        )()

        def optimize(self, *, prompt, goldens):
            return type("OptimizedPrompt", (), {"text_template": "optimized-text"})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_prompt.py",
            "--output",
            str(output_path),
            "--report-output",
            str(report_path),
        ],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: "original-text",
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: goldens,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    main()

    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["prompt_changed"] is True
    assert report["optimization_id"] == "opt-456"
    assert report["input_prompt_hash"] == _sha256_text("original-text")
    assert report["output_prompt_hash"] == _sha256_text("optimized-text")
    assert report["input_prompt_hash"] != report["output_prompt_hash"]
    assert report["output_prompt_path"] == str(output_path)
    assert "prompt_configurations" in report
    assert "pareto_scores" in report


# --- optimize_prompt: CLI argument tests ---


def test_main_input_prompt_path_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    input_prompt_path = tmp_path / "my_prompt.txt"
    input_prompt_path.write_text("my-custom-prompt", encoding="utf-8")
    calls: dict[str, object] = {}
    judge_model = object()
    optimizer_model = object()
    model_callback = object()

    class FakeOptimizer:
        optimization_report = type(
            "OptimizationReport",
            (),
            {"optimization_id": "opt-789"},
        )()

        def optimize(self, *, prompt, goldens):
            return type("OptimizedPrompt", (), {"text_template": "optimized-text"})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_prompt.py",
            "--output",
            str(output_path),
            "--input-prompt-path",
            str(input_prompt_path),
        ],
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: ["golden"],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_prompt",
        lambda **kwargs: (
            calls.update({"build_prompt_kwargs": kwargs})
            or type("Prompt", (), {"text_template": "optimized-text"})()
        ),
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    main()

    assert calls["build_prompt_kwargs"] == {
        "text_template": "my-custom-prompt",
    }


def test_main_prompt_variant_citations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "optimized_prompt.txt"
    calls: dict[str, object] = {}
    judge_model = object()
    optimizer_model = object()
    model_callback = object()

    class FakeOptimizer:
        optimization_report = type(
            "OptimizationReport",
            (),
            {"optimization_id": "opt-var"},
        )()

        def optimize(self, *, prompt, goldens):
            return type("OptimizedPrompt", (), {"text_template": "optimized-text"})()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize_prompt.py",
            "--output",
            str(output_path),
            "--prompt-variant",
            "citations",
        ],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt._load_packaged_template",
        lambda variant: calls.update({"variant": variant}) or "citations-template",
    )
    _eval_model_call_idx = 0

    def _dispatch_eval_model(**kwargs):
        nonlocal _eval_model_call_idx
        _eval_model_call_idx += 1
        return judge_model if _eval_model_call_idx == 1 else optimizer_model

    monkeypatch.setattr(
        "evals.optimize_prompt.build_eval_model",
        _dispatch_eval_model,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.load_goldens",
        lambda path: ["golden"],
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.validate_goldens",
        lambda goldens: None,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_model_callback",
        lambda **kwargs: model_callback,
    )
    monkeypatch.setattr(
        "evals.optimize_prompt.build_optimizer",
        lambda **kwargs: FakeOptimizer(),
    )

    main()

    assert calls["variant"] == "citations"
