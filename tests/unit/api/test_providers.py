from __future__ import annotations

from pathlib import Path

import pytest

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.app import create_app
from ragflow_lite.config import (
    ArkEmbeddingRuntimeConfig,
    OpenAIAnsweringRuntimeConfig,
    Settings,
)
from ragflow_lite.infrastructure import ArkMultimodalTextEmbedder, VectorRetriever
from ragflow_lite.infrastructure.answerers.openai_responses import (
    OpenAIResponsesAnswerer,
)


def _build_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
    )
    settings.ensure_directories()
    return settings


def test_settings_reject_missing_required_runtime_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="OPENAI_API_KEY, ARK_API_KEY, ARK_EMBEDDING_MODEL",
    ):
        settings.require_runtime_provider_configs()


def test_settings_group_runtime_provider_configuration(
    tmp_path: Path,
) -> None:
    ark_config, openai_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert ark_config == ArkEmbeddingRuntimeConfig(
        api_key="test-ark-api-key",
        model="ep-test-model",
        dimensions=None,
    )
    assert openai_config == OpenAIAnsweringRuntimeConfig(
        api_key="test-openai-api-key",
        base_url="https://code.rayinai.com/v1",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        store=False,
        verbosity="medium",
    )


def test_create_app_rejects_missing_ark_embedding_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(RuntimeError, match="ARK_EMBEDDING_MODEL"):
        create_app(settings)


def test_build_services_shares_the_same_ark_embedder_between_pipelines(
    tmp_path: Path,
) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert isinstance(services.retriever, VectorRetriever)
    assert services.ingestion_pipeline.embedder is services.retriever.embedder
    assert services.query_service.retriever is services.retriever
    answerer = services.query_service.answerer
    assert isinstance(answerer, OpenAIResponsesAnswerer)
    assert answerer.base_url == "https://code.rayinai.com/v1"
