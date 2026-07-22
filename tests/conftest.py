from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
TESTS_PATH = PROJECT_ROOT / "tests"
EVALS_PATH = TESTS_PATH / "evals"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(TESTS_PATH) not in sys.path:
    sys.path.insert(0, str(TESTS_PATH))
if str(EVALS_PATH) not in sys.path:
    sys.path.insert(0, str(EVALS_PATH))

from eval_support import EVAL_QUERY_MODES, validate_deepeval_env
from evals.private_bootstrap_eval_corpus import (
    assign_private_bootstrap_eval_tables,
    validate_private_bootstrap_reuse_ready,
)
from helpers.local_env import load_export_env_file
from infinity_test_support import (
    assign_isolated_infinity_tables,
    clear_registered_infinity_tables,
    drop_registered_infinity_tables,
    register_infinity_table_cleanup,
)


class _PytestOptionConfig(Protocol):
    def getoption(self, name: str) -> object: ...


class _PytestOptionRequest(Protocol):
    @property
    def config(self) -> _PytestOptionConfig: ...


def _validate_deepeval_reuse_corpus_for_settings(settings, request):
    if request.node.get_closest_marker("deepeval") is None:
        return None
    if not request.config.getoption("--run-deepeval"):
        return None
    if request.config.getoption("--deepeval-corpus-mode") != "reuse":
        return None
    return validate_private_bootstrap_reuse_ready(settings)


load_export_env_file(PROJECT_ROOT / "data" / "local.env")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-api-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-api-key")
os.environ.setdefault("ARK_API_KEY", "test-ark-api-key")
os.environ.setdefault("ARK_EMBEDDING_MODEL", "ep-test-model")
for _name in (
    "RAGFLOW_LITE_LOG_LEVEL",
    "RAGFLOW_LITE_LOG_FORMAT",
    "RAGFLOW_LITE_METRICS_ENABLED",
):
    os.environ.pop(_name, None)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-infinity",
        action="store_true",
        default=False,
        help="run tests that connect to a real Infinity instance",
    )
    parser.addoption(
        "--run-deepeval",
        action="store_true",
        default=False,
        help="run optional deepeval-backed evaluation tests",
    )
    parser.addoption(
        "--query-mode",
        choices=EVAL_QUERY_MODES,
        default=None,
        help=(
            "query mode for deepeval RAG evaluation runs "
            "(standard or discorag); defaults to standard, or "
            "RAGFLOW_LITE_EVAL_QUERY_MODE when the option is omitted"
        ),
    )
    parser.addoption(
        "--deepeval-case-concurrency",
        type=int,
        default=None,
        help=(
            "maximum concurrent golden cases for deepeval RAG evaluation runs; "
            "defaults to RAGFLOW_LITE_DEEPEVAL_CASE_CONCURRENCY or 4"
        ),
    )
    parser.addoption(
        "--deepeval-corpus-mode",
        choices=("fresh", "reuse"),
        default="reuse",
        help="deepeval corpus table mode; reuse uses private-bootstrap eval tables",
    )
    parser.addoption(
        "--deepeval-case-range",
        default=None,
        help="1-based inclusive deepeval case range START:END",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_infinity: connect to a real Infinity instance",
    )
    config.addinivalue_line(
        "markers",
        "deepeval: run optional deepeval-based RAG evaluation",
    )

    if config.getoption("--run-deepeval"):
        import importlib.util

        if importlib.util.find_spec("deepeval") is None:
            raise pytest.UsageError(
                "--run-deepeval requires the 'deepeval' package. "
                "Install it with: pip install deepeval"
            )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    skip_live_infinity = pytest.mark.skip(
        reason="need --run-live-infinity to run tests against real Infinity"
    )
    skip_deepeval = pytest.mark.skip(
        reason="need --run-deepeval to run deepeval-based evaluation tests"
    )
    run_deepeval = config.getoption("--run-deepeval")
    run_live_infinity = config.getoption("--run-live-infinity") or run_deepeval

    for item in items:
        if item.get_closest_marker("deepeval") is not None and not run_deepeval:
            item.add_marker(skip_deepeval)

        if (
            item.get_closest_marker("live_infinity") is not None
            and not run_live_infinity
        ):
            item.add_marker(skip_live_infinity)


@pytest.fixture(autouse=True)
def _require_deepeval_runtime_env(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("deepeval") is None:
        return
    if not request.config.getoption("--run-deepeval"):
        return
    validate_deepeval_env(os.environ)


@pytest.fixture(autouse=True)
def _set_deepeval_plain_prompt_variant(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep deepeval prompt rendering citation-free for metric stability."""
    if request.node.get_closest_marker("deepeval") is None:
        return
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")


@pytest.fixture
def fixture_documents_dir() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / "documents"


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int | pytest.ExitCode,
) -> None:
    run_live_infinity = session.config.getoption("--run-live-infinity")
    run_deepeval = session.config.getoption("--run-deepeval")
    if run_live_infinity or run_deepeval:
        drop_registered_infinity_tables()
    else:
        clear_registered_infinity_tables()


def _configure_infinity_tables_for_test_settings(
    settings,
    tmp_path: Path,
    request: _PytestOptionRequest,
):
    run_deepeval = request.config.getoption("--run-deepeval")
    corpus_mode = request.config.getoption("--deepeval-corpus-mode")
    if run_deepeval and corpus_mode == "reuse":
        return assign_private_bootstrap_eval_tables(settings)

    assign_isolated_infinity_tables(settings, tmp_path)
    register_infinity_table_cleanup(settings)
    return settings


@pytest.fixture
def app_settings(tmp_path: Path, request: pytest.FixtureRequest):
    from ragflow_lite.config import Settings

    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    _configure_infinity_tables_for_test_settings(settings, tmp_path, request)
    settings.ensure_directories()
    return settings


class _FakeDeepSeekJsonClient:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def complete_json(self, *args, **kwargs):
        return self.output_text


def _install_fake_query_support_clients(app) -> None:
    """Replace query-time DeepSeek JSON clients with deterministic fakes."""
    services = app.state.services

    extractor = getattr(services.ingestion_pipeline, "evidence_extractor", None)
    if extractor is not None:
        extractor.client = _FakeDeepSeekJsonClient('{"entities":[],"relations":[]}')

    query_grounder = getattr(services.retriever, "query_grounder", None)
    if query_grounder is not None:
        query_grounder.client = _FakeDeepSeekJsonClient(
            '{"answer_type_keywords":[],"entities_from_query":[]}'
        )


@pytest.fixture
def deepeval_reusable_manifest(app_settings, request: pytest.FixtureRequest):
    return _validate_deepeval_reuse_corpus_for_settings(app_settings, request)


@pytest.fixture
def app(app_settings, deepeval_reusable_manifest):
    from ragflow_lite.app import create_app

    return create_app(app_settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    # Tests may still stub LLMs, but storage/retrieval now always use real Infinity
    # when this fixture is allowed to run via the live_infinity gate.
    _install_fake_query_support_clients(app)

    with TestClient(app) as test_client:
        yield test_client
