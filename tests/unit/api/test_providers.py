from __future__ import annotations

from pathlib import Path

import pytest

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.app import create_app
from ragflow_lite.application.services import (
    DiscoRAGAnswerBlueprintBuilder,
    DiscoRAGQueryService,
    EvidencePackageBuilder,
    MiniGraphFirstRetriever,
    QueryModeRouter,
)
from ragflow_lite.config import (
    ArkEmbeddingRuntimeConfig,
    DeepSeekRuntimeConfig,
    Settings,
)
from ragflow_lite.infrastructure import (
    ArkMultimodalTextEmbedder,
    DeepSeekChatAnswerer,
    DeepSeekChatEvidenceExtractor,
    DeepSeekChatIntraChunkDiscourseExtractor,
    InfinityDenseVectorIndex,
    InfinityHybridRetriever,
    LocalJsonGraphEvidenceStore,
)
from ragflow_lite.infrastructure import retrievers as retrievers_module
from ragflow_lite.infrastructure.evidence import (
    GraphCandidateSidecar,
    GraphEvidenceSidecarStore,
    LocalJsonGraphEvidenceHybridIndex,
)
from ragflow_lite.infrastructure.retrievers import DeepSeekChatQueryGrounder


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
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_EMBEDDING_MODEL", raising=False)
    settings = _build_settings(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="DEEPSEEK_API_KEY, ARK_API_KEY, ARK_EMBEDDING_MODEL",
    ):
        settings.require_runtime_provider_configs()


