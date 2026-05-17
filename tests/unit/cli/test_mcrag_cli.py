from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ragflow_lite.api.deps.providers import AppServices
from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import AnswerBlueprint, AnswerResult, RetrievedChunk


def _chunk(
    chunk_id: str,
    *,
    score: float,
    metadata: dict[str, object] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=f"text-{chunk_id}",
        score=score,
        metadata=dict(metadata or {}),
    )


def _blueprint() -> AnswerBlueprint:
    return AnswerBlueprint(
        ordered_chunk_ids=["c1", "c2"],
        chunk_roles={"c1": "lead", "c2": "support"},
        answer_constraints=["只基于检索证据"],
        plan_steps=["先回答主结论", "再补充依据"],
        metadata={"debug": "hidden"},
    )


@dataclass
class FakeQueryPath:
    result: AnswerResult
    calls: list[tuple[str, int]] = field(default_factory=list)
    error: Exception | None = None

    def build_answer_request(self, query: str, top_k: int):
        from ragflow_lite.domain.models import AnswerRequest

        self.calls.append((query, top_k))
        if self.error is not None:
            raise self.error
        blueprint_data = self.result.metadata.get("blueprint")
        blueprint = None
        if isinstance(blueprint_data, dict):
            blueprint = AnswerBlueprint(
                ordered_chunk_ids=list(blueprint_data["ordered_chunk_ids"]),
                chunk_roles=dict(blueprint_data["chunk_roles"]),
                answer_constraints=list(blueprint_data["answer_constraints"]),
                plan_steps=list(blueprint_data["plan_steps"]),
            )
        return AnswerRequest(
            query=query,
            contexts=self.result.contexts,
            mode="discorag" if blueprint is not None else "standard",
            blueprint=blueprint,
            metadata={
                key: value
                for key, value in self.result.metadata.items()
                if key != "blueprint"
            },
        )


@dataclass
class FakeQueryRouter:
    result: AnswerResult
    calls: list[tuple[str, int, str]] = field(default_factory=list)
    error: Exception | None = None

    def query(self, query: str, top_k: int, mode: str = "standard") -> AnswerResult:
        self.calls.append((query, top_k, mode))
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class FakeServices:
    query_service: FakeQueryPath
    discorag_query_service: FakeQueryPath
    query_router: FakeQueryRouter


def _services_factory() -> tuple[FakeServices, callable]:
    standard_service = FakeQueryPath(
        result=AnswerResult(
            answer="unused",
            contexts=[
                _chunk("c2", score=0.6, metadata={"rank": 2}),
                _chunk("c1", score=0.9, metadata={"rank": 1}),
            ],
            metadata={"answer_mode": "standard"},
        )
    )
    discorag_service = FakeQueryPath(
        result=AnswerResult(
            answer="unused",
            contexts=[
                _chunk("c1", score=0.9, metadata={"kind": "lead"}),
                _chunk("c2", score=0.6, metadata={"kind": "support"}),
            ],
            metadata={
                "answer_mode": "discorag",
                "blueprint": {
                    "chunk_roles": _blueprint().chunk_roles,
                    "answer_constraints": _blueprint().answer_constraints,
                    "plan_steps": _blueprint().plan_steps,
                    "ordered_chunk_ids": _blueprint().ordered_chunk_ids,
                },
            },
        )
    )
    query_router = FakeQueryRouter(
        result=AnswerResult(
            answer="MicroRAG answer",
            contexts=[
                _chunk("c1", score=0.9, metadata={"rank": 1}),
                _chunk("c2", score=0.6, metadata={"rank": 2}),
            ],
            metadata={"mode": "standard", "trace_id": "req-1"},
        )
    )
    services = FakeServices(
        query_service=standard_service,
        discorag_query_service=discorag_service,
        query_router=query_router,
    )
    return services, lambda: services


