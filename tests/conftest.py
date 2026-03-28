from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

os.environ.setdefault("OPENAI_API_KEY", "test-openai-api-key")
os.environ.setdefault("ARK_API_KEY", "test-ark-api-key")
os.environ.setdefault("ARK_EMBEDDING_MODEL", "ep-test-model")

from ragflow_lite.app import create_app
from ragflow_lite.config import Settings


@pytest.fixture
def fixture_documents_dir() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / "documents"


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    settings.ensure_directories()
    return settings


@pytest.fixture
def app(app_settings: Settings):
    return create_app(app_settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