def test_settings_group_runtime_provider_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-api-key")
    monkeypatch.setenv("ARK_API_KEY", "test-ark-api-key")
    monkeypatch.setenv("ARK_EMBEDDING_MODEL", "ep-test-model")

    ark_config, deepseek_config = _build_settings(
        tmp_path
    ).require_runtime_provider_configs()

    assert ark_config == ArkEmbeddingRuntimeConfig(
        api_key="test-ark-api-key",
        model="ep-test-model",
        dimensions=2048,
    )
    assert deepseek_config == DeepSeekRuntimeConfig(
        api_key="test-deepseek-api-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        reasoning_effort="high",
        prompt_path=None,
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

    _, deepseek_config = _build_settings(tmp_path).require_runtime_provider_configs()

    assert deepseek_config.prompt_path == "/tmp/optimized_answerer_prompt.txt"


def test_settings_reads_optional_render_citations_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    _, deepseek_config = _build_settings(tmp_path).require_runtime_provider_configs()

    assert deepseek_config.render_citations is False


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
    assert isinstance(answerer, DeepSeekChatAnswerer)
    assert answerer.instructions == "Runtime override instructions."


def test_build_services_threads_render_citations_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGFLOW_LITE_OPENAI_RENDER_CITATIONS", "false")

    services = build_services(_build_settings(tmp_path))

    answerer = services.query_service.answerer
    assert isinstance(answerer, DeepSeekChatAnswerer)
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

    # 图优先检索器作为主检索器
    assert isinstance(services.query_service.retriever, MiniGraphFirstRetriever)
    # InfinityHybridRetriever 作为 chunk 辅助检索器
    assert isinstance(
        services.query_service.retriever.chunk_auxiliary_retriever,
        InfinityHybridRetriever,
    )
    assert isinstance(services.ingestion_pipeline.embedder, ArkMultimodalTextEmbedder)
    assert (
        services.ingestion_pipeline.embedder
        is services.query_service.retriever.chunk_auxiliary_retriever.embedder
    )
    assert isinstance(
        services.ingestion_pipeline.vector_index, InfinityDenseVectorIndex
    )
    answerer = services.query_service.answerer
    assert isinstance(answerer, DeepSeekChatAnswerer)
    assert answerer.model == "deepseek-v4-flash"
    assert answerer.reasoning_effort == "high"


def test_build_services_wires_graph_evidence_dependencies(tmp_path: Path) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(
        services.ingestion_pipeline.graph_store, GraphEvidenceSidecarStore
    )
    assert isinstance(
        services.ingestion_pipeline.graph_store._graph_store,
        LocalJsonGraphEvidenceStore,
    )
    assert isinstance(
        services.ingestion_pipeline.graph_store._sidecar,
        GraphCandidateSidecar,
    )
    assert isinstance(
        services.ingestion_pipeline.evidence_extractor,
        DeepSeekChatEvidenceExtractor,
    )


def test_infrastructure_exports_current_runtime_components() -> None:
    from ragflow_lite import infrastructure

    assert infrastructure.__all__ == [
        "ArkMultimodalTextEmbedder",
        "BackgroundTaskRunner",
        "CompositeParser",
        "DeepSeekChatAnswerer",
        "DeepSeekChatEvidenceExtractor",
        "DeepSeekChatIntraChunkDiscourseExtractor",
        "GraphCandidateSidecar",
        "GraphEvidenceSidecarStore",
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
        "DeepSeekChatQueryGrounder",
        "InfinityHybridRetriever",
        "OpenAIResponsesQueryGrounder",
    ]
    assert not hasattr(infrastructure, "VectorRetriever")
    assert not hasattr(infrastructure, "InfinityFullTextRetriever")
    assert not hasattr(retrievers_module, "VectorRetriever")
    assert not hasattr(retrievers_module, "InfinityFullTextRetriever")


def test_build_services_wires_mini_graph_first_retriever(tmp_path: Path) -> None:
    """验证 build_services 组装 MiniGraphFirstRetriever 并在两个 query service 间共享。"""
    settings = _build_settings(tmp_path)

    services = build_services(settings)

    # 主检索器是 MiniGraphFirstRetriever
    assert isinstance(services.retriever, MiniGraphFirstRetriever)
    # 两个 query service 共享同一个检索器实例
    assert services.query_service.retriever is services.retriever
    assert services.discorag_query_service.retriever is services.retriever
    # query_grounder 正确装配
    assert isinstance(services.retriever.query_grounder, DeepSeekChatQueryGrounder)
    # 图证据混合索引正确装配，且 entity/relationship/path_expander 共用同一实例
    assert isinstance(
        services.retriever.entity_index, LocalJsonGraphEvidenceHybridIndex
    )
    assert services.retriever.entity_index._canonicalize_cross_document is True
    assert services.retriever.entity_index is services.retriever.relationship_index
    assert services.retriever.entity_index is services.retriever.path_expander
    # 共享实例验证：sidecar 和 embedder 跨 pipeline 复用
    assert (
        services.retriever.entity_index.sidecar
        is services.ingestion_pipeline.graph_store._sidecar
    )
    assert (
        services.retriever.entity_index.embedder is services.ingestion_pipeline.embedder
    )
    # chunk_lookup 使用 vector_index
    assert services.retriever.chunk_lookup is services.ingestion_pipeline.vector_index
    # chunk_auxiliary_retriever 使用 InfinityHybridRetriever
    assert isinstance(
        services.retriever.chunk_auxiliary_retriever, InfinityHybridRetriever
    )


def test_build_services_wires_discorag_query_service(tmp_path: Path) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(services.discorag_query_service, DiscoRAGQueryService)
    assert services.discorag_query_service.retriever is services.retriever
    assert services.discorag_query_service.answerer is services.query_service.answerer
    assert isinstance(
        services.discorag_query_service.evidence_package_builder,
        EvidencePackageBuilder,
    )
    assert isinstance(
        services.discorag_query_service.discourse_extractor,
        DeepSeekChatIntraChunkDiscourseExtractor,
    )
    assert isinstance(
        services.discorag_query_service.blueprint_builder,
        DiscoRAGAnswerBlueprintBuilder,
    )


def test_build_services_wires_query_mode_router(tmp_path: Path) -> None:
    services = build_services(_build_settings(tmp_path))

    assert isinstance(services.query_router, QueryModeRouter)
    assert services.query_router.standard_service is services.query_service
    assert services.query_router.discorag_service is services.discorag_query_service


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