def test_retrieve_outputs_model_facing_json_only_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    _, factory = _services_factory()

    exit_code = main(
        [
            "retrieve",
            "--query",
            "What is MicroRAG?",
            "--top-n",
            "2",
            "--json",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "query": "What is MicroRAG?",
        "contexts": [
            {
                "chunk_id": "c1",
                "document_id": "doc-c1",
                "text": "text-c1",
                "score": 0.9,
                "metadata": {"rank": 1},
            },
            {
                "chunk_id": "c2",
                "document_id": "doc-c2",
                "text": "text-c2",
                "score": 0.6,
                "metadata": {"rank": 2},
            },
        ],
    }
    assert "runtime_metadata" not in captured.out
    assert "debug" not in captured.out
    assert "mode" not in payload
    assert "metadata" not in payload


def test_retrieve_discorag_outputs_blueprint_at_tail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    _, factory = _services_factory()

    exit_code = main(
        [
            "retrieve",
            "--query",
            "How does DiscoRAG work?",
            "--mode",
            "discorag",
            "--top-n",
            "2",
            "--json",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert list(payload.keys()) == ["query", "contexts", "blueprint"]
    assert payload["blueprint"] == {
        "chunk_roles": {"c1": "lead", "c2": "support"},
        "answer_constraints": ["只基于检索证据"],
        "plan_steps": ["先回答主结论", "再补充依据"],
        "ordered_chunk_ids": ["c1", "c2"],
    }


def test_answer_outputs_answer_contexts_metadata_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    services, factory = _services_factory()

    exit_code = main(
        [
            "answer",
            "--query",
            "Answer it",
            "--mode",
            "discorag",
            "--top-n",
            "2",
            "--json",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "answer": "MicroRAG answer",
        "contexts": [
            {
                "chunk_id": "c1",
                "document_id": "doc-c1",
                "text": "text-c1",
                "score": 0.9,
                "metadata": {"rank": 1},
            },
            {
                "chunk_id": "c2",
                "document_id": "doc-c2",
                "text": "text-c2",
                "score": 0.6,
                "metadata": {"rank": 2},
            },
        ],
        "metadata": {"mode": "standard", "trace_id": "req-1"},
    }
    assert services.query_router.calls == [("Answer it", 2, "discorag")]


def test_setup_error_goes_to_stderr_and_empty_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    def failing_factory() -> AppServices:
        raise RuntimeError("missing config")

    exit_code = main(
        [
            "retrieve",
            "--query",
            "q",
            "--json",
        ],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "setup error:" in captured.err
    assert "missing config" in captured.err


def test_retrieve_runtime_ragflow_error_returns_one_and_reports_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    services, factory = _services_factory()
    services.query_service.error = ProcessingError("retrieve failed")

    exit_code = main(
        [
            "retrieve",
            "--query",
            "q",
            "--json",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "MicroRAG error:" in captured.err
    assert "retrieve failed" in captured.err


def test_answer_runtime_error_returns_one_and_reports_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    services, factory = _services_factory()
    services.query_router.error = RuntimeError("answer exploded")

    exit_code = main(
        [
            "answer",
            "--query",
            "q",
            "--json",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Runtime error:" in captured.err
    assert "answer exploded" in captured.err


def test_cli_requires_json_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    _, factory = _services_factory()

    exit_code = main(
        [
            "retrieve",
            "--query",
            "q",
        ],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "--json" in captured.err


def test_pyproject_registers_mcrag_script() -> None:
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert "[project.scripts]" in text
    assert 'mcrag = "ragflow_lite.cli.mcrag:main"' in text


def test_importing_mcrag_module_keeps_runtime_stack_unloaded() -> None:
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-c",
        (
            "import importlib, json, sys; "
            "sys.path.insert(0, 'src'); "
            "importlib.import_module('ragflow_lite.cli.mcrag'); "
            "print(json.dumps(sorted(name for name in sys.modules "
            "if name.startswith('ragflow_lite'))))"
        ),
    ]

    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
    )

    loaded_modules = set(json.loads(result.stdout))
    assert "ragflow_lite.cli.mcrag" in loaded_modules
    assert "ragflow_lite.domain.models" not in loaded_modules
    assert "ragflow_lite.domain.errors" not in loaded_modules
    assert "ragflow_lite.api.deps.providers" not in loaded_modules
    assert "ragflow_lite.config" not in loaded_modules


def test_package_root_exports_app_proxy_without_importing_app_module() -> None:
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-c",
        (
            "import json, sys; "
            "sys.path.insert(0, 'src'); "
            "from ragflow_lite import app, create_app; "
            "print(json.dumps({"
            "'create_app_callable': callable(create_app), "
            "'app_type': type(app).__name__, "
            "'app_module_loaded': 'ragflow_lite.app' in sys.modules"
            "}))"
        ),
    ]

    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
    )

    payload = json.loads(result.stdout)
    assert payload == {
        "create_app_callable": True,
        "app_type": "_LazyAppExport",
        "app_module_loaded": False,
    }


def test_agent_setup_command_migrates_legacy_runtime_assets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    legacy_workspace = tmp_path / "data" / "agent-runtime" / "workspace"
    (legacy_workspace / ".claude" / "skills" / "microrag-search").mkdir(parents=True)
    (legacy_workspace / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    (legacy_workspace / "CLAUDE.md").write_text(
        "# MicroRAG Product Agent\n",
        encoding="utf-8",
    )
    (
        legacy_workspace / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).write_text(
        "---\nname: microrag-search\n---\n# MicroRAG Search\n",
        encoding="utf-8",
    )

    exit_code = main(["agent", "setup", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "config_dir": str(tmp_path / "data" / "agent-runtime" / "config"),
        "workspace_dir": str(tmp_path / "参考项目" / "claude-code"),
    }
    assert (tmp_path / "data" / "agent-runtime" / "config").is_dir()
    assert (tmp_path / "参考项目" / "claude-code" / "CLAUDE.md").exists()
    assert (
        tmp_path
        / "参考项目"
        / "claude-code"
        / ".claude"
        / "skills"
        / "microrag-search"
        / "SKILL.md"
    ).exists()
    assert (
        tmp_path / "参考项目" / "claude-code" / ".claude" / "settings.json"
    ).exists()


def test_agent_setup_does_not_build_runtime_services(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    def failing_factory() -> AppServices:
        raise AssertionError("setup must not build AppServices")

    exit_code = main(
        ["agent", "setup", "--project-root", str(tmp_path)],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""


def test_runtime_setup_error_marker_is_lowercase(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    def failing_factory() -> AppServices:
        raise RuntimeError("missing config")

    exit_code = main(
        ["retrieve", "--query", "q", "--json"],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.startswith("setup error: missing config")
