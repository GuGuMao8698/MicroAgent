from __future__ import annotations

from pathlib import Path

import pytest

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.app import create_app
from ragflow_lite.application.services import MiniRAGTopologyRetriever
from ragflow_lite.config import (
    ArkEmbeddingRuntimeConfig,
    OpenAIAnsweringRuntimeConfig,
    Settings,
)
from ragflow_lite.infrastructure import (
    ArkMultimodalTextEmbedder,
    InfinityDenseVectorIndex,
    InfinityHybridRetriever,
    LocalJsonGraphEvidenceStore,
    OpenAIResponsesEvidenceExtractor,
)
from ragflow_lite.infrastructure import retrievers as retrievers_module
from ragflow_lite.infrastructure.answerers.openai_responses import (
    OpenAIResponsesAnswerer,
)
from ragflow_lite.infrastructure.retrievers import OpenAIResponsesQueryGrounder


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
        dimensions=2048,
    )
    assert openai_config == OpenAIAnsweringRuntimeConfig(
        api_key="test-openai-api-key",
        base_url="https://code.rayinai.com/v1",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        prompt_path=None,
        store=False,
        verbosity="medium",
        render_citations=True,
    )


def test_settings_reads_optional_answerer_prompt_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RAGFLOW_LITE_OPENAI_ANSWER_PROMPT_PATH",
        "/tmp/optimized_answerer_prompt.txt",
    )

    _, openai_config = _build_settings(tmp_path).require_runtime_provider_configs()

    assert openai_config.prompt_path == "/tmp/optimized_answerer_prompt.txt"


def test_settings_reads_optional_render_citations_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    _, openai_config = _build_settings(tmp_path).require_runtime_provider_configs()

    assert openai_config.render_citations is False


def test_build_services_resolves_relative_answerer_prompt_path_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_relative_path = Path("tests/fixtures/evals/runtime_override.txt")
    prompt_path = tmp_path / prompt_relative_path
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Runtime override instructions.", encoding="utf-8")
    monkeypatch.setenv(
        "RAGFLOW_LITE_OPENAI_ANSWER_PROMPT_PATH",
        str(prompt_relative_path),
    )
    off_repo_dir = tmp_path / "other-working-dir"
    off_repo_dir.mkdir()
    monkeypatch.chdir(off_repo_dir)

    services = build_services(_build_settings(tmp_path))

    answerer = services.query_service.answerer
    assert isinstance(answerer, OpenAIResponsesAnswerer)
    assert answerer.instructions == "Runtime override instructions."


def test_build_services_threads_render_citations_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    services = build_services(_build_settings(tmp_path))

    answerer = services.query_service.answerer
    assert isinstance(answerer, OpenAIResponsesAnswerer)
    assert answerer.render_citations is False


def test_create_app_rejects_missing_ark_embedding_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(RuntimeError, match="ARK_EMBEDDING_MODEL"):
        create_app(settings)


def test_build_services_uses_infinity_hybrid_retriever(
    tmp_path: Path,
) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(services.query_service.retriever, MiniRAGTopologyRetriever)
    assert isinstance(
        services.query_service.retriever.base_retriever, InfinityHybridRetriever
    )
    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert (
        services.ingestion_pipeline.embedder
        is services.query_service.retriever.base_retriever.embedder
    )
    assert isinstance(
        services.ingestion_pipeline.vector_index, InfinityDenseVectorIndex
    )
    answerer = services.query_service.answerer
    assert isinstance(answerer, OpenAIResponsesAnswerer)
    assert answerer.base_url == "https://code.rayinai.com/v1"


def test_build_services_wires_graph_evidence_dependencies(tmp_path: Path) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(
        services.ingestion_pipeline.graph_store,
        LocalJsonGraphEvidenceStore,
    )
    assert isinstance(
        services.ingestion_pipeline.evidence_extractor,
        OpenAIResponsesEvidenceExtractor,
    )


def test_infrastructure_exports_current_runtime_components() -> None:
    from ragflow_lite import infrastructure

    assert infrastructure.__all__ == [
        "ArkMultimodalTextEmbedder",
        "BackgroundTaskRunner",
        "CompositeParser",
        "RecursiveCharacterChunker",
        "InfinityDenseVectorIndex",
        "InfinityHybridRetriever",
        "InlineTaskRunner",
        "InMemoryStageCache",
        "InMemoryTaskStore",
        "LocalDocumentStore",
        "LocalJsonGraphEvidenceStore",
        "LocalJsonVectorIndex",
        "OpenAIResponsesAnswerer",
        "OpenAIResponsesEvidenceExtractor",
    ]
    assert retrievers_module.__all__ == [
        "InfinityHybridRetriever",
        "OpenAIResponsesQueryGrounder",
    ]
    assert not hasattr(infrastructure, "VectorRetriever")
    assert not hasattr(infrastructure, "InfinityFullTextRetriever")
    assert not hasattr(retrievers_module, "VectorRetriever")
    assert not hasattr(retrievers_module, "InfinityFullTextRetriever")


def test_build_services_wires_minirag_topology_retriever(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)

    services = build_services(settings)

    assert isinstance(services.query_service.retriever, MiniRAGTopologyRetriever)
    assert isinstance(
        services.query_service.retriever.query_grounder,
        OpenAIResponsesQueryGrounder,
    )
    assert services.query_service.retriever.graph_store is (
        services.ingestion_pipeline.graph_store
    )


def test_build_services_embedder_dimensions_match_settings(
    tmp_path: Path,
) -> None:
    services = build_services(_build_settings(tmp_path))
    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert services.ingestion_pipeline.embedder.signature["dimensions"] == 2048


def test_settings_rejects_legacy_retrieval_mode_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_RETRIEVAL_MODE", "dense")
    with pytest.raises(
        RuntimeError, match="RAGFLOW_LITE_RETRIEVAL_MODE is no longer supported"
    ):
        _build_settings(tmp_path)


def test_build_services_provides_document_service(tmp_path: Path) -> None:
    from ragflow_lite.application import DocumentService

    services = build_services(_build_settings(tmp_path))
    assert isinstance(services.document_service, DocumentService)
    assert services.document_service.catalog is services.ingestion_pipeline.vector_index


def test_settings_default_observability_and_infinity_values(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)

    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.metrics_enabled is False
    assert settings.infinity_host == "127.0.0.1"
    assert settings.infinity_port == 23817


def test_settings_reads_observability_and_infinity_envs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("RAGFLOW_LITE_LOG_FORMAT", "json")
    monkeypatch.setenv("RAGFLOW_LITE_METRICS_ENABLED", "true")
    monkeypatch.setenv("RAGFLOW_LITE_INFINITY_HOST", "host.docker.internal")
    monkeypatch.setenv("RAGFLOW_LITE_INFINITY_PORT", "31000")

    settings = _build_settings(tmp_path)

    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"
    assert settings.metrics_enabled is True
    assert settings.infinity_host == "host.docker.internal"
    assert settings.infinity_port == 31000


def test_settings_rejects_invalid_metrics_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_METRICS_ENABLED", "maybe")

    with pytest.raises(RuntimeError, match="RAGFLOW_LITE_METRICS_ENABLED"):
        _build_settings(tmp_path)
