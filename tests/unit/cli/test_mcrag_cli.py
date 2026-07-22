from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ragflow_lite.domain.errors import ProcessingError
from ragflow_lite.domain.models import (
    AnswerBlueprint,
    AnswerRequest,
    AnswerResult,
    RetrievedChunk,
)


def _chunk(chunk_id: str, *, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        text=f"text-{chunk_id}",
        score=score,
        metadata={"rank": int(chunk_id.removeprefix("c"))},
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
class FakeRequestBuilder:
    request: AnswerRequest
    calls: list[tuple[str, int]] = field(default_factory=list)

    def build_answer_request(self, query: str, top_k: int) -> AnswerRequest:
        self.calls.append((query, top_k))
        return self.request


@dataclass
class FakeServices:
    query_service: FakeRequestBuilder
    discorag_query_service: FakeRequestBuilder
    query_router: FakeQueryRouter


def _services_factory() -> tuple[FakeServices, Callable[[], FakeServices]]:
    services = FakeServices(
        query_service=FakeRequestBuilder(
            request=AnswerRequest(
                query="retrieval query",
                contexts=[_chunk("c2", score=0.6), _chunk("c1", score=0.9)],
            )
        ),
        discorag_query_service=FakeRequestBuilder(
            request=AnswerRequest(
                query="retrieval query",
                contexts=[_chunk("c2", score=0.6), _chunk("c1", score=0.9)],
                mode="discorag",
                blueprint=AnswerBlueprint(
                    ordered_chunk_ids=["c1", "c2"],
                    chunk_roles={"c1": "lead", "c2": "support"},
                    answer_constraints=["只基于证据"],
                    plan_steps=["先回答", "再补充"],
                ),
            )
        ),
        query_router=FakeQueryRouter(
            result=AnswerResult(
                answer="MicroRAG answer",
                contexts=[_chunk("c1", score=0.9), _chunk("c2", score=0.6)],
                metadata={"mode": "standard", "trace_id": "req-1"},
            )
        ),
    )
    return services, lambda: services


def test_retrieve_outputs_model_facing_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    services, factory = _services_factory()
    exit_code = main(
        [
            "retrieve",
            "--query",
            "retrieval query",
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
    assert list(payload) == ["query", "contexts", "blueprint"]
    assert [context["chunk_id"] for context in payload["contexts"]] == ["c1", "c2"]
    assert payload["blueprint"]["ordered_chunk_ids"] == ["c1", "c2"]
    assert services.discorag_query_service.calls == [("retrieval query", 2)]


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
    assert json.loads(captured.out) == {
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

    def failing_factory():
        raise RuntimeError("missing config")

    exit_code = main(
        ["answer", "--query", "q", "--json"],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith("setup error: missing config")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ProcessingError("answer failed"), "MicroRAG error: answer failed"),
        (RuntimeError("answer exploded"), "Runtime error: answer exploded"),
    ],
)
def test_answer_errors_are_explicit(
    error: Exception,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    services, factory = _services_factory()
    services.query_router.error = error
    exit_code = main(
        ["answer", "--query", "q", "--json"],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert message in captured.err


def test_cli_requires_json_flag(capsys: pytest.CaptureFixture[str]) -> None:
    from ragflow_lite.cli.mcrag import main

    _, factory = _services_factory()
    exit_code = main(
        ["answer", "--query", "q"],
        services_factory=factory,
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "--json" in captured.err


def test_removed_agent_command_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    assert main(["agent", "setup"]) == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_pyproject_registers_mcrag_script() -> None:
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'mcrag = "ragflow_lite.cli.mcrag:main"' in text


def test_importing_mcrag_module_keeps_runtime_stack_unloaded() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, json, sys; "
                "sys.path.insert(0, 'src'); "
                "importlib.import_module('ragflow_lite.cli.mcrag'); "
                "print(json.dumps(sorted(name for name in sys.modules "
                "if name.startswith('ragflow_lite'))))"
            ),
        ],
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

    result = subprocess.run(
        [
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
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
    )

    assert json.loads(result.stdout) == {
        "create_app_callable": True,
        "app_type": "_LazyAppExport",
        "app_module_loaded": False,
    }
