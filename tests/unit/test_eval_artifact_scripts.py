from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("deepeval")

from deepeval.dataset import Golden  # noqa: E402
from evals.cleanup_infinity import select_eval_cleanup_tables  # noqa: E402
from evals.generate_goldens import (  # noqa: E402
    DEFAULT_GOLDENS_PATH,
    generate_goldens_artifact,
    golden_to_payload,
    sync_eval_source_documents,
)
from evals.optimize_prompt import build_optimizer, load_goldens  # noqa: E402

_EXPECTED_EVAL_SOURCE_FILES = {
    "Best Practices for Claude Code.md": 10,
    "CodexBestpractices.md": 10,
    "Faithfulness.md": 10,
    "MinerU_markdown_603260_20260417_2LSZ.md": 10,
    "MinerU_markdown_中华人民共和国劳动法.md": 10,
    "MinerU_markdown_附件1：《期货公司监督管理办法（征求意见稿）》.md": 10,
}


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
        def __init__(self, model=None):
            self.model = model

        def generate_goldens_from_docs(
            self,
            doc_paths,
            *,
            include_expected_output,
            max_goldens_per_context,
        ):
            assert doc_paths == [str(document_path)]
            assert include_expected_output is True
            assert max_goldens_per_context == 10
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


def test_build_optimizer_uses_gepa_and_rag_triad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

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

    build_optimizer(judge_model="judge-model", model_callback=lambda prompt, golden: "")

    assert captured["algorithm"].__class__ is FakeGEPA
    assert captured["metrics"] == [
        ("AnswerRelevancyMetric", "judge-model"),
        ("FaithfulnessMetric", "judge-model"),
        ("ContextualRelevancyMetric", "judge-model"),
    ]


def test_select_eval_cleanup_tables_targets_eval_residue() -> None:
    assert select_eval_cleanup_tables(
        [
            "documents",
            "chunks",
            "documents_datasets",
            "documents_dataset_bindings",
            "documents_liveeval",
            "chunks_liveeval",
            "other_table",
        ]
    ) == [
        "chunks",
        "chunks_liveeval",
        "documents",
        "documents_dataset_bindings",
        "documents_datasets",
        "documents_liveeval",
    ]
